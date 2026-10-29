# Presets

Presets are data. Adding a new analysis type does not require a new Python branch. A preset directory contains `preset.json`, `guidance.md` and optionally `categories.json`.

The manifest uses `id`, `name`, semantic `version`, `owner`, `updated_at`, `description`, `detect_hints`, `required_sources`, `optional_sources` and `defaults`. Defaults can contain any supported FluxSpec blocks, but do not include uploaded file bytes or credentials.

Guidance is limited to approximately 800 words. Describe business definitions, expected sign conventions, input meanings, comparison assumptions, classification categories and what requires analyst confirmation. Guidance cannot override deterministic financial calculations or permit code execution.

## Built-in examples
- **Generic:** neutral defaults, no account or financial-domain assumptions.
- **Repairs and Maintenance:** account-prefix scope, accrual buckets, PO extraction, first-month quarter comparisons, optional open-PO/GAO evidence and ordered exception rules.
- **Benefits:** department comparison with headcount/cost-per-head and optional volume/rate decomposition.
- **Opex:** cost-centre/account comparison with zero absolute presentation threshold.

## Manage versions
Apply after inspecting How this flux works. Edit defaults through the normal forms, edit guidance, then save as a new ID or version. Saved versions are immutable files; saving an existing ID increments its patch version. Generic itself is not overwritten; duplicate it.

Export packages manifest, defaults, guidance, categories, version metadata and export timestamp in one JSON file. Import validates the complete candidate before saving. Presets are global to the local workspace, not private to a browser session.

Each AI request includes selected preset ID/version, its guidance and only defaults relevant to that step. Historical run reuse preserves the selected version; an unavailable historic version must be imported or explicitly replaced.
