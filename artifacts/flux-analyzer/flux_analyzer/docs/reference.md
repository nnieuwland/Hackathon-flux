# Flux engine and agent reference — v2

This is the authoritative v2 contract. The older ENGINE_AND_AGENT_GUIDE document describes the original v1 implementation and should be used only as historical context where it conflicts with this reference.

## Architecture and boundaries
Flask/Jinja/Alpine provide the local UI. Python/pandas read CSV/XLSX, apply declarative settings and calculate results. Decimal arithmetic preserves financial values; amounts are rounded to cents at financial output boundaries. No database, external spreadsheet formula execution, arbitrary agent code, or browser-side financial engine is involved.

The pipeline is: validate/migrate spec; stack fact sources; apply ordered derives; calculate/net/flip value; source joins; classification; scope; normalize periods; resolve tokens and comparison; pre-controls; compute views; view-level lookup summaries; flags and gates; materiality/driver selection; drill evidence; sections/decomposition; evidence formatting; post-controls; stamped export.

## FluxSpec root
`spec_version` is `"2.0"`. `preset` is an ID/version object. `flux_name` is 1–120 characters. `sources` holds portable file/sheet/rectangle definitions, not file bytes or absolute storage paths. `run_stamp` is optional export metadata and is excluded when calculating a new spec fingerprint.

The supported blocks are `roles`, `scope`, `derive`, `value_rules`, `periods`, `period_format`, `partial_periods`, `comparison`, `joins`, `classification`, `measures`, `views`, `sections`, `decompose`, `flags`, `gates`, `drivers`, `drill`, `commentary`, and `controls`.

Version 1 inputs migrate: `skill` becomes the preset ID; `drivers.materiality_abs` becomes an absolute materiality object; legacy slice period labels become explicit canonical months; missing new defaults are supplied. Saves use the v2 shape. Validation errors are returned as a list of configuration paths, not silently accepted.

## Roles
Scalar roles are `value`, `period`, `scenario`, `debit`, and `credit` (string or null). Array roles are `keys`, `dimensions`, and `driver_text` (column-name strings). Amount and period are required for ordinary runs; debit/credit are required for netting mode; scenario is required when filtering by scenario.

## Filters and scope
Filter shape:
```json
{"col":"Region","op":"in","val":["EMEA","APAC"]}
```
Supported operators: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `startswith`, `contains`, `regex`, `isnull`, `notnull`. `val` can be a string, number, boolean, null or array, according to the operator. Null operators do not need val. Scope is an array of AND-combined filters; OR logic can be expressed using membership or an ordered derived rule.

String contains/starts-with filters are case-sensitive. Classification has its own case-sensitive setting. Numeric comparisons use numeric conversion. Regex filters are limited to 500 characters. Invalid/missing columns fail explicitly.

## Derived columns
Derives run in listed order and may refer to earlier derived names.
```json
[
  {"name":"Bucket","type":"rules","rules":[
    {"when":{"col":"Event","op":"contains","val":"Reversal"},"then":"Reversal"}
  ],"default":"Other"},
  {"name":"Base_PO","type":"regex_extract","source":["PO","Description"],
   "pattern":"(\\d{6,})","strip_suffix":"_V\\d+","default":"UNMATCHED"},
  {"name":"Team","type":"map","source":"Cost Center",
   "mapping":{"100":"Facilities","200":"IT"},"default":"Other"},
  {"name":"Unit_cost","type":"ratio","numerator":"Amount","denominator":"Units"},
  {"name":"Label","type":"concat","source":["Country","Team"],"separator":" / "},
  {"name":"Size","type":"bucket_numeric","source":"Amount",
   "bins":[0,1000,10000,1000000],"labels":["Small","Medium","Large"]}
]
```
Rules: `when` may be one filter or an AND-array; first match wins. Regex extraction needs a capture group; sources are attempted left to right; the first captured group is used. Map uses exact string keys and accepts legacy `map` as an alias for `mapping`. Ratio zero denominators produce null. Concat fills missing source cells with empty text. Numeric buckets include the lowest boundary and otherwise follow right-closed pandas cut intervals; out-of-range values are not silently assigned to the nearest bucket.

## Value rules
```json
{"source":"debit_minus_credit","null_as_zero":true,
 "flip_sign_when":[{"col":"Account","op":"startswith","val":"4"}]}
```
`source` is `column` or `debit_minus_credit`. Optional `column`, `debit`, `credit` override the corresponding roles. `null_as_zero` defaults true. Every matching flip multiplies by -1; two matching flips cancel. All role-token amount measures use the resulting internal value column.

## Periods and comparison
```json
{
 "periods":{"calendar":"calendar"},
 "period_format":"MON-YY",
 "partial_periods":["2026-05"],
 "comparison":{"type":"MoM",
   "base":{"months":["2026-04"],"scenario":"Actual","filters":[]},
   "current":{"months":["2026-05"],"scenario":"Forecast","filters":[]}}
}
```
Calendar can instead be `{"start_month":4}` for fiscal-quarter labels. Month lists are explicit and normalized to YYYY-MM. A slice can include scalar/list scenario and additional filters. The type label does not calculate periods by itself. Mixed legacy labels normalize; unparseable periods fail rather than being guessed.

Input format choices are auto, YYYY-MM, MON-YY, MON-YYYY, MM/YYYY, DD/MM/YYYY, MM/DD/YYYY and YYYY-MM-DD. Partial-month detection is a row-count heuristic; it never silently drops months.

## Tokens
Exact `{roles.value}` resolves to the current amount column. `{roles.driver_text}` resolves to its array. Base/current context provides `months`, `first_month`, `last_month` and slice fields, allowing filters such as `{"col":"__month","op":"eq","val":"{base.first_month}"}`. Exact tokens preserve their native list/number/null value. Embedded tokens convert to text. Unknown tokens fail. Do not nest list-valued tokens where a scalar is expected.

## Source joins
```json
{"source":"open_po",
 "on":[{"left":"Base_PO","right":"PO_Number"}],
 "how":"left","columns":["PO_Status","Owner"],"prefix":"po_",
 "key_normalise":["trim","upper","lstrip_zeros"],
 "dedupe_right":"error","unmatched":"warn","optional":false}
```
`on` supports composite keys. Blank/null components do not match other blanks. Only left joins are supported. Missing output columns or prefix collisions fail. Normalization runs in sequence on both sides. `first` deduplicates right keys deterministically; `error` stops on matching duplicates. `unmatched` is allow/warn/stop. Optional missing lookups produce null output fields and a warning/audit record. Audit contains duplicate keys, fanout, unmatched keys, rows and signed value.

## Classification
```json
{"target_col":"Category","source_cols":["{roles.driver_text}"],
 "rules":[{"keyword":"chlr","category":"Chillers","match":"contains","reviewed":true}],
 "fallback":"Other / General Maintenance","case_sensitive":false}
```
First match wins by default. Matches: contains, eq, startswith, regex. Optional `first_match:false` is a compatibility extension for last-match behavior; the normal UI uses first-match. Optional legacy `keyword_map` and `review_flags` remain import-compatible, but canonical saves use ordered rules. Agent-created entries are unreviewed; reviewed matching entries are preserved. Row coverage and absolute-value coverage exclude the fallback category. Coverage previews are consolidated text groups.

## Measures and views
```json
{
 "measures":{
  "amount":{"agg":"sum","col":"{roles.value}"},
  "M1_base":{"agg":"sum","col":"{roles.value}","slice":"base",
    "filter":[{"col":"__month","op":"eq","val":"{base.first_month}"}]}
 },
 "views":[{"name":"country","keys":["Country"],"measures":["amount"],"compare":true}]
}
```
Aggregation choices: sum, count, nunique, mean, min, max. `filter` is an AND-array. Omit `slice` for a normal compared measure. `slice:none` bypasses passed base/current slices; do not use it for an ordinary amount comparison. In a noncompared view, `slice:base`/`current` selects the fixed measure slice. Group keys can be empty for totals.

A compared measure emits `_base`, `_current`, `_delta`, `_delta_pct`. Delta is current minus base; percentage is delta divided by absolute base, or null if base is zero. Full outer grouping retains new and removed members. Driver measures must be additive sums.

View-level `joins` are legacy aggregated lookup summaries: `lookup`, `left_on`, `right_on`, optional `key_normalise`, `optional`, and `fields`. A field definition has `type:exists`, `exists_where` with `filter`, or `value` with `col`. These attach existence/value attributes to grouped views, not fact rows.

## Expressions, flags and gates
```json
{
 "flags":[{"view":"po","name":"Observation",
  "ordered":[{"if":"abs(M1_curr - M1_base) > 5000","label":"Material"}],
  "default":"Consistent"}],
 "gates":[{"view":"po","name":"Needs review",
  "if":"gao_booked and Observation == 'Material'"}]
}
```
Expression grammar supports known column names, string/number/boolean/null constants, lists/tuples, + - * /, unary signs, comparisons, membership, and/or/not, and explicitly whitelisted functions (`abs`, `isnull`, `startswith`, `contains`). No attribute access, imports, indexing-based execution, comprehensions, loops, eval or exec. Expressions are capped at 4,000 characters and 500 AST nodes.

Flags use first-true order and default; every row receives one label. Gates filter flagged view rows into exceptions. Numeric expression calculations use Decimal values.

## Sections and decomposition
`sections` can be null, or `{"split_by":"Spend_Type","order":["Recurring","One-off"],"must_reconcile_to":"amount"}`. It groups movements for commentary and checks reconciliation.

`decompose` can be null, or `{"volume":"Headcount","rate":"Cost_per_head","method":"volume_at_base_rate","measure":"amount","view":"department"}`. Volume effect is volume change times base rate; rate effect is the residual needed to reconcile total movement, including interaction/mix effects. Input measures and units must be meaningful; AI cannot establish causality from this arithmetic.

## Drivers, materiality and drills
```json
{
 "drivers":{"view":"country","measure":"amount","top_n":15,"others_label":"Other items",
   "materiality":{"mode":"max_of","abs":300000,"pct":0.05,"basis":"abs_total_movement"}},
 "drill":{"group_by":"{roles.driver_text}","top_n":5}
}
```
Modes: abs, pct_of_total, max_of, min_of. Fractional pct is 0–1. Bases: abs_total_movement, abs_total_base, abs_total_current (legacy total_delta/base/current aliases accepted). max/min compare absolute and percentage thresholds. Eligible drivers sort by absolute movement, stable on ties; top_n limits named drivers. Everything excluded is combined into Other items. Top descriptions plus Remaining transactions reconcile to each driver. Presentation thresholds never remove source value.

## Commentary settings
```json
{"units":"M","decimals":1,"currency_symbol":"$","sign_style":"plus_minus",
 "dimension_label_style":{"Country":"code"},"forbidden_terms":[],
 "max_line_words":35,"verify_tag":"[TO VERIFY]",
 "headline_template":"Total {label} movement {delta_fmt}, mainly {top_driver}."}
```
Units: M, K, none; B and units remain import-compatible. Decimals: 0–6. Sign style: plus_minus or fav_unfav. Optional `favorable_when` is negative or positive (default positive). Dimension style accepts explicit aliases per dimension, for example `{"Country":{"United Kingdom":"UK"}}`; code style does not infer an external country dictionary.

Headline placeholders: label, delta_fmt, top_driver; legacy flux_name, total_delta, total_base, total_current also work. Amount tokens are supplied by Python. A value that would round to a misleading zero uses a more precise raw token.

## Controls and outputs
See the [control catalogue](/docs?doc=controls). Stops block release. Warnings remain in the result pack. Engine result contains totals, views, drivers, flags, exceptions, drills, sections, controls, evidence, materiality_threshold, classification/review, join_audit, monthly counts and partial months.

Every completed run stamps ID, time, engine version, preset/version, canonical spec SHA-256 and input-byte SHA-256 values. The Excel review pack opens on a Summary overview (comparison, totals, explanation status, key drivers, linked contents) followed by Needs Explanation, Commentary, Drill-down, Data checks, Data and Settings. Supporting detail (Variance, Movement detail, Source lines, Classifications, Unmatched lookups) and the audit trail (Data controls, Setup changes, Explanation log, Run audit, AI assistant log, FluxSpec) follow, grouped by tab colour. The Run audit and FluxSpec sheets and the FluxSpec JSON download contain the stamp. Uploaded or edited text that could be read as a formula is written as inert text. Word and Markdown downloads are retired. Reuse preserves settings but binds them to current uploaded sources; it does not overwrite historical evidence.

## Stateless agent request
```json
{"request_id":"unique-id","step":"map_columns","user_message":"",
 "spec_so_far":{"spec_version":"2.0"},
 "payload":{"profile":{"columns":[]},"preset":{"id":"generic_flux","version":"1.0.0","guidance":"..."}}}
```
`spec_so_far` is the complete current spec (abbreviated above). There is no dependence on an earlier conversation. Public Python entry points are `agent.client.call(step,spec_so_far,payload,user_message="")` and `invoke_agent(envelope,timeout_s=...,log_dir=...)`. The payload builder is the recommended privacy boundary.

## Agent steps and payload expectations
- detect_flux: headers, user text and available preset metadata. Proposal: preset_id, flux_name, optional scope_suggestion.
- map_columns: profile and previous_roles. Proposal: roles.
- define_comparison: distinct period values, today, canonical available months, monthly counts and partial candidates. Proposal: comparison, optional period_format and partial_periods.
- derive_columns: selected column distinct-value/count metadata. Proposal: scope, derive, optional joins/value_rules.
- classify_terms: consolidated terms/amounts, relevant preset categories. Proposal: rules or mappings, optional source_col/target_col. Mappings contain term, category and keyword_rule.
- define_rules: current spec and relevant defaults. Proposal: measures, views, drivers, controls; optional flags, gates, sections, decompose, drill, commentary, value_rules, joins and classification.
- write_commentary: evidence_pack with preformatted tokens and ordered drivers, per-driver history (trend pattern decided by Python), volume/rate, category approval, flags and coverage, report data_quality/coverage_notes, plus writing_guidance (each preference tagged user/preset/default) and attributed, unverified business_context. Proposal: lines of driver_id/text/support/evidence_refs with optional claims (observation, possible_explanation, context) and confirm_prompt, headline and others_summary. Checks reject unknown or other-movement references, unsupported amounts and numbers, trend wording the history does not show and unmarked causes.
- apply_instruction: instruction, target card and available column names. Proposal: RFC6902 patch (or additive top-level patch), optional summary/changes.
- explain_spec: current declarative settings. Proposal: sentences.
- answer_question: question, optional selected run evidence and deterministic rule descriptions. Proposal: answer. This step cannot mutate settings.

Every step includes preset guidance and only relevant defaults. Sample lists are capped at 10 and requests at 50 KiB. No raw row arrays are uploaded. Size trimming is explicit; an envelope still over the cap is rejected.

## Agent response contract and application
```json
{"request_id":"same-id","step":"apply_instruction","status":"ok",
 "proposal":{"patch":[{"op":"replace","path":"/drivers/top_n","value":5}]},
 "confidence":"low","rationale":"Requested a shorter driver list.",
 "questions":[],"warnings":[],"summary":"Show five drivers.",
 "changes":[{"setting":"Top drivers","from":"15","to":"5","reason":"User request"}]}
```
Status is ok, needs_input or cannot_do; confidence high, medium or low. Questions contain id, question and options. A valid applicable result auto-applies at any confidence; low confidence is visibly warned. Needs_input can apply a valid partial proposal while displaying questions. Cannot_do never mutates. Invalid schema or patch leaves the previous state intact. Stale responses do not overwrite settings changed while the request was running.

Patch operations are add, remove, replace and test with JSON Pointer paths, including escaped ~ and /. The operation array is atomic: all operations and the resulting full spec validate before commit. Undo/redo also use audited patches. Audit records timestamp, actor, path, operation, before, after and reason.

One stateless validation repair includes all errors, expected schema, original request ID, previous output and preset context. Financial narrative additionally receives one content-repair attempt. No amount is accepted because an LLM claims to have calculated it.

## HTTP interface
- GET /state; GET /jobs/{id}.
- POST /sources/upload, /sources/{id}/define; GET /sources/{id}/preview; DELETE /sources/{id}.
- GET /presets, /presets/{id}, /presets/{id}/export; POST /presets/apply, /presets/save, /presets/import.
- POST /config/{step}/suggest auto-applies valid configuration; the older accept route remains compatibility-only.
- POST /spec/patch, /spec/undo, /spec/redo, /instruction.
- POST /classification/preview, /config/preview/{scope|derive|joins|value_rules}, /review/controls.
- POST /run; GET /results/{id}?format=json and /results/{id}/drill/{driver}.
- POST /results/{id}/narrative (optional driver_id), /results/{id}/commentary (text and aligned lines), /questions.
- POST /runs/{id}/reuse; GET /download/{id}/{excel|spec} (docx and markdown return a 400 explaining they are retired).
- GET /docs and /help/{doc_id}; saved spec routes remain available for import/save/load.

Mutating requests need the session's X-CSRF-Token header. Async endpoints return HTTP 202 plus job_id, then pending/done/error status. Instruction/config jobs return the response envelope plus applied and current state. Runs return run_id. Server restarts lose pending jobs, not completed files.

## Live API transport
Required private environment settings are EAP_BASE_URL, EAP_AGENT_ID, EAP_API_KEY and EAP_PAT. POST to `/api/v1/agents/{agent}/invoke` uses Api-Key and X-EAP-Authorization: Bearer PAT headers, with the JSON envelope serialized into `message`. HTTP 200 reads response; HTTP 202 polls the returned conversation's messages until a non-user response or timeout. Network/429/5xx retries are bounded. Credentials are never sent to the browser or logged.

Use [local setup and privacy guidance](/docs?doc=ai_and_data) and [known limits](/docs?doc=known_gaps) before using real corporate data.
