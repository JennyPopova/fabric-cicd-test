import base64
import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from azure.core.credentials import AccessToken
from fabric_cicd import constants
from fabric_cicd._common._exceptions import PublishError

import deploy_powerbi


WORKSPACE_ID = "11111111-1111-4111-8111-111111111111"
MODEL_ID = "22222222-2222-4222-8222-222222222222"
REPORT_ID = "33333333-3333-4333-8333-333333333333"


class PowerBIDeploymentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.sample = Path(temporary.name) / "sample"
        shutil.copytree(deploy_powerbi.SAMPLE, self.sample, ignore=shutil.ignore_patterns(".pbi"))
        self.start_patch(patch.object(deploy_powerbi, "SAMPLE", self.sample))
        self.start_patch(patch.object(constants, "FEATURE_FLAG", set()))
        self.start_patch(patch(
            "azure.identity.AzureCliCredential.get_token",
            return_value=AccessToken("offline-test-token", 4102444800),
        ))
        self.invoke = self.start_patch(patch(
            "fabric_cicd._common._fabric_endpoint.FabricEndpoint.invoke",
            side_effect=self.respond,
        ))
        self.deployed = []
        self.writes = []

    def start_patch(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def workspace_item(self, item_type, name, item_id):
        return {"type": item_type, "displayName": name, "id": item_id, "description": ""}

    def respond(self, method, url, body=None, **kwargs):
        base = f"{constants.DEFAULT_API_ROOT_URL}/v1/workspaces/{WORKSPACE_ID}"
        if method == "GET" and url == base:
            return {"body": {"displayName": "Test workspace"}}
        if method == "GET" and url == f"{base}/items":
            return {"body": {"value": self.deployed}}
        if method == "POST" and (url == f"{base}/items" or "/updateDefinition?" in url):
            self.writes.append((url, body))
            return {"body": {"id": REPORT_ID if body.get("type") == "Report" else MODEL_ID}}
        raise AssertionError(f"Unexpected API call: {method} {url}")

    def publish(self, item):
        with contextlib.redirect_stdout(io.StringIO()):
            deploy_powerbi.publish(item, WORKSPACE_ID)

    def definition_parts(self):
        self.assertEqual(len(self.writes), 1)
        return {
            part["path"]: base64.b64decode(part["payload"])
            for part in self.writes[0][1]["definition"]["parts"]
        }

    def test_create_model_only(self):
        self.publish("semantic-model")
        self.assertEqual(self.writes[0][1]["type"], "SemanticModel")
        self.assertEqual(self.writes[0][1]["displayName"], "Sales")
        parts = self.definition_parts()
        self.assertIn("definition.pbism", parts)
        self.assertNotIn("definition.pbir", parts)

    def test_update_model_only(self):
        self.deployed = [
            self.workspace_item("SemanticModel", "Sales", MODEL_ID),
            self.workspace_item("Report", "Sales-report", REPORT_ID),
        ]
        self.publish("semantic-model")
        self.definition_parts()
        self.assertIn(f"/{MODEL_ID}/updateDefinition?", self.writes[0][0])

    def test_create_report_bound_to_existing_model_only(self):
        self.deployed = [self.workspace_item("SemanticModel", "Sales", MODEL_ID)]
        original = (self.sample / "Sales-report.Report/definition.pbir").read_bytes()
        self.publish("sales-report")
        self.assertEqual(self.writes[0][1]["type"], "Report")
        self.assertEqual(self.writes[0][1]["displayName"], "Sales-report")
        parts = self.definition_parts()
        connection = json.loads(parts["definition.pbir"])["datasetReference"]
        self.assertEqual(connection["byConnection"]["pbiModelDatabaseName"], MODEL_ID)
        self.assertNotIn("byPath", connection)
        self.assertNotIn("definition.pbism", parts)
        self.assertEqual((self.sample / "Sales-report.Report/definition.pbir").read_bytes(), original)

    def test_update_report_only(self):
        self.deployed = [
            self.workspace_item("SemanticModel", "Sales", MODEL_ID),
            self.workspace_item("Report", "Sales-report", REPORT_ID),
        ]
        self.publish("sales-report")
        self.definition_parts()
        self.assertIn(f"/{REPORT_ID}/updateDefinition?", self.writes[0][0])

    def test_report_without_deployed_model_fails_before_writing(self):
        with self.assertRaises(PublishError):
            self.publish("sales-report")
        self.assertEqual(self.writes, [])

    def test_other_reports_and_desktop_caches_are_not_published(self):
        self.deployed = [self.workspace_item("SemanticModel", "Sales", MODEL_ID)]
        other = self.sample / "Unrelated.Report"
        shutil.copytree(self.sample / "Sales-report.Report", other)
        platform = json.loads((other / ".platform").read_text())
        platform["metadata"]["displayName"] = "Unrelated"
        platform["config"]["logicalId"] = "44444444-4444-4444-8444-444444444444"
        (other / ".platform").write_text(json.dumps(platform))
        cache = self.sample / "Sales-report.Report/.pbi"
        cache.mkdir()
        (cache / "cache.bin").write_bytes(b"desktop cache")
        self.publish("sales-report")
        parts = self.definition_parts()
        self.assertFalse(any(".pbi/" in path for path in parts))
        self.assertEqual(self.writes[0][1]["displayName"], "Sales-report")

    def test_wrong_report_model_path_is_rejected(self):
        manifest = self.sample / "Sales-report.Report/definition.pbir"
        document = json.loads(manifest.read_text())
        document["datasetReference"]["byPath"]["path"] = "../Missing.SemanticModel"
        manifest.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "must reference"):
            self.publish("sales-report")
        self.invoke.assert_not_called()

    def test_wrong_item_metadata_is_rejected(self):
        metadata = self.sample / "Sales.SemanticModel/.platform"
        document = json.loads(metadata.read_text())
        document["metadata"]["displayName"] = "Unexpected"
        metadata.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "Expected display name Sales"):
            self.publish("semantic-model")
        self.invoke.assert_not_called()

    def test_invalid_workspace_id_is_rejected_before_authentication(self):
        with self.assertRaises(ValueError), contextlib.redirect_stdout(io.StringIO()):
            deploy_powerbi.publish("semantic-model", "not-a-workspace-guid")
        self.invoke.assert_not_called()


if __name__ == "__main__":
    unittest.main()
