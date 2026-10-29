# Step 1 — Sources and presets

Upload CSV or XLSX files. Each file remains local under the workspace directory. Executable files, macro workbooks and unsupported file types are rejected. The upload request limit is 600 MiB; practical limits depend on available memory.

## Define the correct rectangle
- Select the workbook sheet.
- Set the **1-based** header row and Excel-style start/end column letters.
- Check the parsed preview, not just the raw worksheet preview.
- Optionally combine selected sheets and add a sheet-tag column.
- Confirm the definition before continuing. Reopening a file does not silently change its definition.

## Source roles
- **Primary:** stacked into the fact table; multiple files may contain different months.
- **Lookup:** named enrichment tables, joined explicitly. Files sharing the same lookup name are stacked.
- **Forecast:** stacked facts with a scenario indicator for Actual versus Forecast comparisons.

Repeated periods across separate fact files trigger a stop because overlap may double-count transactions. A lookup can be optional when its join explicitly sets `optional: true`; its absence then produces an audit warning, not fabricated matches.

## Presets
Generic is the neutral starting point. Repairs and Maintenance, Benefits, and Opex are declarative examples, not special engine branches. Inspect **How this flux works**, guidance, source expectations and rules before applying one. Header names in a preset may need mapping to your files.

Give the analysis a clear name. Duplicate or save a preset with a stable ID, owner, description and guidance. Export/import is a single portable JSON file. No credentials or financial source files belong in a preset.

## AI and overrides
Detect uses header names and your context to propose a preset and analysis name. Choose a different preset tile or edit its defaults manually if the suggestion is wrong. In live mode, an example instruction is `Use the generic preset for monthly operating costs`. Offline, choose the tile directly. Source rectangles must still be confirmed by you.
