"""Publish one Power BI item, fully refreshing semantic models and preserving other items."""

import argparse
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.request import Request, urlopen
from uuid import UUID

from validate_powerbi import read_json, require


SAMPLE = Path(__file__).resolve().parents[1] / "sample"
ITEMS = {
    "semantic-model": ("Sales.SemanticModel", "SemanticModel", "Sales"),
    "sales-report": ("Sales-report.Report", "Report", "Sales-report"),
}
POWERBI_API = "https://api.powerbi.com/v1.0/myorg"
POWERBI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"


def powerbi_request(credential, method, url, body=None):
    token = credential.get_token(POWERBI_SCOPE).token
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method=method,
    )
    with urlopen(request, timeout=30) as response:
        payload = response.read()
        return (json.loads(payload) if payload else {}, response.headers)


def refresh_model(workspace_id, name, credential, timeout=900):
    base = f"{POWERBI_API}/groups/{workspace_id}/datasets"
    datasets, _ = powerbi_request(credential, "GET", base)
    matches = [dataset for dataset in datasets["value"] if dataset["name"] == name]
    require(len(matches) == 1, f"Expected exactly one published semantic model named {name}")
    model_id = str(UUID(matches[0]["id"]))
    refresh_url = f"{base}/{model_id}/refreshes"
    _, headers = powerbi_request(
        credential, "POST", refresh_url,
        {"type": "Full", "commitMode": "Transactional", "applyRefreshPolicy": False},
    )
    request_id = headers.get("x-ms-request-id") or headers.get("RequestId")
    require(request_id, "Refresh was submitted but Power BI returned no request ID")
    print(f"Full refresh of {name}; request ID: {request_id}", flush=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        history, _ = powerbi_request(credential, "GET", f"{refresh_url}?$top=60")
        refresh = next(
            (entry for entry in history["value"] if entry.get("requestId") == request_id),
            None,
        )
        if refresh is not None:
            status = refresh["status"]
            if status == "Completed":
                print(f"Fully refreshed {name}; imported data is ready")
                return
            if status not in ("Unknown", "InProgress"):
                raise RuntimeError(
                    f"Refresh of {name} ended with {status}: "
                    f"{refresh.get('serviceExceptionJson', 'No error details returned')}"
                )
        time.sleep(min(10, max(0, deadline - time.monotonic())))
    raise TimeoutError(
        f"Refresh of {name} did not complete within {timeout} seconds "
        f"(request ID: {request_id}); check Power BI refresh history"
    )


def validate_item(item, sample=SAMPLE):
    folder, item_type, name = ITEMS[item]
    directory = sample / folder
    metadata = read_json(directory / ".platform")
    require(metadata["metadata"]["type"] == item_type, f"Expected {item_type}: {directory}")
    require(metadata["metadata"]["displayName"] == name, f"Expected display name {name}: {directory}")
    UUID(metadata["config"]["logicalId"])

    if item_type == "SemanticModel":
        read_json(directory / "definition.pbism")
        for filename in ("database.tmdl", "model.tmdl", "relationships.tmdl"):
            path = directory / "definition" / filename
            require(path.is_file() and path.stat().st_size > 0, f"Missing or empty TMDL: {path}")
    else:
        connection = read_json(directory / "definition.pbir")
        model_path = connection["datasetReference"]["byPath"]["path"]
        require(
            (directory / model_path).resolve() == (sample / "Sales.SemanticModel").resolve(),
            "Sales-report must reference ../Sales.SemanticModel",
        )
        validate_item("semantic-model", sample)
        for filename in ("report.json", "version.json", "pages/pages.json"):
            read_json(directory / "definition" / filename)

    for path in directory.rglob("*.json"):
        if ".pbi" not in path.relative_to(directory).parts:
            read_json(path)
    print(f"PASS: deployment structure for {name} ({item_type})")


def publish(item, workspace_id, refresh=None):
    from azure.identity import AzureCliCredential
    from fabric_cicd import FabricWorkspace, append_feature_flag, publish_all_items

    if refresh is None:
        refresh = item == "semantic-model"
    require(not refresh or item == "semantic-model", "--refresh is only supported for semantic-model")
    validate_item(item, SAMPLE)
    workspace_id = str(UUID(workspace_id))
    _, item_type, name = ITEMS[item]
    # Keep both items discoverable so fabric-cicd resolves the report's model link.
    append_feature_flag("disable_workspace_folder_publish")
    credential = AzureCliCredential()
    workspace = FabricWorkspace(
        workspace_id=workspace_id,
        repository_directory=str(SAMPLE),
        item_type_in_scope=[item_type],
        token_credential=credential,
    )
    publish_all_items(workspace, item_name_exclude_regex=rf"^(?!{re.escape(name)}$).*")
    print(f"Published {name} ({item_type}) to workspace {workspace_id}")
    if refresh:
        refresh_model(workspace_id, name, credential)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("item", choices=ITEMS)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument(
        "--refresh", action="store_true", default=None,
        help="Fully refresh after publishing (automatic for semantic-model) and wait for completion",
    )
    arguments = parser.parse_args()
    try:
        require(
            not arguments.refresh or arguments.item == "semantic-model",
            "--refresh is only supported for semantic-model",
        )
        if arguments.validate_only:
            validate_item(arguments.item)
        else:
            workspace_id = os.environ.get("PBI_WORKSPACE_ID")
            require(workspace_id, "Set PBI_WORKSPACE_ID to the target workspace GUID")
            publish(arguments.item, workspace_id, refresh=arguments.refresh)
    except (ValueError, KeyError, OSError, RuntimeError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
