import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from validate_powerbi import validate


class PowerBIValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        source = Path(__file__).resolve().parents[1] / "sample"
        self.sample = Path(self.temporary.name) / "sample"
        shutil.copytree(source, self.sample, ignore=shutil.ignore_patterns(".pbi"))
        self.project = self.sample / "Sales.pbip"
        self.report = self.sample / "Sales-report.Report"
        self.page = self.report / "definition/pages/5fbe7a4cdeb5ad8c41a7"
        self.sales_card = self.page / "visuals/2777c7b959007050e623"
        self.profit_card = self.page / "visuals/365aca82563077dcde61"

    def run_validation(self):
        with contextlib.redirect_stdout(io.StringIO()):
            validate(self.project)

    def update_json(self, path, change):
        document = json.loads(path.read_text(encoding="utf-8"))
        change(document)
        path.write_text(json.dumps(document), encoding="utf-8")

    def test_valid_sample(self):
        self.run_validation()

    def test_broken_model_path(self):
        self.update_json(
            self.report / "definition.pbir",
            lambda document: document["datasetReference"]["byPath"].update(path="../Missing.SemanticModel"),
        )
        with self.assertRaisesRegex(ValueError, "Broken reference"):
            self.run_validation()

    def test_missing_model_manifest(self):
        (self.sample / "Sales.SemanticModel/definition.pbism").unlink()
        with self.assertRaisesRegex(ValueError, "Missing file"):
            self.run_validation()

    def test_missing_page_metadata(self):
        (self.page / "page.json").unlink()
        with self.assertRaisesRegex(ValueError, "Missing file"):
            self.run_validation()

    def test_missing_visual_metadata(self):
        (self.sales_card / "visual.json").unlink()
        with self.assertRaisesRegex(ValueError, "Missing file"):
            self.run_validation()

    def test_missing_visual_folder(self):
        shutil.rmtree(self.sales_card)
        with self.assertRaisesRegex(ValueError, "missing sample visual folders"):
            self.run_validation()

    def test_unknown_measure(self):
        def change(document):
            projection = document["visual"]["query"]["queryState"]["Data"]["projections"][0]
            projection["field"]["Measure"]["Property"] = "Missing Measure"

        self.update_json(self.sales_card / "visual.json", change)
        with self.assertRaisesRegex(ValueError, "Unknown Measure"):
            self.run_validation()

    def test_overlapping_visuals(self):
        self.update_json(
            self.profit_card / "visual.json",
            lambda document: document["position"].update(x=40),
        )
        with self.assertRaisesRegex(ValueError, "Overlapping visuals"):
            self.run_validation()

    def test_missing_data_visual_query_is_rejected(self):
        self.update_json(
            self.sales_card / "visual.json",
            lambda document: document["visual"]["query"].update(queryState={}),
        )
        with self.assertRaisesRegex(ValueError, "Missing query"):
            self.run_validation()

    def test_decorative_visual_outside_canvas_is_rejected(self):
        self.update_json(
            self.page / "visuals/98673ee350be45840d89/visual.json",
            lambda document: document["position"].update(x=-1),
        )
        with self.assertRaisesRegex(ValueError, "Visual outside page bounds"):
            self.run_validation()


if __name__ == "__main__":
    unittest.main()