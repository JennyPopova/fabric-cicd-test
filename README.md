# Power BI CI/CD Development Sample

A text-based Power BI project for testing model and report changes in source control. The report connects to its sibling semantic model through a relative path, not a workspace ID. No database, credentials, gateway, custom visuals, or external data downloads are needed to refresh.

## Open in Power BI Desktop

1. Clone the repository onto Windows with a current Power BI Desktop release. Use the regular Desktop application, not Desktop for Report Server. Keep both artifact folders together.
2. If your release requires them, enable **Power BI Project (.pbip) save option**, **Store semantic model using TMDL format**, and **Store reports using enhanced metadata format (PBIR)** under File > Options and settings > Options > Preview features. Restart Desktop after changing preview options. Feature names and availability vary by release.
3. Open [sample/Sales.pbip](sample/Sales.pbip). The model is import mode; no cached data is committed. Select **Home > Refresh** to materialize the embedded data before checking report results.
4. Open **Sales Overview** and compare the cards and table totals with the acceptance values below. The Year and Category slicers start unfiltered. Charts and the product table use explicit model measures.
5. In Model view, confirm that Date and Product each filter Sales through an active, single-direction, one-to-many relationship. Date is marked as a date table using its unique Date column. MonthName sorts by MonthNumber; YearMonth sorts by YearMonthSort.
6. Save, close, and reopen the project. Verify that the report remains connected and its visuals still work. Generated `.pbi` caches and local settings are intentionally ignored by Git.

Power BI Desktop is not available in the Linux dev container. JSON validation does not establish that Desktop can load, refresh, or render the project; the steps above are required runtime acceptance checks.

## Project Layout

```text
sample/
	Sales.pbip
	Sales.SemanticModel/
		definition.pbism
		definition/
			database.tmdl
			model.tmdl
			relationships.tmdl
			tables/
				Date.tmdl
				Product.tmdl
				Sales.tmdl
	Sales.Report/
		definition.pbir
		definition/
			version.json
			report.json
			pages/
				pages.json
				salesOverview/
					page.json
					visuals/<visual-name>/visual.json
scripts/
	validate_powerbi.py
	test_validate_powerbi.py
	requirements-validation.txt
```

The PBIP entry point references `Sales.Report`; its `definition.pbir` references `../Sales.SemanticModel`. All report visuals bind to the model's Date, Product, or Sales fields. The page contains four KPI cards, a monthly line chart, category bar chart, product table, and two dropdown slicers.

## Sample Model

The import partitions contain deterministic Power Query M expressions, with no machine-specific paths. Each sale represents one complete order, so Order Count is the distinct count of SaleID.

| Table | Contents |
| --- | --- |
| Date | 731 daily rows, January 1, 2024 through December 31, 2025; year, month, and sortable year-month attributes |
| Product | Six products in Office, Electronics, and Lifestyle |
| Sales | 216 orders, nine per month for 24 months; quantity, unit price/cost, revenue, and cost |

| ProductKey | Product | Category | Unit Price (USD) | Unit Cost (USD) |
| --- | --- | --- | ---: | ---: |
| 1 | Notebook | Office | 25 | 10 |
| 2 | Planner | Office | 40 | 18 |
| 3 | Keyboard | Electronics | 75 | 35 |
| 4 | Headset | Electronics | 120 | 60 |
| 5 | Bottle | Lifestyle | 15 | 6 |
| 6 | Tote | Lifestyle | 30 | 12 |

For zero-based sale index `i` from 0 to 215: SaleID is `i + 1`, ProductKey is `(i mod 6) + 1`, Quantity is `(i mod 5) + 1`, and month index is `floor(i / 9)`. The date has year `2024 + floor(month index / 12)`, month `(month index mod 12) + 1`, and day `1 + (i mod 9) * 3`. Revenue and Cost multiply quantity by the product's price and cost. No random seed or current-date dependency is involved.

Measures: **Total Sales**, **Total Cost**, **Gross Profit**, **Gross Margin %**, **Units Sold**, and **Order Count**. Gross Margin % divides total profit by total sales, rather than averaging row-level margins. Technical keys and raw numeric columns are hidden to encourage explicit measure use. Auto date/time is disabled.

## Desktop Acceptance Values

These values were calculated independently from the generation rules, not by executing the model. Compare them with Desktop after refresh. Currency is USD; margins are displayed to one decimal place.

| Year Slicer | Category Slicer | Total Sales | Total Cost | Gross Profit | Gross Margin | Units Sold | Order Count |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| All | All | $32,940.00 | $15,238.00 | $17,702.00 | 53.7% | 646 | 216 |
| 2024 | All | $16,635.00 | $7,707.00 | $8,928.00 | 53.7% | 321 | 108 |
| 2025 | All | $16,305.00 | $7,531.00 | $8,774.00 | 53.8% | 325 | 108 |
| All | Electronics | $21,180.00 | $10,320.00 | $10,860.00 | 51.3% | 217 | 72 |
| 2025 | Electronics | $10,305.00 | $5,025.00 | $5,280.00 | 51.2% | 105 | 36 |

Selecting a year should reduce the monthly chart to 12 months. Selecting Electronics should leave Keyboard and Headset in the product table. Applying both slicers should give the last row above across cards, charts, and table totals. Clear both slicers and verify the unfiltered values return. Chart selections may cross-highlight other visuals according to Power BI's built-in defaults.

## Repository Validation

Run the dependency-free structural check using Python 3.10 or later:

```sh
python3 scripts/validate_powerbi.py
```

For Microsoft JSON Schema checks, install the optional validation dependencies and allow HTTPS access to `developer.microsoft.com`:

```sh
python3 -m pip install -r scripts/requirements-validation.txt
python3 scripts/validate_powerbi.py --schemas
```

On Windows, use `py` in place of `python3` if needed. No Python packages are needed to open or refresh the Power BI project itself.

The validator checks project/model paths, required TMDL files, a narrow inventory of column/measure declarations, page/visual metadata, report field references, and non-overlapping canvas bounds. `--schemas` additionally validates all schema-bearing JSON files, including referenced schemas. Missing files, invalid references, schema failures, and unreachable schemas fail with a nonzero exit code. The PBIP entry point has structural checks only; it has no declared JSON schema.

This script is deliberately specific to the sample, not a general TMDL parser or DAX/M engine. If you intentionally add pages, visuals, or measures, update its expected inventories. Runtime model correctness and report rendering require the Desktop acceptance checks.

Run the validator regression tests without extra dependencies:

```sh
python3 -m unittest discover -s scripts -p 'test_*.py' -v
```

The tests modify temporary copies, covering the valid project, broken model links, missing model/page/visual metadata, missing visual folders, unknown measures, and overlapping visuals. They do not modify the source artifacts.

During authoring, Microsoft Analysis Services `19.118.3` successfully deserialized the TMDL and resolved the tables, measures, M import partitions, date key, and active single-direction relationships. This parser check does not execute M or DAX and does not replace Desktop acceptance.

## CI/CD Scope

This stage supplies development artifacts and local checks only. It does not configure GitHub Actions, create workspaces, publish to the service, or deploy between environments. No secrets or workspace identifiers are stored in the sample.

A later deployment stage will need a supported publishing method, development/test/production workspace IDs, appropriate licensing/capacity, deployment identity permissions and tenant settings, and environment-specific handling of report-to-model bindings. Keep the report and semantic model together when promoting them. Do not copy Desktop caches into deployment packages.

For a first source-control exercise, change a measure or chart title in Desktop, save, and inspect the TMDL/PBIR diff. Run validation and the relevant acceptance checks before committing. A deliberate measure change may also require updating the expected totals.