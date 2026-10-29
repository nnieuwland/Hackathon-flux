# Flux Analyzer

Local financial variance analysis for Equinix finance analysts. Upload CSV/XLSX, confirm a portable FluxSpec, run deterministic Python calculations and export an auditable Excel pack.

## Run & Operate

- Managed workflow: `artifacts/flux-analyzer: web`
- `pnpm --filter @workspace/flux-analyzer run dev` runs Flask, honoring `PORT`.
- `cd artifacts/flux-analyzer/flux_analyzer && python app.py` runs locally on port 5000.
- `cd artifacts/flux-analyzer/flux_analyzer && python -m pytest -q` runs the full offline suite (engine, agent, journey, Excel pack).
- Optional workflow test: `AGENT_MOCK=true python -m pytest artifacts/flux-analyzer/flux_analyzer/tests/test_mock_workflow.py -q`.
- Gunicorn must run **one process** with threads: jobs use an in-process thread pool.
- No database. Do not provision one for this app.

## Stack & source

- `artifacts/flux-analyzer/flux_analyzer/app.py`: Flask factory.
- `engine/`: pure Python ingestion, AST expressions, transforms, measures, controls, evidence, exports and schema.
- `agent/`: Equinix invoke/poll integration, response schemas, local mock templates and metadata payload builders.
- `web/`: focused blueprints, atomic local state, Jinja templates, Alpine, HTMX and vendored JS.
- Simple mode (default, guided `/flow/<stage>` journey) lives in `web/templates/journey/`, `web/static/journey.js` and `journey.css`; it is mixed into the Advanced-mode Alpine component in `app.js`. Advanced mode keeps the original `/step/<step>` screens. Finance wording for Simple mode lives in `web/terms.py`.
- Agent-facing contract and instructions: `docs/agent/` (published in the in-app docs).
- `tests/fixtures/`: synthetic R&M Golden Rule and Benefits worked examples.
- `requirements.txt` uses minimum versions only; Python 3.10+ intended (not runtime-tested on every version).
- Local runtime data is under `workspace/`, ignored by Git and deployment packaging.

## Product rules

- User explicitly requires Flask/Jinja/HTMX/Alpine, not the scaffolded React/Express stack.
- All financial math and preformatted evidence amounts are Python-only. Use Decimal sums, rounded to cents at the output boundary.
- No flux-type-specific calculation branches. New types are data-only presets plus saved JSON FluxSpecs.
- The agent sees only metadata/value counts/small aggregated evidence, never raw records. Enforce a 50KB encoded envelope cap.
- Valid agent configuration proposals auto-apply at all confidence levels, with low-confidence warnings, audited atomic patches and undo/redo. Valid partial proposals may apply under needs_input; cannot_do and invalid proposals never mutate settings.
- Never eval/exec agent code. Expressions use the engine's AST whitelist.
- Only a person can confirm an explanation; AI drafts stay "Explained by AI — please review" until confirmed by a named reviewer.
- Excel is the only report download (plus FluxSpec setup JSON). Word and Markdown are retired (approved); the routes return a 400. The workbook is built by `engine/excel_pack.py` with `excel_style.py`, `excel_summary.py` and `excel_appendix.py`; formula-backed sheets rely on the named ranges BaseMonths, CurrentMonths, Base/CurrentVersion, Threshold, TotalBase and TotalCurrent.
- Every stop control blocks output release; drivers/others, section movements and flag counts reconcile.
- Corporate credentials must stay in environment settings, never templates, logs, source or browser storage.
- Mock mode is the default while live Equinix access is unavailable. It is visibly labeled and generic, not a replacement for corporate skills.

## Operations

- See the application README for local setup and EAP environment variable names.
- Completed outputs and audit data persist locally; pending jobs do not survive a restart.
- The app is a local trusted-operator tool, not an authenticated corporate multi-user service. Do not publish real finance data without corporate auth, approved durable storage and retention/security review.
- Existing API Server and Canvas are starter services and are not used by Flux Analyzer; leave them stopped.
