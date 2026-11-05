"""Publish one Power BI item, preserving other items in the target workspace."""

import argparse
import os
from pathlib import Path
import re
import sys
from uuid import UUID

from validate_powerbi import read_json, require


SAMPLE = Path(__file__).resolve().parents[1] / "sample"
ITEMS = {
    "semantic-model": ("Sales.SemanticModel", "SemanticModel", "Sales"),
    "sales-report": ("Sales-report.Report", "Report", "Sales-report"),
}


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


def publish(item, workspace_id):
    from azure.identity import AzureCliCredential
    from fabric_cicd import FabricWorkspace, append_feature_flag, publish_all_items

    validate_item(item, SAMPLE)
    workspace_id = str(UUID(workspace_id))
    _, item_type, name = ITEMS[item]
    # Keep both items discoverable so fabric-cicd resolves the report's model link.
    append_feature_flag("disable_workspace_folder_publish")
    workspace = FabricWorkspace(
        workspace_id=workspace_id,
        repository_directory=str(SAMPLE),
        item_type_in_scope=[item_type],
        token_credential=AzureCliCredential(),
    )
    publish_all_items(workspace, item_name_exclude_regex=rf"^(?!{re.escape(name)}$).*")
    print(f"Published {name} ({item_type}) to workspace {workspace_id}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("item", choices=ITEMS)
    parser.add_argument("--validate-only", action="store_true")
    arguments = parser.parse_args()
    try:
        if arguments.validate_only:
            validate_item(arguments.item)
        else:
            workspace_id = os.environ.get("PBI_WORKSPACE_ID")
            require(workspace_id, "Set PBI_WORKSPACE_ID to the target workspace GUID")
            publish(arguments.item, workspace_id)
    except (ValueError, KeyError, OSError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
