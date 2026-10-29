# Flux Analyzer Engine and Agent Contract

> **Version note:** This is the original v1 contract. The authoritative v2 replacement is `docs/reference.md`, available in the app at `/docs?doc=reference`. Presets replace skills, valid AI settings auto-apply with undo, and canonical v2 join/classification/materiality contracts supersede older examples below.

**Purpose:** a comprehensive reference for building or instructing an Equinix AI
Engine agent that proposes configurations for Flux Analyzer. It documents the
implemented engine behavior, exact JSON shapes, accepted rule vocabulary,
validation boundaries, and an agent prompt you can adapt.

**Contract version:** FluxSpec `1.0`. The authoritative machine-readable
response schema is `agent/schemas/responses.json`; the authoritative reusable
example configurations are in `examples/`. This guide explains their meaning,
but does not replace validation against those files.

---

## 1. Operating model

Flux Analyzer separates **suggestions** from **financial computation**:

1. A user uploads CSV/XLSX files, explicitly chooses each sheet, header row,
   column range, source role, and (optionally) matching sheets to stack.
2. Python parses the selected data, computes metadata and aggregates, and
   constructs a bounded JSON envelope for the requested agent step.
3. The Equinix AI Engine proposes JSON. The browser shows the proposal as an
   editable draft; it is not configuration yet.
4. The user explicitly accepts the proposal, or edits the FluxSpec directly.
   Python validates the response schema and the resulting full FluxSpec before
   saving it.
5. Python alone executes approved rules, periods, measures, joins, flags,
   gates, drivers, reconciliations, evidence, and exports.
6. Commentary may be proposed separately. Python checks it against
   deterministic evidence; the user must accept it and save it explicitly.

The agent is **not** a general-purpose calculator. It must not receive raw
transaction rows, calculate financial totals, invent facts, or silently apply
any proposed configuration. It should return the required JSON only.

### Data boundary

- Uploads, parsed data, caches, projects, specs, runs, workbooks, and drill rows
  remain in the local Flask process/workspace.
- Agent inputs contain bounded source metadata and aggregated evidence, not
  transaction records. `detect_flux` receives header names; `map_columns`
  receives an aggregate profile; comparison and classification steps receive
  summarized values; commentary receives consolidated drivers and evidence.
- Agent payloads are JSON encoded and capped at **50 KiB**. Selected metadata
  lists are trimmed, but the existing `spec_so_far` is not silently discarded.
  If the whole envelope still exceeds the cap, the request fails and must be
  simplified manually.
- The browser never holds the Equinix API credentials. The server sends
  `Api-Key` and `X-EAP-Authorization: Bearer <PAT>` headers.
- The mock agent is a generic demonstration template, not a live agent and
  not a source of domain-specific R&M/Benefits policy.

### What is authoritative

| Concern | Authority |
| --- | --- |
| What a column means or which periods to compare | Analyst, with optional agent suggestion |
| Whether an agent response has the right structure | JSON Schemas and Python |
| Whether an uploaded column/rule exists and can run | Python validation and controls |
| Numeric aggregation, signs, cents, and reconciliation | Python engine |
| Cause of a financial change | Source evidence and analyst judgment |
| Whether an accepted proposal changes the spec | Explicit user action only |
| Whether an AI commentary proposal is valid | Python evidence checks, then explicit user action |

---

## 2. Agent request/response protocol

### 2.1 Request envelope

Every agent call is a JSON object of this form:

```json
{
  "request_id": "a-unique-request-id",
  "step": "map_columns",
  "skill": "rm_flux",
  "user_message": "Use the country/account hierarchy in this workbook.",
  "spec_so_far": {
    "spec_version": "1.0",
    "flux_name": "Example analysis",
    "sources": {},
    "roles": {
      "value": null,
      "period": null,
      "scenario": null,
      "debit": null,
      "credit": null,
      "keys": [],
      "dimensions": [],
      "driver_text": []
    },
    "comparison": {
      "type": "QoQ",
      "base": {"months": []},
      "current": {"months": []}
    }
  },
  "payload": {}
}
```

The example's `spec_so_far` is abbreviated. In a real request it is the full
current FluxSpec. `skill` may be `null`. `user_message` is truncated by the
server to 3,000 characters. The request ID must be echoed exactly in the
response. The `step` must be echoed exactly, except for the repair behavior
described below.

**Do not return or request credentials.** Credentials are server-side
environment configuration and never part of this envelope.

### 2.2 Required response envelope

Return one JSON object, with exactly these top-level fields:

```json
{
  "request_id": "a-unique-request-id",
  "step": "map_columns",
  "status": "ok",
  "proposal": {},
  "confidence": "medium",
  "rationale": "The amount, period, and organization columns are supported by the profile.",
  "questions": [],
  "warnings": []
}
```

| Field | Contract |
| --- | --- |
| `request_id` | Required string. Copy the request exactly. |
| `step` | Required supported step string. Normally equals the request `step`. |
| `status` | One of `ok`, `needs_input`, `cannot_do`. |
| `proposal` | Required object. It must match the schema for this step. Do not wrap it in prose or an extra `proposal` property. |
| `confidence` | One of `high`, `medium`, `low`. Do not use numeric confidence. |
| `rationale` | Required string, maximum 600 characters. State the evidence and assumptions concisely. |
| `questions` | Required array. Each item has exactly `id`, `text`, and `options`; all are required, and `options` is a string array. Use `[]` when no question is needed. |
| `warnings` | Required array of strings. Use `[]` when there are no warnings. |

The response envelope rejects additional properties. Every `ok` response is
checked against its step schema; before **any** proposal can be accepted, the
server validates the edited proposal against that step's schema again.
Configuration proposals are also checked against the full FluxSpec schema.

#### Status behavior

- **`ok`**: provide a complete, usable proposal for this step. Python validates
  the proposal and FluxSpec. The user still needs to accept it.
- **`needs_input`**: provide the best safe, step-schema-shaped proposal you
  can, list concise
  blocking/clarifying questions, and explain the unresolved assumption in
  `rationale` or `warnings`. The runtime does not validate the step proposal
  until acceptance for this status; still return the required complete
  proposal shape, because the accept operation will validate it. Do not claim
  the incomplete part has been decided.
- **`cannot_do`**: state why in `rationale` and/or `warnings`; do not fabricate
  data. `proposal` is still required and must validate. Prefer a structurally
  valid, minimal proposal only if it is safe and genuinely useful. Otherwise
  return the closest valid no-op/current configuration the step permits and
  clearly say no new decision was made.

The UI treats a proposal as a draft in every case. It never turns `status:
ok` into automatic approval.

### 2.3 JSON formatting and repair

- Return raw JSON, not Markdown commentary. Optional JSON code fences are
  stripped, but raw JSON is the reliable format.
- Return no NaN or Infinity values. Use valid JSON `null` where appropriate.
- If the first response is malformed or fails schema validation, the client
  may make **one** repair call. The repair request carries the original
  expected step and request ID in its payload. The repaired response must
  satisfy the **original** step schema and echo the **original** request ID.
- The repair call is not a new user decision. If repair also fails, the step
  fails and the user can edit the configuration manually.
- Live 4xx responses are not retried. Network failures and server errors are
  retried twice. A live asynchronous invocation is polled until completion or
  timeout.

---

## 3. Steps and the exact agent payloads

The browser groups some steps together, but the server uses these independent
step names:

```text
detect_flux
map_columns
define_comparison
derive_columns
classify_terms
define_rules
write_commentary
```

`write_commentary` is only called after a calculation has completed; it is not
a configuration suggestion endpoint.

### 3.1 `detect_flux` — identify the analysis type

**Request payload**

```json
{
  "headers": ["Period", "Scenario", "Account", "Country", "Cost"],
  "user_text": "Compare forecast with actual by department.",
  "available_skills": ["benefits_flux"]
}
```

- `headers`: exact defined primary-data column names, excluding private
  internal columns.
- `user_text`: user-provided context, bounded to 3,000 characters in the
  outer envelope.
- `available_skills`: zero or one currently selected skill ID. This is not an
  automatic discovery of skills installed in the Equinix system.

**Proposal schema**

```json
{
  "skill": "benefits_flux",
  "flux_name": "Benefits Actual vs Forecast",
  "required_sources": ["Monthly actual and forecast ledger"],
  "optional_sources": ["Department mapping"]
}
```

Required fields: `skill` (string or `null`), `flux_name` (string).
`required_sources` and `optional_sources` are optional arrays. The step
currently applies only `skill` and `flux_name` to the FluxSpec. Source
descriptions are advice for the analyst: they do **not** upload, map, or
configure files.

**Good behavior:** identify a skill only when the user's request or known
agent-side skill supports it; otherwise return `null` and ask a question.
Do not label data as R&M/Benefits solely because of a column name unless the
skill's documented evidence supports the inference.

### 3.2 `map_columns` — suggest role mappings

**Request payload**

```json
{
  "profile": {
    "n_rows": 250,
    "columns": [
      {
        "name": "Functional Net",
        "dtype_guess": "number",
        "pct_empty": 0.0,
        "n_unique": 32,
        "samples": ["1835.16", "-42.98", "0"]
      }
    ]
  },
  "previous_roles": {
    "value": null,
    "period": null,
    "scenario": null,
    "debit": null,
    "credit": null,
    "keys": [],
    "dimensions": [],
    "driver_text": []
  }
}
```

The profile contains per-column name, guessed type, percentage empty, unique
count, and at most five distinct example values (each shortened to at most 60
characters). A profile sample is metadata, not a transaction row. Guesses are
heuristics, not certified types. `previous_roles` allows a proposal to preserve
user work.

**Proposal schema**

```json
{
  "roles": {
    "value": "Functional Net",
    "period": "Month",
    "scenario": "Scenario",
    "debit": "Debit",
    "credit": "Credit",
    "keys": ["Department Code"],
    "dimensions": ["Department", "Country"],
    "driver_text": ["Description"]
  },
  "unmapped": ["Optional internal reference"]
}
```

- `roles` is required and is merged with other current roles. Only supported
  role keys are accepted by the full FluxSpec schema.
- `unmapped` is an optional informational list. It is not a role and does not
  cause source columns to be discarded.
- Each scalar role is a real column name or `null`.
- `keys`, `dimensions`, and `driver_text` are arrays of real column names.

**Role semantics**

| Role | Meaning |
| --- | --- |
| `value` | Primary numeric measure used for totals and transaction drills. Required before calculation. |
| `period` | Month/date/fiscal-period source column. Python canonicalizes it into private `__month`. |
| `scenario` | Column containing values such as `Actual` and `Forecast`. Required to select scenario slices. |
| `debit`, `credit` | Optional fields used by the debit-minus-credit control. Set the sign convention in the skill/instructions. |
| `keys` | Stable identifiers available for grouping or explanation. Do not use as business drivers unless that is intended. |
| `dimensions` | Business grouping columns. These are the primary dimensions for variance views and membership checks. |
| `driver_text` | Description fields that can be grouped for consolidated evidence and drill-down. They are not raw narrative evidence sent in full. |

Mapping the wrong value or period column is a blocking error for meaningful
results. Ask the user when two candidates are plausible; do not silently
reinterpret signs or dates.

### 3.3 `define_comparison` — define base and current slices

**Request payload**

```json
{
  "period_values": [
    {"value": "2026-01", "count": 50, "sum_value": 210000}
  ],
  "today": "2026-10-27",
  "available_months": ["2026-01", "2026-02"],
  "scenario_values": [
    {"value": "Actual", "count": 50},
    {"value": "Forecast", "count": 50}
  ]
}
```

- `period_values`: up to 50 common period values and row counts (plus exact
  value-column total when available).
- `today`: server date in ISO format; do not use it to infer a reporting cutoff
  when explicit data or user directions conflict.
- `available_months`: canonical months, expanding quarter labels to their
  three-month coverage.
- `scenario_values`: included only when the scenario role is mapped; up to 50
  values.

**Proposal schema**

```json
{
  "comparison": {
    "type": "Actual vs Forecast",
    "base": {
      "months": ["2026-01"],
      "scenario": "Forecast",
      "filters": []
    },
    "current": {
      "months": ["2026-01"],
      "scenario": "Actual",
      "filters": []
    }
  },
  "period_format": "YYYY-MM",
  "partial_periods": []
}
```

`comparison` is required; its `type` is a descriptive string and it must
contain both `base` and `current`. Each slice can contain:

- `months`: array of recognized date/month/quarter labels. Quarter labels are
  expanded to three canonical months.
- `period`: one period string, as an alternative to `months`.
- `scenario`: one string or `null`. The implemented JSON schema accepts a
  scalar scenario, not a scenario array.
- `filters`: zero or more custom AND filters using the filter grammar in
  Section 5.

`period_format` and `partial_periods` are optional hint fields. `period_format`
is saved as metadata; actual period parsing is performed by Python's supported
date formats and configured fiscal calendar. Python recomputes missing months
and stop controls; it does not trust the agent's `partial_periods`.

**Supported period inputs**

- `JAN-26`, `Jan-2026`, `2026-01`, `01/2026`
- dates such as `2026-01-15`, `15/01/2026`, or `01/15/2026`
- `Q1 2026` through `Q4 2026`
- `FY26 Q1` through `FY26 Q4` when fiscal calendar configuration is present

Date and month values normalize to `YYYY-MM`. For a fiscal calendar with
`start_month: 4`, fiscal Q1 starts in April. The implementation uses the
starting-year convention for fiscal labels. No periods are guessed from
ambiguous dates; ask for clarification when the data locale matters.

### 3.4 `derive_columns` — propose scope and derived columns

**Request payload**

```json
{
  "value_counts": [
    {
      "Country": "NL",
      "Account": "54100",
      "count": 18,
      "sum_value": 450000
    }
  ],
  "roles": {
    "value": "Amount",
    "dimensions": ["Country", "Account"],
    "driver_text": ["Description"]
  }
}
```

Python groups the first two configured `dimensions` plus `driver_text`
columns (up to two columns total) into counts and optional exact sums.
Returned values are aggregates, not lines. The server trims supported
metadata lists to stay within the request cap.

**Proposal schema**

```json
{
  "scope": [
    {"col": "Account", "op": "startswith", "val": "54"}
  ],
  "derive": [
    {
      "name": "Category",
      "type": "rules",
      "rules": [
        {
          "when": {"col": "Description", "op": "contains", "val": "reversal"},
          "then": "Reversal"
        }
      ],
      "default": "Other"
    }
  ]
}
```

Both `scope` and `derive` are required by this step's response schema.
`scope` filters included rows. `derive` creates columns before scope is
applied. Rule order matters; the first matching rule wins. See Section 5 for
all derivation types and operators.

Instructions should specify:

- Which source columns are trustworthy for inclusion/exclusion.
- Exact include/exclude logic; scope filters are ANDed.
- Ordered classification precedence and a default/unmatched label.
- Whether transforms must preserve an original source field.
- Whether a suggested classification is a hypothesis that needs analyst
  review.

### 3.5 `classify_terms` — propose aggregate description mappings

**Request payload**

```json
{
  "allowed_categories": [],
  "terms": [
    {"text": "Cooling accrual JAN-26", "abs_value": 1835.16, "n": 1}
  ]
}
```

The server chooses the first `driver_text` column and sends up to 100
consolidated terms, sorted by absolute value. Each text is shortened to 120
characters. `n` is the row count; `abs_value` is the absolute exact sum of the
configured value column, if available. This is not a raw row list.

**Proposal schema**

```json
{
  "mappings": [
    {
      "term": "Cooling accrual",
      "category": "Facilities",
      "keyword_rule": "Cooling accrual"
    }
  ],
  "target_col": "Category",
  "source_col": "Description"
}
```

Each mapping requires string `term`, `category`, and `keyword_rule`.
`target_col` and `source_col` are optional strings. The server uses
`source_col` or the first mapped `driver_text` column, then adds an ordered
case-insensitive literal substring rule to `derive`. It uses
`keyword_rule`, falling back to `term`, and assigns `category`; unmatched
values receive `UNMATCHED`.

Mappings are applied in the order returned. Earlier substring matches win.
Use specific terms before broad terms. Empty mappings do not add a derived
column. Do not infer a business cause solely from similar text; label
descriptions, not accounting truth.

### 3.6 `define_rules` — propose calculation and review configuration

**Request payload**

```json
{
  "spec_so_far": {
    "...": "The complete current FluxSpec"
  }
}
```

This step sees the current full spec. Use existing explicit choices as
constraints; do not silently replace analyst-accepted settings.

**Proposal schema**

The response requires `measures`, `views`, `drivers`, and `controls`. Other
properties below are optional:

```json
{
  "measures": {},
  "views": [],
  "sections": null,
  "decompose": null,
  "flags": [],
  "gates": [],
  "drivers": {},
  "drill": {},
  "commentary": {},
  "controls": []
}
```

The proposal's allowed rule fields match FluxSpec Sections 4–7. A proposal
may be valid JSON yet fail the full FluxSpec schema. Prefer complete,
cross-referenced configurations, and never include unimplemented rule types.

### 3.7 `write_commentary` — describe checked results, never calculate them

This is generated only after a successful Python run. It is not a way to
repair a calculation or to ask for new dimensions.

**Request payload**

```json
{
  "evidence_pack": {
    "flux_name": "Monthly expense variance",
    "drivers": [
      {
        "driver_id": "d1",
        "label": "Operations",
        "dimensions": {"Department": "Operations"},
        "base": 13200,
        "current": 14100,
        "delta": 900,
        "delta_fmt": "+$900.00",
        "top_texts": [
          {"text": "Employee benefits", "delta_fmt": "+$900.00"}
        ],
        "n_lines": 12,
        "flags_summary": {}
      }
    ],
    "sections": [],
    "commentary_rules": {
      "units": "K",
      "decimals": 1,
      "verify_tag": "[TO VERIFY]",
      "forbidden_terms": []
    }
  },
  "commentary_rules": {}
}
```

The evidence pack is aggregated and bounded: up to five consolidated drill
texts per driver, each shortened to 160 characters. It contains numeric facts
formatted by Python. It does not contain original transactions or a verified
business cause.

Each driver may also carry Python-built context: `base_fmt`/`current_fmt`, a
`trend` (up to six earlier windows of the compared length and a `pattern` such
as `one_period`, `continuing` or `reversal`), a volume/rate `decomposition`,
the `categories` mix with each category's rule `approval`, `flags` and
`coverage` (lines behind it, descriptions shown, unmatched or uncategorised
lines, incomplete periods). The pack adds `totals`, `data_quality`,
`coverage_notes`, `materiality_policy`, the allowed references and number
tokens, `writing_guidance` (each preference tagged `user`, `preset` or
`default`) and `business_context` — facts a person or preset stated, marked
`verified: false`, cited as `context:user:N` / `context:preset:N`. Lines may
add `claims` (`observation`, `possible_explanation`, `context`) and a
`confirm_prompt`. See `docs/agent/contract.md` for exact shapes.

**Proposal schema**

```json
{
  "lines": [
    {"driver_id": "d1", "text": "Operations increased by +$900.00. [TO VERIFY]"}
  ],
  "headline": "Current period increased against base.",
  "others_summary": "Remaining drivers reconcile to the reported movement."
}
```

Required fields are `lines`, `headline`, and `others_summary`. Every line
requires `driver_id` and `text`. Return exactly one line for every evidence
driver, in the same order, with no missing or duplicated IDs.

Python rejects commentary when:

- driver IDs are omitted, duplicated, or reordered;
- the driver's signed `delta_fmt` is not reproduced verbatim in its line;
- a line introduces an unsupported currency amount;
- unsupported numeric claims appear in the headline, line, or others summary;
- the text contains `$0.0M`;
- a reference is unknown or belongs to another driver, or a supported line
  cites nothing;
- an observation claim cites no checked evidence or states a cause, or a
  possible explanation has no verify tag and does not just repeat a cited
  context fact;
- AI wording describes a one-period, continuing or reversal pattern that the
  driver's `trend.pattern` does not show (or does not cite it);
- AI wording states a cause, timing or one-off without the verify tag, unless
  the stated reason only repeats a context fact it cites; or
- a configured forbidden term appears.

One repair attempt may be made. If validation still fails, the UI displays the
issues. A valid proposal remains a proposal until the analyst accepts and
saves it. Manual edits are marked unverified and warn that their financial
claims are no longer automatically checked.

---

## 4. FluxSpec v1.0 — complete configuration reference

The FluxSpec is the portable declarative representation of an analysis. The
full top-level object requires:

```json
{
  "spec_version": "1.0",
  "flux_name": "Name shown in results",
  "sources": {},
  "roles": {},
  "comparison": {
    "type": "Comparison label",
    "base": {"months": ["2026-01"]},
    "current": {"months": ["2026-02"]}
  }
}
```

Unknown top-level properties are rejected. Unknown `roles` properties,
comparison-slice properties, measures properties, views properties, flags,
gates, driver, drill, commentary, and control properties are rejected unless
their schema explicitly allows otherwise. Some inner objects (`sources`,
`sections`, `decompose`, individual derived-column definitions, joins, and
control `params`) are intentionally open-ended and are checked by the
relevant engine path.

### 4.1 Top-level fields

| Field | Type / default | Purpose |
| --- | --- | --- |
| `spec_version` | Required constant `"1.0"` | Schema contract version. |
| `flux_name` | Required string, 1–120 characters | Human-readable analysis name. |
| `skill` | String or `null` | Optional Equinix agent-side skill ID. It does not load a skill by itself. |
| `sources` | Object, default `{}` | Portable file/sheet definition. Runtime binds current uploaded files to it. |
| `roles` | Role object | Source-to-business-column assignments. |
| `scope` | Filter array | Optional row filters, ANDed together. |
| `derive` | Derived-column array | Ordered transforms; each output column may be used by later transforms. |
| `periods` | Object | Optional period format metadata and calendar. |
| `comparison` | Required comparison object | Base/current slices; see Section 3.3. |
| `measures` | Map of named measure objects | Aggregations used by views and drivers. |
| `views` | Array of views | Groupings and requested measures. |
| `sections` | Object or `null` | Optional section-level reconciliation split. |
| `decompose` | Object or `null` | Optional volume/rate analysis. |
| `flags` | Array | Ordered labels applied to compared view rows. |
| `gates` | Array | Explicit expression-based exception subsets. |
| `drivers` | Driver options | Chooses a compared sum measure and ranks movement. |
| `drill` | Drill options | Chooses source columns consolidated beneath each driver. |
| `commentary` | Commentary formatting/rules | Amount display settings and forbidden words. |
| `controls` | Array | Selectable registry controls; mandatory safety checks still run. |

### 4.2 `sources`

Runtime source definitions are refreshed from the analyst's current files.
Portable source entries use the following shape:

```json
{
  "primary": {
    "files": [
      {
        "file": "ledger.csv",
        "sheet": "Sheet1",
        "header_row": 1,
        "start_col": "A",
        "end_col": "F"
      }
    ],
    "union": {"mode": "stack", "tag_column": null}
  },
  "lookups": {
    "open_po": {
      "files": [
        {
          "file": "open_po.xlsx",
          "sheet": "Open PO Report ",
          "header_row": 4,
          "start_col": "A",
          "end_col": "C"
        }
      ]
    }
  }
}
```

- Source file choices are remapped to files the user uploads; filenames and
  sheet names can differ between machines.
- Excel sheet names are exact. Preserve whitespace in sheet names.
- Header rows are one-based. Column boundaries use spreadsheet letters.
- Several selected sheets may be stacked if their cleaned headers match.
- Lookup files are separate from primary sources; lookup join behavior is in
  Section 6.3.
- A stacked primary dataset can attach a sheet/source tag column. Choose a
  tag name that does not collide with an existing header.

### 4.3 `roles`

```json
{
  "value": "Amount",
  "period": "Period",
  "scenario": "Scenario",
  "debit": "Debit",
  "credit": "Credit",
  "keys": ["Cost Center Code"],
  "dimensions": ["Department", "Country"],
  "driver_text": ["Description"]
}
```

`value`, `period`, `scenario`, `debit`, `credit` are strings or `null`.
`keys`, `dimensions`, and `driver_text` are arrays of strings. Only these
role names are accepted. The UI prevents a column from being assigned to more
than one of the value/period/scenario/debit/credit selector fields. Required
role, scope, and derive-source dependencies are checked during preflight;
measure/view/join dependencies are also checked where those operations run.
Source and derived column names must match exactly.

### 4.4 `periods`

```json
{
  "format_in": "MON-YY",
  "calendar": "calendar"
}
```

or:

```json
{
  "calendar": {"start_month": 4}
}
```

The schema accepts `calendar` or an object with integer `start_month` from
1 through 12. Python adds an internal canonical `__month` column; it preserves
the input period column. A period value that cannot be parsed raises an
explicit error. Quarter labels represent all three constituent months when
evaluating coverage and comparison slices.

### 4.5 Token references

Strings may refer to spec or resolved-comparison values:

```json
"{roles.value}"
"{roles.period}"
"{base.first_month}"
"{current.last_month}"
```

Tokens are resolved recursively before execution. A string consisting solely
of a token preserves the token's underlying JSON type (string, number, array,
object, or `null`). Embedded tokens are interpolated as text. Unknown tokens
raise an error. They are not Python expressions and do not allow code
execution.

Example for a single-month comparison:

```json
{
  "agg": "sum",
  "col": "{roles.value}",
  "slice": "none",
  "filter": [
    {"col": "{roles.period}", "op": "eq", "val": "{current.first_month}"}
  ]
}
```

Period filters on the mapped period column are rewritten to the canonical
internal `__month` column before calculation.

---

## 5. Filters, safe expressions, and derived columns

### 5.1 Filter object

All filter objects have exactly:

```json
{"col": "Column name", "op": "eq", "val": "value"}
```

`val` may be any JSON value where the operator supports it. `col` must name
an available source or derived column. A list of filters means **AND**:

```json
[
  {"col": "Country", "op": "in", "val": ["NL", "DE"]},
  {"col": "Account", "op": "startswith", "val": "54"}
]
```

Supported operators:

| `op` | Behavior |
| --- | --- |
| `eq`, `ne` | Equal / not equal. Numeric `val` requests numeric comparison; other non-null values compare as text. |
| `in`, `not_in` | Membership / non-membership in a JSON array. |
| `gt`, `gte`, `lt`, `lte` | Greater-than, at-least, less-than, at-most. |
| `startswith` | Text starts with `val`. |
| `contains` | Text contains `val` literally (not regex). |
| `regex` | Text matches the supplied regex. Patterns are limited to less than 500 characters. |
| `isnull`, `notnull` | Value is empty/null or not empty/null. Omit `val`. |

Unsupported operators, missing columns, or malformed rules raise errors; there
is no silent fallback. Regex is allowed only in the explicit filter/transform
features above and is length-limited.

### 5.2 Safe expressions for flags and gates

Expressions are parsed as a small Python-AST subset. **Never use Python
`eval` or `exec`; the engine does not.**

Allowed:

- Known column names.
- String, numeric, boolean, and `None` constants.
- Parenthesized arithmetic: `+`, `-`, `*`, `/`, `%`.
- Unary minus and `not`.
- Comparisons: `==`, `!=`, `>`, `>=`, `<`, `<=`, `in`, `not in`.
- Boolean combinations: `and`, `or`.
- List and tuple literals.
- `abs(x)`, `isnull(x)`, `startswith(text, prefix)`, `contains(text, value)`.

Example:

```text
M1_base == 0 and abs(M1_curr - M1_base) > 5000
```

Limits: 4,000 characters and 500 AST nodes per expression. Attribute access,
subscript access, comprehensions, imports, assignments, arbitrary functions,
keyword arguments, and code execution are rejected.

Conditions should refer to output columns present in the named view. Missing
columns are errors. Boolean flags use Python's safe vectorized expression
evaluator; null results are treated as non-matches.

### 5.3 Derived-column types

Definitions run in array order. Name every derived column uniquely. Later
derived columns may refer to earlier derived outputs. Each definition requires
`name` and `type`; the type is one of:

#### A. Ordered `rules`

```json
{
  "name": "Bucket",
  "type": "rules",
  "rules": [
    {
      "when": {"col": "Event Type", "op": "contains", "val": "Reversal"},
      "then": "Accrual - Reversal"
    },
    {
      "when": {"col": "Event Type", "op": "contains", "val": "Current"},
      "then": "Accrual - Current"
    }
  ],
  "default": "Operational"
}
```

`when` is either one filter or an array of filters; array conditions are ANDed.
Rules use first match wins. `then` is assigned literally. No match gets
`default` (empty string if omitted). The friendly UI shows its simple
single-condition form; edit advanced JSON for multi-condition rules.

#### B. `regex_extract`

```json
{
  "name": "Base_PO",
  "type": "regex_extract",
  "source": ["PO Number", "Description"],
  "pattern": "(\\d{6,})",
  "strip_suffix": "_V\\d+",
  "default": "UNMATCHED"
}
```

`source` is one column name or an array of column names searched in order.
Python applies `strip_suffix` (when supplied) before extraction, then takes the
first non-null match. `pattern` is limited to 500 characters. `default` is
optional and defaults to `UNMATCHED`. Regex must contain a useful capture
group if the desired result is a matched substring; test it against source
values before accepting.

#### C. `map`

```json
{
  "name": "Region",
  "type": "map",
  "source": "Country",
  "mapping": {"NL": "EMEA", "DE": "EMEA"},
  "default": "Other"
}
```

Maps the source's string value exactly through `mapping` (or its equivalent
`map` property). Unmapped values use `default`, otherwise `UNMATCHED`.
Treat map keys as explicit source values; do not assume case-insensitive
matching.

#### D. `ratio`

```json
{
  "name": "Cost_per_head",
  "type": "ratio",
  "numerator": "Cost",
  "denominator": "Headcount"
}
```

Divides row by row using `Decimal`. A zero denominator yields `null`.
Measure aggregation/formatting is a later step; this derived ratio is not
itself an additive amount.

#### E. `concat`

```json
{
  "name": "Org",
  "type": "concat",
  "source": ["Company", "Department"],
  "separator": " / "
}
```

Concatenates source columns row by row, converting nulls to empty strings.
`source` must be an array for the implemented concatenation branch.
`separator` defaults to one space.

#### F. `bucket_numeric`

```json
{
  "name": "Spend Band",
  "type": "bucket_numeric",
  "source": "Amount",
  "bins": [0, 1000, 10000, 1000000],
  "labels": ["Low", "Medium", "High"]
}
```

Uses ascending numeric bin edges with `pandas.cut`; invalid numeric values
raise errors. Provide a labels array that has exactly one fewer item than the
number of bin edges. `include_lowest` is enabled; the top interval behavior
follows `pandas.cut` and the supplied edges. Test boundaries and negative
values explicitly.

### 5.4 `scope`

`scope` is an AND list of filters that removes source rows before any period
comparison or measure calculation. It is distinct from:

- slice-level `filters`, which select base/current periods independently;
- measure-level `filter`, which narrows one measure;
- lookup field `filter`, which narrows rows in one lookup before matching.

Use the narrowest correct level and explain it in the rationale. If a filter
is intended to apply to both periods and every measure, use `scope`; if it
defines only one slice or measure, do not globally discard rows.

---

## 6. Measures, views, lookups, sections, and decomposition

### 6.1 Measures

`measures` is a JSON object keyed by unique measure name:

```json
{
  "amount": {
    "agg": "sum",
    "col": "{roles.value}",
    "slice": "none",
    "filter": []
  },
  "headcount": {
    "agg": "sum",
    "col": "Headcount",
    "slice": "none",
    "filter": []
  },
  "cost_per_head": {
    "agg": "mean",
    "col": "Cost_per_head",
    "slice": "none"
  }
}
```

| Property | Rules |
| --- | --- |
| `agg` | Required: `sum`, `count`, `mean`, `min`, `max`, or `nunique`. |
| `col` | Required real source/derived column name or a supported token. |
| `slice` | Optional: `none`, `base`, or `current`. When omitted, comparison mode applies base/current slices. |
| `filter` | Optional filter array; all conditions are ANDed. |

For compared views, the engine computes the measure separately on the base and
current slice unless the view disables comparison. It then derives:

- `<measure>_base`
- `<measure>_current`
- `<measure>_delta` = current minus base
- `<measure>_delta_pct` = delta / absolute base × 100, or `null` when base is
  zero.

For `compare: false`, the engine emits the unsuffixed measure value. It uses
the selected base/current slice when `slice` explicitly names one; otherwise
it calculates over the supplied grouped frame after applying the measure
filter.

**Financial guidance:** use `sum` for reconciling monetary movement. `count`,
`nunique`, `mean`, `min`, and `max` are useful supplementary measures, but
they are not additive driver amounts. The selected driver measure must be a
`sum`, or the run stops before presenting misleading transaction evidence.

All `sum` measures convert values to `Decimal`, sum exactly, and round half-up
to cents at the output boundary. `count`/`nunique` count non-null/unique values.
`mean`, `min`, and `max` are calculated separately and should not be expected
to reconcile like financial sums.

### 6.2 Views

```json
{
  "name": "by_department",
  "keys": ["Department"],
  "measures": ["amount", "headcount", "cost_per_head"],
  "compare": true,
  "joins": []
}
```

Required: `name` string, `keys` string array, `measures` string array.
Optional: `compare` boolean (defaults to comparison behavior) and `joins`
array. `keys: []` produces one total row. Key values are stringified; missing
group keys are retained as `(empty)`. A view must reference existing measures
and columns.

Grouped comparisons are full-outer in effect: all groups in the source are
retained, with base/current aggregations reflecting each slice. New and
removed group members therefore appear with a zero on one side rather than
being omitted.

You may define several views for distinct levels of analysis: for example,
department summary, account-by-country variance, and a separate PO evidence
view. `drivers.view` selects which compared view drives the headline driver
waterfall; every view remains available in the result/export.

### 6.3 Lookup joins

Joins add summary fields to a view without multiplying its rows:

```json
{
  "lookup": "open_po",
  "left_on": "Base_PO",
  "right_on": "PO Num",
  "fields": {
    "in_open_po": {"type": "exists"},
    "gao_booked": {
      "type": "exists_where",
      "filter": [{"col": "GAO Comment", "op": "startswith", "val": "GAO"}]
    },
    "vendor": {"type": "value", "col": "Vendor", "filter": []}
  }
}
```

- `lookup` is the short name of an uploaded and defined lookup source.
- `left_on` is the grouped view key; `right_on` is the lookup key.
- `fields` maps new output field names to a field definition.
- `exists`: adds a Boolean indicating whether the key occurs in the filtered
  lookup.
- `exists_where`: adds a Boolean indicating whether the key occurs in lookup
  rows meeting the filter.
- `value`: adds the selected lookup field value. The filtered lookup key must
  be unique; duplicate lookup keys cause an explicit error.
- `filter` is optional and uses the standard filter grammar.

Each join needs the lookup file to be defined and loaded. Missing lookups or
columns fail explicitly. Use `exists`/`exists_where` if a lookup has multiple
rows per key; do not select an arbitrary duplicate value. The JSON schema
allows join objects to be defined openly; the shapes above describe the
implemented execution paths.

### 6.4 Sections

```json
{
  "split_by": "Department",
  "order": ["Operations", "Technology", "Other"],
  "must_reconcile_to": "amount"
}
```

`sections` may be an object or `null`. At run time:

- `split_by` is the existing source/derived column used for the section
  grouping.
- `must_reconcile_to` optionally names a configured sum measure. If omitted,
  the selected driver measure is used.
- `order` optionally gives preferred display order; unspecified labels follow
  afterward.
- Python calculates each section's base/current/delta and checks the
  aggregate section delta against the total, within the
  `sections_reconcile` control tolerance (default **0.01**).

Sections must form an exhaustive, non-overlapping grouping. A non-reconciling
split is not a presentation preference; it is a data/rule issue.

### 6.5 Volume/rate decomposition

```json
{
  "volume": "Headcount",
  "rate": "Cost_per_head",
  "method": "volume_at_base_rate",
  "measure": "amount",
  "view": "by_department"
}
```

Only `method: "volume_at_base_rate"` is implemented. `volume` and `rate`
refer to measures with `<name>_base`/`<name>_current` results in the view.
`measure` is the additive value measure whose delta is explained and defaults
to `amount`; its `<measure>_delta` must be present. `view` is optional; when
provided, decomposition applies only to that view; when omitted it applies to
each compared view and therefore all required measure columns must be
present.

For each group:

```text
volume_impact = (current_volume - base_volume) × base_rate
rate_impact   = total_amount_delta - volume_impact
```

The residual rate impact is calculated to reconcile exactly to the total
delta. Do not substitute a symmetric, current-rate, or multi-factor
decomposition; it is not implemented. Confirm units and whether a rate is
per-person, per-month, or another basis before using this method.

---

## 7. Flags, gates, drivers, drill, and controls

### 7.1 Flags

```json
{
  "view": "by_department",
  "name": "Variance_Status",
  "ordered": [
    {"if": "amount_base == 0 and amount_current != 0", "label": "New"},
    {"if": "abs(amount_delta) > 5000", "label": "Material"}
  ],
  "default": "Within threshold"
}
```

Each flag requires a view name, output `name`, and ordered array of
`{"if": "safe expression", "label": "text"}`. Optional `default` is
`Unclassified` if not supplied. First match wins; every output row receives
exactly one label. The engine calculates label counts and checks that counts
sum to the view row count. Expression rules use Section 5.2.

Flags belong to a named view and can reference its output fields, including
measure comparison suffixes, added lookup fields, or decomposition fields
when available. Never reference a field that this view does not produce.

### 7.2 Gates

```json
{
  "view": "by_department",
  "name": "Material exceptions",
  "if": "gao_booked and amount_delta < -5000"
}
```

Gates require `view`, `name`, and safe expression `if`. They do not change the
underlying variance table; they select rows into the result's `exceptions`
output. They can refer to fields present in that view after joins/flags.
Gates are not auto-approval decisions or additional calculated measures.

### 7.3 Drivers

```json
{
  "view": "by_department",
  "measure": "amount",
  "materiality_abs": 300000,
  "top_n": 15,
  "others_label": "Other items"
}
```

| Property | Rule |
| --- | --- |
| `view` | A compared view; defaults to the first configured view. |
| `measure` | A measure included in that view; defaults to the first spec measure. Must aggregate with `sum`. |
| `materiality_abs` | Non-negative absolute delta threshold. A row is eligible when `abs(delta) >= threshold`. |
| `top_n` | Integer from 1 to 100; default 15. Applied after materiality eligibility, ranked by absolute movement. |
| `others_label` | Remainder label; default `Other items`. |

Selected drivers plus a single `others` row must equal the overall delta. The
remainder includes both below-materiality rows and eligible rows beyond top N.
Negative deltas retain their sign. If every row is selected, there may be no
remainder row.

### 7.4 Drill evidence

```json
{"group_by": ["Description"], "top_n": 5}
```

`group_by` is a source column name or string array. `top_n` is an integer from
1 to 100 (default 5). Python groups source rows by these text fields within
each driver, calculates base/current/delta and line count, orders by absolute
delta, and adds a `Remaining transactions` aggregate when more than top N
text groups exist. The drill rows reconcile to the additive sum driver.

This is consolidated evidence, not an explanation of business cause. It is
retained locally; the agent gets at most five top-text summaries per driver
only when a commentary proposal is requested.

### 7.5 Control registry

A control has the schema:

```json
{
  "id": "new_or_removed_members",
  "severity": "warn",
  "tolerance": 0.01,
  "params": {}
}
```

Only `id` and `severity` are required. `severity` is `stop` or `warn`.
Optional `tolerance` is a non-negative numeric threshold; optional `params`
is a JSON object. Unsupported IDs are explicit errors.

Available registry controls:

| ID | Timing | Behavior / options |
| --- | --- | --- |
| `required_columns` | Pre-run, mandatory stop | Confirms mapped and referenced columns exist and a value role is mapped. Missing source/derived columns stop the run. |
| `periods_present` | Pre-run, mandatory stop | Requires both comparison slices to contain rows and selected months to be covered. |
| `no_duplicate_periods_across_files` | Pre-run, mandatory stop | When periods and stacked-source tracking are available, stops when a month/scenario is present in more than one stacked source. |
| `debit_minus_credit_equals_value` | Pre-run, optional | Row-by-row check of debit minus credit against the value role. `params.debit`/`params.credit` override mapped role columns. Default severity is `warn`; `tolerance` defaults to 0.01. |
| `new_or_removed_members` | Pre-run, optional | Warns or stops on dimension members present in only one slice. |
| `drivers_reconcile` | Post-run, mandatory stop | Drivers including remainder equal total delta exactly. |
| `sections_reconcile` | Post-run, mandatory stop | Section delta sum matches total within `tolerance` (default 0.01). With no sections it passes. |
| `flags_sum_to_rows` | Post-run, mandatory stop | Every flagged view's counts equal the view's row count. |

The pre-run safety controls are always installed with `severity: stop`.
Post-run reconciliation controls also always run and stop release on failure.
Specifying a lower severity for these mandatory checks does not downgrade
them. All extra registered controls run at the configured severity. A warning
is carried into results; a stop blocks output. `controls` does not turn a
failed calculation into a passing one.

---

## 8. Calculation and result lifecycle

### 8.1 Preparation

Python validates the full spec; runs derived transforms in order; applies
scope; rejects an empty dataset; parses periods; resolves slices; expands
quarters; resolves tokens; and normalizes period measure filters.

### 8.2 Pre-run checks

Mandatory controls verify required fields, period availability, and duplicate
stacked period coverage. User-selected controls such as debit-minus-credit or
member movement are also run. A stop prevents calculation.

### 8.3 View execution

For each view, Python verifies requested measure names, groups rows, calculates
base/current/non-compared values, performs configured lookup joins, adds
decomposition, applies ordered flags, and selects gate exceptions.

### 8.4 Drivers and drill

The driver selection must be additive (`sum`). Python ranks group deltas,
applies materiality and top-N limits, constructs the reconciled remainder,
and calculates consolidated drill evidence from local source data.

### 8.5 Post-run checks

Drivers, sections, and flag counts are reconciled. A post-run stop withholds
the output. A successful run persists the result, FluxSpec, and Excel pack
locally.

### 8.6 Commentary

Every run starts with deterministic evidence text and a `[TO VERIFY]` marker.
AI commentary is a separate, optional proposal from the evidence pack. It is
validated; it does not recalculate the result. An analyst can edit commentary,
but manual edits are explicitly marked unverified.

### 8.7 Outputs

- Results: total base/current/delta/percentage, charts, views, drivers,
  exceptions, section splits, controls, drill access, commentary.
- Excel workbook: `Summary`, one `Variance_<view>` sheet per view, `Drivers`,
  `Drill_Evidence`, and when populated, `Flags`, `Exceptions`, `Sections`;
  always includes `Controls` and the full `FluxSpec`.
- Word document: the result heading and analyst-saved commentary.
- FluxSpec JSON: reusable declarative configuration that can be saved,
  loaded, imported, remapped, and audited.
- Result JSON endpoint omits full drill/evidence by default; drill evidence is
  requested separately for a selected driver.

Excel string cells beginning with formula trigger characters are escaped
before writing, protecting against formula injection from source labels or
edited text.

---

## 9. Agent authoring instructions (adapt as the system prompt)

Use the following as the foundation for an Equinix AI Engine system
instruction. Add the organization's *approved* policy and worked examples;
do not expand the application's implemented JSON contract without updating
its schema and tests.

> You are the configuration and evidence-commentary assistant for Flux
> Analyzer. The request is a JSON envelope with `request_id`, `step`, `skill`,
> `user_message`, `spec_so_far`, and `payload`. Read the named step and obey
> its proposal schema.
>
> Return exactly one JSON object with `request_id`, `step`, `status`,
> `proposal`, `confidence`, `rationale`, `questions`, and `warnings`. Echo the
> original `request_id`. Use only statuses `ok`, `needs_input`, or `cannot_do`;
> use only confidence values `high`, `medium`, or `low`. Keep `rationale` to
> 600 characters or fewer. Return valid JSON without prose or extra fields.
>
> Return the step-specific proposal directly in `proposal`; do not add
> Markdown, do not put the proposal under another `proposal`, and do not
> invent schema properties. On `repair`, return a proposal for the original
> expected step named in `payload.expected_step`, echoing
> `payload.original_request_id`.
>
> You are advisory. Never claim you calculated or verified a total.
> Never send, request, or return credentials. Never ask for raw transactions.
> Use only the bounded, aggregated metadata/evidence in `payload`, the
> analyst's explicit context, and the current `spec_so_far`. Never invent
> column names, period coverage, classifications, source contents, or business
> causes. If evidence is ambiguous, return `needs_input`, explain the
> ambiguity, and ask a short, specific question with plausible options.
>
> Preserve previously accepted settings unless the analyst explicitly asks
> to change them. Suggest only columns actually present in the metadata.
> Keep rules declarative and within the supported FluxSpec v1.0 operators,
> aggregations, transforms, joins, controls, and expression language.
> Prefer additive sum measures for reconciled financial drivers. Include
> appropriate mandatory control configurations, knowing Python runs mandatory
> safety and reconciliation checks regardless of requested severity.
>
> During `write_commentary`, use only the supplied `evidence_pack`. Do not
> make up a cause, unit, amount, percentage, period, or count. Return exactly
> one ordered `lines` entry for each evidence driver, copy that driver's
> `delta_fmt` exactly and with its sign, and retain `[TO VERIFY]` when the
> cause is not supported. Avoid forbidden terms. Treat all commentary as a
> proposal, not a verified calculation.

### Suggested behavior by step

| Step | Agent should | Agent must not |
| --- | --- | --- |
| `detect_flux` | Select the best supported skill/name; state uncertainty; identify desired sources as advisory. | Claim to have inspected file contents not in payload; configure an upload. |
| `map_columns` | Map only observed columns; preserve accepted role choices; identify ambiguity. | Invent columns or map text/code IDs as amounts without evidence. |
| `define_comparison` | Select periods/scenarios shown in payload and user instruction; identify gaps; define base and current explicitly. | Claim period coverage from an agent guess; compare disjoint scenarios without a mapped scenario role. |
| `derive_columns` | Propose transparent filters and ordered transformations with defaults; separate scope from slice/measure filtering. | Add unsupported transformation types or treat keyword match as verified finance classification. |
| `classify_terms` | Map only aggregated terms; use specific literal keyword rules before broad rules. | Infer all unmatched items, return transaction rows, or assert a cause from description alone. |
| `define_rules` | Propose complete measures, views, references, driver, controls, and optional analysis that validate together. | Use unsupported aggregates, non-additive driver totals, arbitrary code, or references to absent fields. |
| `write_commentary` | Summarize only supplied checked facts and identify unverified cause. | Change signs/amounts, add unsupplied metrics or explanations as facts, or claim financial review is complete. |

---

## 10. Full working examples

The files in `examples/` are the canonical complete examples. Load them rather
than copying a shortened snippet when testing:

- [`examples/rm_qoq.json`](examples/rm_qoq.json) — R&M-style quarter
  comparison, account scope, ordered accrual bucket, PO regex extraction,
  slice-filtered measures, primary variance view, lookup existence tests,
  flags, gate, driver thresholds, review controls.
- [`examples/benefits.json`](examples/benefits.json) — Actual vs Forecast,
  department view, row-level cost-per-head ratio, supplementary measures, and
  volume-at-base-rate decomposition.

These examples demonstrate *configuration mechanics*, not approved financial
policy. Confirm their source columns, account logic, signs, tolerance,
materiality, lookup uniqueness, periods, and wording against the real process
before use. The agent should use only policy/instructions the organization has
actually approved.

### Example complete response: `define_comparison`

```json
{
  "request_id": "request-id-from-input",
  "step": "define_comparison",
  "status": "ok",
  "proposal": {
    "comparison": {
      "type": "Actual vs Forecast",
      "base": {"months": ["2026-01"], "scenario": "Forecast"},
      "current": {"months": ["2026-01"], "scenario": "Actual"}
    },
    "period_format": "YYYY-MM",
    "partial_periods": []
  },
  "confidence": "high",
  "rationale": "The payload shows both scenarios for January 2026, matching the requested comparison.",
  "questions": [],
  "warnings": []
}
```

### Example complete response: `define_rules`

```json
{
  "request_id": "request-id-from-input",
  "step": "define_rules",
  "status": "ok",
  "proposal": {
    "measures": {
      "amount": {"agg": "sum", "col": "{roles.value}", "slice": "none"}
    },
    "views": [
      {
        "name": "by_department",
        "keys": ["Department"],
        "measures": ["amount"],
        "compare": true
      }
    ],
    "sections": null,
    "decompose": null,
    "flags": [],
    "gates": [],
    "drivers": {
      "view": "by_department",
      "measure": "amount",
      "materiality_abs": 0,
      "top_n": 15,
      "others_label": "Other items"
    },
    "drill": {"group_by": ["Description"], "top_n": 5},
    "commentary": {
      "units": "K",
      "decimals": 1,
      "style": "largest_first",
      "verify_tag": "[TO VERIFY]"
    },
    "controls": [
      {"id": "required_columns", "severity": "stop"},
      {"id": "periods_present", "severity": "stop"},
      {"id": "no_duplicate_periods_across_files", "severity": "stop"},
      {"id": "drivers_reconcile", "severity": "stop"},
      {"id": "sections_reconcile", "severity": "stop", "tolerance": 0.01},
      {"id": "flags_sum_to_rows", "severity": "stop"}
    ]
  },
  "confidence": "medium",
  "rationale": "This uses a department sum for additive drivers and preserves deterministic reconciliation checks.",
  "questions": [],
  "warnings": ["Confirm the reporting materiality threshold with Finance."]
}
```

### Example complete response: `write_commentary`

```json
{
  "request_id": "request-id-from-input",
  "step": "write_commentary",
  "status": "ok",
  "proposal": {
    "headline": "Current-period cost is higher than base.",
    "lines": [
      {
        "driver_id": "d1",
        "text": "Operations increased by +$900.00. [TO VERIFY] Confirm the underlying business cause."
      }
    ],
    "others_summary": ""
  },
  "confidence": "medium",
  "rationale": "The line preserves the exact signed evidence amount. The business cause is not established by the evidence.",
  "questions": [],
  "warnings": ["The cause is analyst-verification text, not a confirmed explanation."]
}
```

The complete response must still pass numeric-claim validation against the
actual run. These illustrative values are not to be copied into a real result.

---

## 11. Common invalid responses and their correction

| Invalid pattern | Why it fails | Correct approach |
| --- | --- | --- |
| `{"answer":"..."}` instead of the full envelope | Missing required response fields. | Return the complete envelope. |
| `"confidence": 0.87` | Only `high`, `medium`, `low` are allowed. | Use the closest supported enum and explain uncertainty in `rationale`. |
| `"step": "compare"` | Wrong protocol step. | Echo the exact requested step. |
| `"roles": {"amount":"Cost"}` | Unknown role key. | Use `roles.value`. |
| A column name not present in profile/headers | The engine cannot validate the mapping. | Ask the user or choose a present, supported column. |
| `"agg": "variance"` | Unsupported aggregation. | Configure supported aggregations or use a tested derived measure/expression. |
| `"operator": "matches"` | Filter property is `op`; operator is not supported. | Use `{"col": "...", "op": "regex", "val": "..."}`. |
| `{"type":"python","code":"..."}` | No code transform exists and arbitrary code is unsafe. | Express the rule using the documented declarative transform or safe expression. |
| `{"type":"join"}` in `derive` | Unsupported derived type. | Put a supported lookup join on a view. |
| Driver on a `mean` or ratio | Driver reconciliation requires additive sums. | Select a sum amount measure for drivers; show ratio as a supplementary measure. |
| Regex classification with a broad rule first | First match wins, so it consumes more specific matches. | Order narrow/specific rules first. |
| A commentary line with an alternate rounded amount/sign | The evidence checker requires the exact Python `delta_fmt`. | Copy the exact formatted token, including sign. |
| A commentary explanation such as "due to restructuring" without evidence | The evidence pack does not prove cause. | State the observed movement and retain `[TO VERIFY]`. |
| More than 50 KiB of serialized request | The client rejects it even after bounded metadata trimming. | Reduce rule/spec complexity or make a manual change. |

---

## 12. Versioning and maintenance

If the supported configuration or agent contract changes:

1. Update the FluxSpec schema in `engine/spec.py`.
2. Update the JSON response schemas in `agent/schemas/responses.json`.
3. Update the engine implementation and this guide together.
4. Add/update tests for every new accepted value and its rejection case.
5. Add a portable JSON example when a new domain pattern is introduced; keep
   domain-specific policy in data/specs and approved agent instructions, not
   Python branches.
6. Validate that the Equinix agent response still matches the exact envelope,
   step, request ID, and full FluxSpec.

The single source of truth for the current implemented agent response
properties is the machine-readable response schema. The source of truth for
what a requested computation actually does is the Python engine plus its
tests. Where this guide and runtime disagree, report/update the guide rather
than teaching the agent to rely on unsupported behavior.

---

## 13. Data-handling and deployment note

This build is a local, single-operator finance workbench, not an authenticated
multi-user corporate service. It uses local files and process-local
background jobs. Do not deploy it with real financial data until corporate
authentication, approved durable storage, access boundaries, retention
policies, and a security review have been added. Live Equinix API access also
requires approved credentials and network access; it has not been verified
without them.
