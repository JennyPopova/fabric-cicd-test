# Power BI CI/CD Development Sample

A text-based Power BI project for testing model and report changes in source control. The report connects to its sibling semantic model through a relative path, not a workspace ID. No database, credentials, gateway, custom visuals, or external data downloads are needed to refresh.

## Open in Power BI Desktop

1. Clone the repository onto Windows with a current Power BI Desktop release. Use the regular Desktop application, not Desktop for Report Server. Keep both artifact folders together.
2. If your release requires them, enable **Power BI Project (.pbip) save option**, **Store semantic model using TMDL format**, and **Store reports using enhanced metadata format (PBIR)** under File > Options and settings > Options > Preview features. Restart Desktop after changing preview options. Feature names and availability vary by release.
3. Open [sample/Sales.pbip](sample/Sales.pbip). The model is import mode; no cached data is committed. Select **Home > Refresh** to materialize the embedded data before checking report results.
4. Open **Sales Performance Overview** and compare the Total Sales and Gross Profit cards with the acceptance values below. Clear the Year and Category slicers before checking unfiltered totals. Charts use explicit model measures.
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
	Sales-report.Report/
		definition.pbir
		definition/
			version.json
			report.json
			pages/
				pages.json
				5fbe7a4cdeb5ad8c41a7/
					page.json
					visuals/<visual-name>/visual.json
scripts/
	validate_powerbi.py
	test_validate_powerbi.py
	requirements-validation.txt
```

The PBIP entry point references `Sales-report.Report`; its `definition.pbir` references `../Sales.SemanticModel`. Data visuals bind to the model's Date, Product, or Sales fields. The exported page contains two KPI cards, a monthly line chart, three column charts, two dropdown slicers, and a decorative header shape and text box.

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

These values were calculated independently from the generation rules, not by executing the model. Compare the displayed measures with Desktop after refresh; measures not shown in this report can be checked in a temporary table visual. Currency is USD.

| Year Slicer | Category Slicer | Total Sales | Total Cost | Gross Profit | Gross Margin | Units Sold | Order Count |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| All | All | $32,940.00 | $15,238.00 | $17,702.00 | 53.7% | 646 | 216 |
| 2024 | All | $16,635.00 | $7,707.00 | $8,928.00 | 53.7% | 321 | 108 |
| 2025 | All | $16,305.00 | $7,531.00 | $8,774.00 | 53.8% | 325 | 108 |
| All | Electronics | $21,180.00 | $10,320.00 | $10,860.00 | 51.3% | 217 | 72 |
| 2025 | Electronics | $10,305.00 | $5,025.00 | $5,280.00 | 51.2% | 105 | 36 |

Selecting a year should reduce the monthly chart to 12 months. Selecting Electronics should leave Keyboard and Headset in the product units chart. Applying both slicers should give the last row above for the displayed measures. Clear both slicers and verify the unfiltered values return. Chart selections may cross-highlight other visuals according to Power BI's built-in defaults.

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

The validator checks project/model paths, required TMDL files, a narrow inventory of column/measure declarations, page/visual metadata, report field references, and canvas bounds. Data visuals must not overlap; decorative header shapes and text may intentionally overlay other visuals. `--schemas` additionally validates all schema-bearing JSON files, including referenced schemas. Missing files, invalid references, schema failures, and unreachable schemas fail with a nonzero exit code. The PBIP entry point has structural checks only; it has no declared JSON schema.

This script is deliberately specific to the sample, not a general TMDL parser or DAX/M engine. If you intentionally add pages, visuals, or measures, update its expected inventories. Runtime model correctness and report rendering require the Desktop acceptance checks.

Run the validator and deployment regression tests (deployment tests require the publishing library):

```sh
python3 -m pip install -r scripts/requirements-deployment.txt
python3 -m unittest discover -s scripts -p 'test_*.py' -v
```

The tests modify temporary copies, covering the valid project, broken model links, missing model/page/visual metadata, missing visual folders, unknown measures, and overlapping visuals. They do not modify the source artifacts.

During authoring, Microsoft Analysis Services `19.118.3` successfully deserialized the TMDL and resolved the tables, measures, M import partitions, date key, and active single-direction relationships. This parser check does not execute M or DAX and does not replace Desktop acceptance.

## CI/CD Scope

Two independent **manual-only GitHub Actions workflows** publish to one Power BI workspace using Microsoft's `fabric-cicd` library:

| Workflow | Source | Published item |
| --- | --- | --- |
| `publish-semantic-model.yml` / **Publish semantic model** | `sample/Sales.SemanticModel` | `Sales` semantic model only |
| `publish-sales-report.yml` / **Publish Sales-report** | `sample/Sales-report.Report` | `Sales-report` report only |

`Sales-report.Report` is the workspace-exported report used by both `Sales.pbip` and the report pipeline. Publishing creates or updates the selected item by its `.platform` display name and type; do not rename the workspace items independently. Other workspace items are not deleted, and workspace folders are not published.

### One-time configuration

1. Choose the Microsoft Entra user account you use for Power BI. Add that user to the target workspace as **Contributor** or a higher role, with the appropriate Power BI licensing and semantic-model permissions. Use a regular workspace, not My workspace, with appropriate licensing/capacity and support for the Fabric item-definition APIs.
2. Ensure your tenant permits Azure CLI user sign-in using the device-code flow and delegated access to the Fabric APIs. Sign-in must satisfy your organization's MFA and Conditional Access policies. If device-code sign-in is blocked, ask your administrator about an approved authentication method; do not bypass those policies.
3. In repository **Settings > Environments**, create `powerbi`. Restrict deployment branches to `main`; optionally require a reviewer. Both workflows use this environment and also skip runs from other branches.
4. In repository **Settings > Secrets and variables > Actions > Variables**, set the repository variables below. Keep `PBI_WORKSPACE_ID` at repository scope so both workflows share the same concurrency group.

| Repository variable | Value |
| --- | --- |
| `AZURE_TENANT_ID` | Microsoft Entra directory (tenant) GUID |
| `PBI_WORKSPACE_ID` | Target Power BI/Fabric workspace GUID from its URL |

No app registration, service principal, client secret, Azure subscription, or GitHub OIDC federation is required. If migrating from the previous service-principal setup, `AZURE_CLIENT_ID` and its federated credential are no longer used by these workflows.

The workflows request only repository read access. `az login --use-device-code` signs in interactively as your Microsoft Entra user; `AzureCliCredential` supplies that user's credentials to `fabric-cicd`. Starting or approving the GitHub workflow does not select the Microsoft identity: deployment uses whichever Power BI account completes the device-code sign-in. Credentials are kept in an isolated Azure CLI directory on the ephemeral runner, not cached or uploaded, and an always-run cleanup step clears the CLI account/token cache. The first step sets `AZURE_CONFIG_DIR` under `$RUNNER_TEMP` through `$GITHUB_ENV` so all subsequent steps use the same isolated directory. There are no passwords or workspace identifiers committed to source control. The pipelines do not provision workspaces or change tenant settings.

### Publishing

After merging these workflows into `main`, open **Actions**, select **Publish semantic model**, then **Run workflow** on `main`. Complete any environment approval, open the running job, and expand **Sign in as a Power BI user (open logs for device code)**. Open the Microsoft sign-in URL shown there, enter the device code, and sign in with your Power BI user. Complete sign-in within the step's 10-minute timeout (or the code's shorter expiry); the workflow then publishes automatically. If sign-in fails or expires, rerun the workflow to obtain a new code. Both workflows require a fresh sign-in for every run, so they are not unattended deployments.

Only enter a device code from a workflow run you intentionally started and trust. Treat an unexpired code as sensitive and do not share it. Anyone who can read the job logs can see the code, especially in public repositories; never approve an unexpected sign-in or a request from an untrusted workflow.

For the first deployment, wait for the semantic-model workflow to finish successfully before manually running **Publish Sales-report** and completing its own device-code sign-in. The model workflow publishes the definition, requests a Power BI refresh using the same signed-in user, and waits for that specific refresh to complete so the import tables contain data.

The report's relative `../Sales.SemanticModel` reference is resolved by `fabric-cicd` to the existing `Sales` model's ID in the target workspace. The report workflow does **not** deploy or refresh the model; it fails if the model has not been published there. Later report-only changes can be published independently. Publish compatible model changes first when changing fields used by the report.

Both workflows run regression tests and structural checks before signing in. The checks do not execute TMDL, M, DAX, or render reports; Desktop acceptance still applies. Schema validation remains available separately with `--schemas`. A shared concurrency group prevents simultaneous writes to the workspace and does not cancel an active deployment. GitHub may replace an older pending run when several runs are queued.

Publishing definitions alone does not refresh imported data; Desktop caches are excluded from publishing. The semantic-model workflow uses `--refresh` to materialize the embedded M data after every deployment. The signed-in user needs permission to refresh the semantic model and delegated Power BI API access (`Dataset.ReadWrite.All`). No external connections or gateway are needed for this sample. A failed refresh or a 15-minute wait timeout fails the workflow, even if the definition was published successfully; inspect the job logs and the model's refresh history in Power BI. A timeout does not cancel a refresh already running in the service. For an already-published empty model, select **Refresh now** on `Sales` in the Power BI service, or rerun the updated model workflow. Compare refreshed report values with the acceptance table above. Scheduled refresh and multi-environment promotion are outside these pipelines.

To publish and refresh from an already authenticated Azure CLI session:

```sh
python3 scripts/deploy_powerbi.py semantic-model --refresh
```

Without `--refresh`, the local publishing command still deploys definitions only. The option is not supported for report publishing.

To check either deployment source locally without Azure credentials or publishing dependencies:

```sh
python3 scripts/deploy_powerbi.py semantic-model --validate-only
python3 scripts/deploy_powerbi.py sales-report --validate-only
```

For a first source-control exercise, change a measure or chart title in Desktop, save, and inspect the TMDL/PBIR diff. Run validation and the relevant acceptance checks before committing. A deliberate measure change may also require updating the expected totals.