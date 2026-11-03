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
        self.report = self.sample / "Sales.Report"
        self.page = self.report / "definition/pages/salesOverview"

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
        (self.page / "visuals/totalSalesCard/visual.json").unlink()
        with self.assertRaisesRegex(ValueError, "Missing file"):
            self.run_validation()

    def test_missing_visual_folder(self):
        shutil.rmtree(self.page / "visuals/totalSalesCard")
        with self.assertRaisesRegex(ValueError, "missing sample visual folders"):
            self.run_validation()

    def test_unknown_measure(self):
        def change(document):
            projection = document["visual"]["query"]["queryState"]["Values"]["projections"][0]
            projection["field"]["Measure"]["Property"] = "Missing Measure"

        self.update_json(self.page / "visuals/totalSalesCard/visual.json", change)
        with self.assertRaisesRegex(ValueError, "Unknown Measure"):
            self.run_validation()

    def test_overlapping_visuals(self):
        self.update_json(
            self.page / "visuals/grossProfitCard/visual.json",
            lambda document: document["position"].update(x=24),
        )
        with self.assertRaisesRegex(ValueError, "Overlapping visuals"):
            self.run_validation()


if __name__ == "__main__":
    unittest.main()