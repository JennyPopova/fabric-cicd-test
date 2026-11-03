"""Check this sample's project structure; optionally validate Microsoft JSON schemas."""

import argparse
from functools import lru_cache
import json
from pathlib import Path
import re
import sys
from urllib.request import urlopen


EXPECTED_VISUALS = {
    "yearSlicer", "categorySlicer", "totalSalesCard", "grossProfitCard",
    "grossMarginCard", "unitsSoldCard", "monthlySales", "categorySales",
    "productPerformance",
}
EXPECTED_MEASURES = {
    "Total Sales", "Total Cost", "Gross Profit", "Gross Margin %",
    "Units Sold", "Order Count",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    require(path.is_file(), f"Missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def resolve_relative(parent, value):
    relative = Path(value)
    require(not relative.is_absolute(), f"Expected relative path: {value}")
    resolved = (parent / relative).resolve()
    require(resolved.exists(), f"Broken reference: {parent} -> {value}")
    return resolved


def declarations(path):
    require(path.is_file(), f"Missing TMDL: {path}")
    result = {"Column": set(), "Measure": set()}
    for kind, quoted, plain in re.findall(
        r"^\t(column|measure) (?:'((?:[^']|'')+)'|([^=\r\n]+?))(?: =.*)?$",
        path.read_text(encoding="utf-8"), re.MULTILINE,
    ):
        result[kind.title()].add((quoted or plain).strip().replace("''", "'"))
    return result


def check_fields(value, tables):
    if isinstance(value, dict):
        for kind in ("Column", "Measure"):
            if kind in value:
                field = value[kind]
                table = field["Expression"]["SourceRef"]["Entity"]
                name = field["Property"]
                require(table in tables, f"Unknown table: {table}")
                require(name in tables[table][kind], f"Unknown {kind}: {table}.{name}")
        for nested in value.values():
            check_fields(nested, tables)
    elif isinstance(value, list):
        for nested in value:
            check_fields(nested, tables)


def check_schemas(documents):
    try:
        from jsonschema import Draft7Validator
        from referencing import Registry, Resource
        from referencing.jsonschema import DRAFT7
    except ImportError as error:
        raise ValueError("Install scripts/requirements-validation.txt to use --schemas") from error

    @lru_cache(maxsize=None)
    def retrieve(uri):
        require(
            uri.startswith("https://developer.microsoft.com/json-schemas/fabric/"),
            f"Unexpected schema host: {uri}",
        )
        with urlopen(uri, timeout=30) as response:
            return Resource.from_contents(json.load(response), default_specification=DRAFT7)

    registry = Registry(retrieve=retrieve)
    count = 0
    for path, data in documents.items():
        if "$schema" in data:
            validator = Draft7Validator(retrieve(data["$schema"]).contents, registry=registry)
            errors = list(validator.iter_errors(data))
            require(not errors, f"Schema failure in {path}: {errors[0].message if errors else ''}")
            count += 1
    print(f"PASS: {count} files validated against Microsoft JSON schemas (including references)")


def validate(project_path, schemas=False):
    project_path = project_path.resolve()
    project = read_json(project_path)
    require(project["version"] == "1.0", "Unexpected PBIP version")
    require(len(project["artifacts"]) == 1, "Expected one connected report")
    report = resolve_relative(project_path.parent, project["artifacts"][0]["report"]["path"])
    require(report.name == "Sales.Report", "Unexpected report folder")
    report_manifest = report / "definition.pbir"
    connection = read_json(report_manifest)
    model = resolve_relative(report, connection["datasetReference"]["byPath"]["path"])
    require(model == project_path.parent / "Sales.SemanticModel", "Unexpected semantic model path")
    model_manifest = model / "definition.pbism"
    documents = {report_manifest: connection, model_manifest: read_json(model_manifest)}

    for name in ("database", "model", "relationships"):
        path = model / "definition" / f"{name}.tmdl"
        require(path.is_file() and path.stat().st_size > 0, f"Missing or empty TMDL: {path}")
    table_dir = model / "definition" / "tables"
    require({path.stem for path in table_dir.glob("*.tmdl")} == {"Date", "Product", "Sales"},
            "Expected Date, Product, and Sales tables")
    tables = {name: declarations(table_dir / f"{name}.tmdl") for name in ("Date", "Product", "Sales")}
    require(tables["Sales"]["Measure"] == EXPECTED_MEASURES, "Unexpected sample measure inventory")

    definition = report / "definition"
    for path in definition.rglob("*.json"):
        documents[path] = read_json(path)
    for name in ("version.json", "report.json", "pages/pages.json"):
        require(definition / name in documents, f"Missing report definition: {name}")
    pages_path = definition / "pages"
    pages = documents[pages_path / "pages.json"]
    require(pages["pageOrder"] == ["salesOverview"], "Unexpected sample page order")
    require(pages["activePageName"] in pages["pageOrder"], "Active page is missing")
    require({path.name for path in pages_path.iterdir() if path.is_dir()} == set(pages["pageOrder"]),
            "Page directories do not match pageOrder")

    visual_count = 0
    for page_name in pages["pageOrder"]:
        page_dir = pages_path / page_name
        page = read_json(page_dir / "page.json")
        require(page["name"] == page_name, "Page name does not match folder")
        visual_dirs = {path.name: path for path in (page_dir / "visuals").iterdir() if path.is_dir()}
        require(set(visual_dirs) == EXPECTED_VISUALS, "Unexpected or missing sample visual folders")
        positions = []
        for visual_name, visual_dir in visual_dirs.items():
            visual = read_json(visual_dir / "visual.json")
            require(visual["name"] == visual_name, f"Visual name mismatch: {visual_name}")
            require(bool(visual["visual"]["query"]["queryState"]), f"Missing query: {visual_name}")
            check_fields(visual, tables)
            position = visual["position"]
            left, top = position["x"], position["y"]
            right, bottom = left + position["width"], top + position["height"]
            require(0 <= left < right <= page["width"] and 0 <= top < bottom <= page["height"],
                    f"Visual outside page bounds: {visual_name}")
            for other_name, other_left, other_top, other_right, other_bottom in positions:
                require(not (left < other_right and right > other_left and top < other_bottom and bottom > other_top),
                        f"Overlapping visuals: {visual_name}, {other_name}")
            positions.append((visual_name, left, top, right, bottom))
            visual_count += 1
    print(f"PASS: connected PBIP, 3 table declarations, 6 measures, 1 page, {visual_count} visual bindings and bounds")
    if schemas:
        check_schemas(documents)
    else:
        print("SKIP: JSON Schema validation (use --schemas to enable)")
    print("Not checked: M execution, DAX results, relationship semantics, visual rendering; validate in Desktop.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path,
                        default=Path(__file__).resolve().parents[1] / "sample" / "Sales.pbip")
    parser.add_argument("--schemas", action="store_true", help="Fetch and validate Microsoft JSON schemas")
    arguments = parser.parse_args()
    try:
        validate(arguments.project, arguments.schemas)
    except Exception as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())