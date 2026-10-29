# Flux Analyzer

Flux Analyzer is a file-based financial variance analysis app. The running app is
the Flask application under `artifacts/flux-analyzer/flux_analyzer/`; it serves
its own HTML, CSS, and JavaScript.

## Where things live

- `artifacts/flux-analyzer/flux_analyzer/app.py` — Flask application entry point.
- `artifacts/flux-analyzer/flux_analyzer/web/` — routes, page templates, and browser assets.
- `artifacts/flux-analyzer/flux_analyzer/engine/` — analysis, evidence checks, and Excel exports.
- `artifacts/flux-analyzer/flux_analyzer/agent/` — AI Engine client, response contracts, and mock mode.
- `artifacts/flux-analyzer/flux_analyzer/presets/` and `examples/` — sample analysis presets and specifications.
- `artifacts/flux-analyzer/flux_analyzer/tests/` — automated tests.
- `artifacts/flux-analyzer/flux_analyzer/workspace/` — local uploads and generated app data; excluded from Git.

The `artifacts/flux-analyzer/src/` folder is a separate React/Vite scaffold. The
current Flask workflow does not use it to serve the app.

## Run locally

Use Python 3.13, then run:

```sh
cd artifacts/flux-analyzer/flux_analyzer
python -m pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000`. The app starts in mock AI mode by default, so it
can run without AI credentials.

