# AI, data handling and local operation

## Responsibility boundary
Python reads files, scopes data, calculates values, joins, classifies reviewed rules, aggregates measures, selects drivers, builds evidence and reconciles outputs. AI proposes declarative settings or wording only. No agent response is evaluated as Python.

Every request is stateless: request ID, step, current spec, user message and step payload. The selected preset guidance and relevant defaults accompany each request. Column sample lists are capped at 10; encoded requests are capped at 50 KiB. Raw transaction rows are not sent.

Metadata is still sensitive: column names, description terms, aggregate values and spec rules may reveal business information. Obtain approval before enabling live mode. Requests rejected by the size cap require less metadata or a simpler spec; the app does not secretly upload whole files elsewhere.

## Apply and repair policy
Responses use `ok`, `needs_input` or `cannot_do`, with `high`, `medium` or `low` confidence. Valid applicable settings auto-apply at any confidence. Partial settings can apply under needs_input; the assistant also displays questions. Cannot_do and invalid responses leave settings unchanged.

Schema and patch errors trigger one stateless repair with all reported validation errors, the expected schema and selected preset context. Mechanical narrative checks allow one content repair as well. There is no endless retry loop. Requests taking a corporate asynchronous path are polled with a timeout; transient network errors have bounded retries.

## Run locally
From `artifacts/flux-analyzer/flux_analyzer`:
```sh
python -m pip install -r requirements.txt
cp .env.example .env
python app.py
```
Open `http://127.0.0.1:5000`. Use Python 3.10 or later. Local mode needs no database. The ignored local workspace stores uploads, project state, presets, runs and audit files.

Set `AGENT_MODE=mock` for offline operation or `AGENT_MODE=live` for the corporate API. Legacy `AGENT_MOCK=true/false` remains supported when AGENT_MODE is unset. Set live credentials only in the private local `.env` or environment:
```text
AGENT_MODE=live
EAP_BASE_URL=https://your-approved-api-host
EAP_AGENT_ID=your-agent-identifier
EAP_API_KEY=your-private-api-key
EAP_PAT=your-private-personal-access-token
```
Do not paste real values into chat, source, presets, screenshots or documentation. The exact endpoint must be approved/reachable from the machine running Flask. Supplying an unrelated model-provider key alone does not configure the Equinix invoke/poll API.

## Storage and operations
Use one Python process with threads: background jobs are in-process and do not survive restart. Completed files do persist. Back up the ignored workspace separately if needed; Git does not back up financial data.

The app is for a trusted local operator. CSRF protection and local session isolation are not corporate authentication. Do not expose real finance data publicly without approved authentication, durable storage, access controls, retention and security review. Corporate API connectivity and credentials have not been verified in this environment.
