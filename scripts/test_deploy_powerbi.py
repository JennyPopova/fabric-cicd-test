import base64
import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

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

    def test_refresh_runs_after_model_is_published(self):
        with patch.object(deploy_powerbi, "refresh_model") as refresh:
            refresh.side_effect = lambda *args: self.assertEqual(len(self.writes), 1)
            with contextlib.redirect_stdout(io.StringIO()):
                deploy_powerbi.publish("semantic-model", WORKSPACE_ID, refresh=True)
        refresh.assert_called_once()
        self.assertEqual(refresh.call_args.args[:2], (WORKSPACE_ID, "Sales"))

    def test_definition_only_publish_does_not_refresh(self):
        with patch.object(deploy_powerbi, "refresh_model") as refresh:
            self.publish("semantic-model")
        refresh.assert_not_called()

    def test_report_refresh_is_rejected_before_publishing(self):
        with self.assertRaisesRegex(ValueError, "only supported for semantic-model"):
            deploy_powerbi.publish("sales-report", WORKSPACE_ID, refresh=True)
        self.invoke.assert_not_called()

    def test_failed_publish_does_not_refresh(self):
        self.invoke.side_effect = RuntimeError("Publishing failed")
        with patch.object(deploy_powerbi, "refresh_model") as refresh:
            with self.assertRaises(RuntimeError), contextlib.redirect_stdout(io.StringIO()):
                deploy_powerbi.publish("semantic-model", WORKSPACE_ID, refresh=True)
        refresh.assert_not_called()

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


class PowerBIRefreshTests(unittest.TestCase):
    def setUp(self):
        self.credential = MagicMock()
        self.request_id = "44444444-4444-4444-8444-444444444444"
        self.base = f"{deploy_powerbi.POWERBI_API}/groups/{WORKSPACE_ID}/datasets"
        self.refresh_url = f"{self.base}/{MODEL_ID}/refreshes"
        self.real_request = deploy_powerbi.powerbi_request
        patcher = patch.object(deploy_powerbi, "powerbi_request")
        self.request = patcher.start()
        self.addCleanup(patcher.stop)
        sleep = patch.object(deploy_powerbi.time, "sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)

    def responses(self, *histories):
        self.request.side_effect = [
            ({"value": [{"id": MODEL_ID, "name": "Sales"}]}, {}),
            ({}, {"x-ms-request-id": self.request_id}),
            *[({"value": history}, {}) for history in histories],
        ]

    def entry(self, status, request_id=None, **details):
        return {"requestId": request_id or self.request_id, "status": status, **details}

    def refresh(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            deploy_powerbi.refresh_model(WORKSPACE_ID, "Sales", self.credential, **kwargs)

    def test_waits_for_own_refresh_not_previous_success(self):
        self.responses(
            [self.entry("Completed", request_id="other-request")],
            [self.entry("Unknown")],
            [self.entry("Completed")],
        )
        self.refresh()
        self.assertEqual(self.sleep.call_count, 2)
        self.assertEqual(self.request.call_args_list[0].args, (self.credential, "GET", self.base))
        self.assertEqual(
            self.request.call_args_list[1].args,
            (self.credential, "POST", self.refresh_url, {"notifyOption": "NoNotification"}),
        )
        self.assertEqual(
            self.request.call_args_list[-1].args,
            (self.credential, "GET", f"{self.refresh_url}?$top=60"),
        )

    def test_refresh_failure_includes_service_details(self):
        self.responses([self.entry("Failed", serviceExceptionJson='{"error":"M failure"}')])
        with self.assertRaisesRegex(RuntimeError, "Failed.*M failure"):
            self.refresh()

    def test_disabled_cancelled_and_unexpected_states_fail(self):
        for status in ("Disabled", "Cancelled", "Unexpected"):
            with self.subTest(status=status):
                self.responses([self.entry(status)])
                with self.assertRaisesRegex(RuntimeError, status):
                    self.refresh()

    def test_timeout_does_not_report_success(self):
        self.responses([self.entry("Unknown")])
        with patch.object(deploy_powerbi.time, "monotonic", side_effect=[0, 0, 899, 900]):
            with self.assertRaisesRegex(TimeoutError, "900 seconds"):
                self.refresh()
        self.sleep.assert_called_once_with(1)

    def test_missing_and_duplicate_model_fail_before_refresh(self):
        for models in ([], [{"id": MODEL_ID, "name": "Unrelated"}], [
            {"id": MODEL_ID, "name": "Sales"},
            {"id": REPORT_ID, "name": "Sales"},
        ]):
            with self.subTest(models=models):
                self.request.reset_mock()
                self.request.side_effect = [({"value": models}, {})]
                with self.assertRaisesRegex(ValueError, "exactly one"):
                    self.refresh()
                self.request.assert_called_once()

    def test_missing_request_id_fails_without_polling_other_refreshes(self):
        self.request.side_effect = [
            ({"value": [{"id": MODEL_ID, "name": "Sales"}]}, {}),
            ({}, {}),
        ]
        with self.assertRaisesRegex(ValueError, "no request ID"):
            self.refresh()
        self.assertEqual(self.request.call_count, 2)

    def test_api_failure_is_not_swallowed(self):
        self.request.side_effect = HTTPError(self.base, 403, "Forbidden", {}, None)
        with self.assertRaises(HTTPError):
            self.refresh()

    def test_request_uses_powerbi_token_and_json(self):
        self.credential.get_token.return_value = AccessToken("offline-test-token", 4102444800)
        response = MagicMock()
        response.read.return_value = b'{"value":[]}'
        response.headers = {"x-ms-request-id": self.request_id}
        with patch.object(deploy_powerbi, "urlopen") as open_url:
            open_url.return_value.__enter__.return_value = response
            body, headers = self.real_request(
                self.credential, "POST", self.refresh_url, {"notifyOption": "NoNotification"},
            )
        self.credential.get_token.assert_called_once_with(deploy_powerbi.POWERBI_SCOPE)
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, self.refresh_url)
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer offline-test-token")
        self.assertEqual(json.loads(request.data), {"notifyOption": "NoNotification"})
        self.assertEqual(open_url.call_args.kwargs, {"timeout": 30})
        self.assertEqual(body, {"value": []})
        self.assertEqual(headers["x-ms-request-id"], self.request_id)


if __name__ == "__main__":
    unittest.main()
