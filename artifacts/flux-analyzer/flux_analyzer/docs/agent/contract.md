# Flux Analyzer Agent Contract

**Contract `journey-1` — implemented by this version of Flux Analyzer.** Validators, response schemas, request builders and the offline mock all follow it.

Planning companion to the conversational redesign. Change validators, response schemas, builders, adapters, mocks and instructions together.

## Shared request
Exactly:
```json
{"contract_version":"journey-1","request_id":"opaque-unique-id","step":"apply_instruction","user_message":"Show the top 15 movements.","spec_so_far":{},"payload":{}}
```
The empty spec/payload above are structural placeholders. Actual spec_so_far is complete, validated FluxSpec. Every call includes it, including repair. Retain FluxSpec 2.0 with optional style-profile extension and schema migration/default compatibility; old binaries do not accept the new field. The agent contract ID is separate from FluxSpec version.

Steps: detect_flux, map_columns, define_comparison, derive_columns, classify_terms, define_rules, apply_instruction, explain_spec, answer_question, plan_from_description, extract_commentary_style, write_commentary, describe_setup, repair.

### Shared payload fields
- response_schema: complete JSON Schema for this step's response envelope, including the exact nested engine grammar.
- preset: application-produced current preset ID/version/guidance/defaults/hard constraints; {} when none.
- context: exactly `{spec_revision:integer>=0, source_profile_id:string, run_id:string|null, ui_step:Stage, mode:"simple"|"advanced", locale:string}`.
- allowed_patch_paths: string array of permitted JSON Pointer prefixes; empty for read-only calls.
- allowed_columns: string array including validated available derived/joined columns.
- available_months: canonical sorted YYYY-MM array.
- Optional truncated:true when optional metadata was trimmed.

Stage: upload|path|data|compare|include|group|important|explain|review|results|save.

### Metadata types
- ColumnProfile: `{name:string,dtype:string,null_count:integer>=0,distinct_count:integer>=0,samples:string[]}`. Samples are bounded/redacted distinct labels, not records.
- FileProfile: `{source_id:string,name:string,columns:ColumnProfile[],row_count:integer>=0,months:string[],source_guess:string|null}`.
- PresetSummary: `{id:string,version:string,name:string,description:string}`; normalize the existing list output in the adapter.
- ValueCount: `{values:object<string,string|null>,count:integer>=0,amount_fmt:string|null}`.
- PeriodWarning: `{month:string,reason:string,row_count:integer>=0}`.
- RuleDescription: `{id:string,sentence:string}`.

No raw transaction rows, uploaded files, credentials, internal file-system paths or unnecessary personal identifiers. Grouped labels can still be sensitive; redact them.

## Shared response
Exactly these required fields:
```json
{
  "contract_version":"journey-1",
  "request_id":"opaque-unique-id",
  "step":"apply_instruction",
  "status":"ok",
  "proposal":{"patch":[{"op":"replace","path":"/drivers/top_n","value":15}]},
  "confidence":"high",
  "rationale":"You requested fifteen movements.",
  "questions":[],
  "warnings":[],
  "summary":"The report will show fifteen top movements.",
  "changes":[{"setting":"Top movements","from":"Ten","to":"Fifteen","reason":"Your instruction"}]
}
```
- No unknown keys or top-level patch.
- status: ok|needs_input|cannot_do. confidence: high|medium|low; never an approval bypass.
- rationale: string, max 600 characters; summary: nonempty string, max 1000.
- changes: max 30 objects, exactly setting/from/to/reason, all strings. Server produces the authoritative change notice from the actual diff.
- warnings: max 10 plain-language strings, each max 500 characters.
- questions: max 3 objects, exactly `{id:string,text:string,options:string[]}`. Text max 240 characters; two or three options, each max 240, each a self-contained instruction.
- ok has no unresolved questions. needs_input has at least one question and may omit normally required proposal fields; present fields retain their strict types.
- cannot_do has proposal:{}, changes:[], questions:[], confidence:"low", with a useful manual next step.
- Summary/rationale/questions are plain finance language; no exposed tokens or technical control IDs in Simple-mode prose.

## Validation and application
Validate one JSON object → version/ID/step/envelope → step proposal → ownership/paths/protected fields → merged candidate schema/semantics → data/preset/evidence references → narrative/style checks → current revision/profile/run → atomic persistence and audit.

Aggregate all discoverable validation errors into one repair attempt. A second invalid answer means manual fallback, no mutation. HTTP/auth/timeouts are operational failures, not reasons for repeated semantic repair.

Safe validated configuration proposals auto-apply with summary, Change and Undo. Valid independent partial proposals in needs_input may apply atomically; unresolved values remain unchanged. Never apply just the valid subset of an otherwise invalid patch. Empty patch is a no-op.

Capture revision/profile/run when starting a request. Ignore obsolete results server-side. Undo uses stored valid history, not an AI inverse patch. Changes mark dependent results stale.

### Patch shape and protected fields
Patch is an array of objects with only op/path/value. op: add|replace|remove|test. add/replace/test require value; remove forbids value. Paths use RFC6901 escaping and match allowlist boundaries.

No root replacement, move/copy, code, file references, credentials or protected changes. Protected: sources/file bindings, spec_version, run_stamp, history, jobs and human confirmations. Preset selection uses detect_flux and an existing ID; server resolves the actual preset. Mandatory checks cannot be removed; other destructive resets need explicit intent.

Existing step-shaped proposals are converted into candidates, diffed and applied through the existing audited patch path. Do not treat all old proposals as patches.

### Engine configuration grammar
Full nested grammar is the actual `engine/spec.py` schema plus semantic validation, supplied in response_schema. This is authoritative rather than an LLM-generated alternate schema.
- Roles: value/period/scenario/debit/credit string|null; keys/dimensions/driver_text string[].
- Comparison: `{type:string,base:Slice,current:Slice}`. Slices have explicit months, optional scenario/filters. Returned months must be available YYYY-MM.
- Filter: `{col:string,op:eq|ne|in|not_in|gt|gte|lt|lte|startswith|contains|regex|isnull|notnull,val?:any}` with data/type checks.
- Join: canonical source/on/columns/prefix/key_normalise/dedupe_right; supported left-join semantics only.
- Classification: canonical target_col/source_cols/rules, deliberate first-match order; generated rules reviewed:false.
- Materiality percentages are fractions: .05 means 5%.
- Ordinary compared measures omit slice; slice:none deliberately bypasses the comparison.
- User-requested numeric configuration values are permitted; model-calculated financial results are not.

## Per-step contracts
All payload fields below are additional to shared fields. All proposal fields are exact, with optional fields marked ?. Unknown fields fail. Examples show proposal fragments only, wrapped in the complete response above with the matching step. Examples depend on actually supplied columns, values, presets and references and never authorize resetting existing settings.

### detect_flux
When: uploaded-source/preset suggestion.
Payload: headers:string[], user_text:string, available_presets:PresetSummary[].
Proposal: `{preset_id:string,flux_name:string,required_sources?:string[],optional_sources?:string[]}`.
Example:
```json
{"preset_id":"generic","flux_name":"Country movements","required_sources":["Main data"],"optional_sources":[]}
```
Validate preset exists and name/source labels are permitted. Server resolves defaults; preserve reviewed settings unless an explicit reset was requested. Auto-apply valid candidate.

### map_columns
When: Data step or remapping new files.
Payload: profile:ColumnProfile[], previous_roles:Roles, source_profiles:FileProfile[].
Proposal: `{roles:Roles,unmapped?:string[]}`.
Example:
```json
{"roles":{"value":"Amount","period":"Month","dimensions":["Country"],"driver_text":["Description"]},"unmapped":[]}
```
Validate existing columns/types and unique matching; preserve unrelated roles. Auto-apply supported unique mappings; ask for ambiguity.

### define_comparison
When: Compare.
Payload: period_values:string[], today:ISO-date string, monthly_row_counts:object<string,integer>, partial_period_candidates:PeriodWarning[], scenario_values:string[].
Proposal: `{comparison:Comparison,period_format?:string,partial_periods?:string[]}`.
Example, only with all months available:
```json
{"comparison":{"type":"period_vs_period","base":{"months":["2026-01","2026-02","2026-03"]},"current":{"months":["2026-04","2026-05","2026-06"]}}}
```
Validate calendar, scenarios, available months, explicit overlap and format. Low row count is a warning, not automatic exclusion. Auto-apply valid resolved choice; otherwise ask.

### derive_columns
When: Include/Group needs supported scope, derivation, join or value rule.
Payload: value_counts:ValueCount[], roles:Roles, source_profiles:FileProfile[], supported_derive_types:string[], supported_expression_hint:string.
Proposal: `{scope:Filter[],derive:Derive[],joins?:Join[],value_rules?:ValueRules}`.
Example when no existing derivations need preserving:
```json
{"scope":[{"col":"Region","op":"eq","val":"EMEA"}],"derive":[]}
```
Validate engine grammar/data, permitted sources/keys and no fan-out bypass. Preserve unrelated configuration. Auto-apply valid candidate.

### classify_terms
When: Group categorisation.
Payload: allowed_categories:string[], terms:Term[], existing_classification:Classification|null.
Term: `{text:string,abs_value:number,n:integer>=0}`; values are computed evidence, not permission for model arithmetic.
Proposal: `{mappings?:Mapping[],rules?:ClassificationRule[],target_col?:string,source_col?:string}`.
Mapping: `{term:string,category:string,keyword_rule:string}`.
ClassificationRule: `{keyword:string,category:string,match:"contains"|"eq"|"startswith"|"regex",reviewed:boolean}`.
Example:
```json
{"rules":[{"keyword":"maintenance","category":"Maintenance","match":"contains","reviewed":false}],"target_col":"Category","source_col":"Description"}
```
Validate category permissions, source/target, safe patterns/order, preserve reviewed rules. Adapter converts source_col into canonical source_cols. New rules stay unreviewed even if auto-applied.

### define_rules
When: Important or advanced report/rule settings.
Payload: rule_descriptions:RuleDescription[], supported_expression_hint:string.
Proposal required: measures:Measures, views:View[], drivers:Drivers, controls:Control[].
Optional: sections,decompose,flags,gates,drill,commentary,value_rules,joins,classification, all actual engine types.
Example shape, only if these are the intended complete replacements and additional required controls are preserved:
```json
{"measures":{"amount":{"agg":"sum","col":"Amount"}},"views":[{"name":"By country","keys":["Country"],"measures":["amount"],"compare":true}],"drivers":{"view":"By country","measure":"amount","materiality_abs":300000,"top_n":15,"others_label":"Other"},"controls":[{"id":"required_columns","severity":"stop"},{"id":"drivers_reconcile","severity":"stop"}]}
```
Validate references, materiality policy, expressions and mandatory controls. Do not invent currencies/policies or reset unrelated measures. Auto-apply valid candidate.

### apply_instruction
When: change box or question option.
Payload: instruction:string max3000, target_step:data|compare|include|group|important|explain, rule_descriptions:RuleDescription[].
Proposal: `{patch:Patch[]}` only.
Example:
```json
{"patch":[{"op":"replace","path":"/drivers/top_n","value":15}]}
```
Validate allowed paths/ownership/intent/current candidate. Auto-apply valid patch; read-only questions must not mutate.

### explain_spec
When: setting explanation/contextual help.
Payload: target:string max500, rule_descriptions:RuleDescription[].
Proposal: `{sentences:string[]}`.
Example:
```json
{"sentences":["The report groups movements by country.","The threshold determines which movements need explaining."]}
```
Validate against actual settings. Read-only.

### answer_question
When: Ask about results.
Payload: question:string max1000, evidence_pack:EvidencePack|null, rule_descriptions:RuleDescription[].
Proposal: `{answer:string,evidence_refs:string[]}`.
Example:
```json
{"answer":"Germany includes maintenance-related descriptions. The business cause still needs confirmation.","evidence_refs":["driver:DE","text:DE:maintenance"]}
```
Validate evidence references and numeric tokens; no causality invented. Null evidence permits setup explanations only. Read-only; no patches.

### plan_from_description
When: Describe your flux.
Payload: description:string max3000, file_profiles:FileProfile[], value_counts:ValueCount[], available_presets:PresetSummary[], existing_step_state:object.
Proposal: `{patch:Patch[],step_states:StepState[]}`.
StepState exactly `{step:data|compare|include|group|important|explain,status:"confident"|"needs_input",summary:string,reason:string,question_ids:string[]}`.
Exactly one entry per step in that order. Question IDs reference envelope questions. Confident has no unresolved questions. Ask at most three earliest blockers; later unresolved steps may have no question yet.
Example with existing mapped data/grouping/style but unresolved comparison:
```json
{"patch":[{"op":"replace","path":"/drivers/top_n","value":15}],"step_states":[{"step":"data","status":"confident","summary":"The columns are mapped.","reason":"The current setup already maps them.","question_ids":[]},{"step":"compare","status":"needs_input","summary":"Choose periods.","reason":"No periods were specified.","question_ids":["periods"]},{"step":"include","status":"confident","summary":"Include all main data.","reason":"No narrower scope was requested.","question_ids":[]},{"step":"group","status":"confident","summary":"Group by country.","reason":"The current setup uses Country.","question_ids":[]},{"step":"important","status":"confident","summary":"Show fifteen movements.","reason":"Your instruction.","question_ids":[]},{"step":"explain","status":"confident","summary":"Use neutral controller commentary.","reason":"The current setup specifies this.","question_ids":[]}]}
```
For this example use envelope status needs_input and:
```json
{"id":"periods","text":"Which periods should we compare?","options":["Compare Q2 2026 with Q1 2026.","Compare June 2026 with May 2026."]}
```
Options require those months/calendar to be supplied. Validate patch and step/question consistency. Apply valid patch; server recomputes readiness and routes to first actual blocker or Review. Never run analysis or write commentary.

### extract_commentary_style
When: explicit submission of pasted commentary.
Payload: example_text:string max6000, current_style_profile:StyleProfile|null, style_constraints:object with allowed audience/length/tone and forbidden terms.
Proposal: `{example_style:ExampleStyle}`.
ExampleStyle exactly `{summary_of_style:string max600,sample_phrases:string[] max5}`; each phrase max120.
Example:
```json
{"example_style":{"summary_of_style":"Short neutral bullets, one movement per line.","sample_phrases":["The movement relates to [supported evidence]."]}}
```
Validate no copied historical amounts/dates/entities/periods/claims. Prefer abstraction/empty phrases when uncertain. Adapter patches only style_profile.example_style after safety validation; preserve other fields. Do not persist or later forward raw example text in setups/logs/exports.

### write_commentary
When: initial generation, selected lines or refinement.
Payload: evidence_pack:EvidencePack, commentary_rules:CommentarySettings, writing_guidance:WritingGuidance, evidence_guide:{string:string}; optional instruction:string max1000.

WritingGuidance: `{audience,length,tone,structure,objective,instructions,include,example_style: {value, source:"user"|"preset"|"default"}, preset_name:string}`. A field is "preset" when it equals the chosen preset's default, "user" when a person changed it, otherwise "default".

EvidencePack retains flux_name/drivers/sections/commentary_rules/headline_hint and adds totals, comparison, description_columns, materiality_policy, allowed_evidence_refs:string[], allowed_numeric_tokens:string[], coverage_notes:string[], data_quality:object[], business_context:BusinessContext[], writing_guidance. Business context and writing guidance are stored with the run, so later checks of the same run accept context references.
BusinessContext: `{id:"context:user:N"|"context:preset:N",evidence_ref:string,text:string<=300,source:"user"|"preset",verified:false,note:string}`, at most 8, one per line of the Explain step's "What do you already know?".

Driver evidence retains driver_id,label,dimensions,base,current,delta,delta_fmt,top_texts,n_lines,flags_summary and adds base_fmt,current_fmt,evidence_refs and, when the engine can build them, trend/decomposition/categories/coverage/flags/is_material. top_texts adds evidence_ref (`text:<driver>:<n>`).

Shapes (all produced by Python; no digits in notes):
- trend: `{comparability:"comparable"|"limited",pattern:"one_period"|"continuing"|"reversal"|"mixed"|"no_movement"|"insufficient_history"|"not_assessed"|"partial_period",points:[{period:string,amount_fmt:string,partial?:true}],note:string,evidence_ref:"trend:<driver>"}`. Up to six consecutive windows of the compared length; a period is YYYY-MM or "YYYY-MM to YYYY-MM". Non-consecutive comparisons are "limited" and "not_assessed". No trend means no trend claims.
- decomposition: `{method:"volume_rate",measure:string,components:[{label:string,delta_fmt:string,evidence_ref:"decomp:<driver>:volume|rate"}],note:string}` — only when the configured decomposition is for the movement's own measure and its effects add up to the movement.
- categories: `{column:string,items:[{category:string,delta_fmt:string,lines:integer,approval:"approved"|"partly_approved"|"not_approved"|"unclassified"|"mixed",evidence_ref:"category:<driver>:<n>"}]}` — top four plus "Other categories".
- coverage: `{source_lines,shown_description_count,truncated,unmatched_lookup_lines,unclassified_lines,partial_periods,note,evidence_ref:"coverage:<driver>"}`.
- flags: `[{rule,label,lines,evidence_ref:"flag:<driver>:<n>"}]`; is_material is decided by the engine (see materiality_policy).
- data_quality entries: `{id:string,severity:"warn"|"stop",scope:string,message:string,evidence_refs:string[]}` with ids `control:*`, `lookup:*`, `classification:unreviewed`, `partial:*`.

References must be in allowed_evidence_refs and belong to the line's driver or be report-wide (total, control, lookup, classification, partial, section, context). Narrative numbers need an exact allowed token; amounts must be a *_fmt of the line's driver or the totals. Missing optional evidence is not zero, complete coverage or proof of no issues. Requests over the size cap shorten history to the latest three points and categories to two before trimming descriptions.

Proposal exactly:
`{headline:string,lines:[{driver_id:string,text:string,support:"supported"|"needs_verification",evidence_refs:string[],claims?:[{type:"observation"|"possible_explanation"|"context",text:string<=300,evidence_refs:string[]}],confirm_prompt?:string<=240}],others_summary:string}`.
Claim rules: an observation cites checked (non-context) evidence and states no cause; a possible_explanation needs the verify tag with support needs_verification unless it only repeats the stated context it cites; a context claim cites and repeats that context. Citing context is not proof: a reason whose words do not come from the cited context still needs the verify tag. confirm_prompt says what the reviewer should check.
Example:
```json
{"headline":"Country movements for review","lines":[{"driver_id":"DE","text":"+$0.4M — Germany includes maintenance-related descriptions. [TO VERIFY] Confirm the business cause.","support":"needs_verification","evidence_refs":["driver:DE","text:DE:maintenance"]}],"others_summary":""}
```
Validate exact target order/coverage and IDs; each line starts with exact delta_fmt; all tokens/references supplied and relevant; configured word/forbidden-term limits; exact headline_hint if provided; no pasted-example facts.

Unsupported causes require verify tag plus needs_verification. An evidence ID's existence does not prove its causal claim. For AI text, trend wording must match trend.pattern and cite it; cause, timing and one-off wording needs the verify tag unless the stated reason only repeats the cited context. Text a person writes is checked for amounts, numbers, references and forbidden terms only. The model never confirms explanations or decides below-threshold.

For selected output preserve supplied headline/others_summary unless separately requested. “Short summary” does not remove required detail lines. Batch without losing coverage.

Save valid AI drafts only for unprotected targets; preview replacements for manual/confirmed text. Invalid output leaves prior valid text intact.

### describe_setup
When: Save form or missing/stale description on load.
Payload: rule_descriptions:RuleDescription[],existing_name:string,existing_description:string,purpose:save|load,allowed_display_tokens:string[].
Proposal: `{suggested_name:string length1..120,description:string length1..1000}`.
Example:
```json
{"suggested_name":"Country controller review","description":"Compare the selected periods by country and prepare neutral commentary for material movements."}
```
Validate faithful settings/allowed display values, no sensitive examples or paths. Fixed months are not “latest quarter” unless a supported policy is supplied. Fill editable defaults only; no automatic file save/overwrite.

### repair
When: invalid original answer, once maximum.
Request step:repair, request_id remains original. Shared fields/spec retained. Additional payload:
`{expected_step:OriginalStep,original_request_id:string,expected_schema:object,original_payload:object,errors:[{path:string,code:string,message:string}],previous_output:string}`.
response_schema/expected_schema describe the original complete response. Preserve relevant original metadata/evidence/preset constraints. previous_output bounded/redacted; never retain raw style example for repair. If sanitized context is insufficient, fall back.
Return the original step's full envelope, not step:repair. Example:
```json
{"contract_version":"journey-1","request_id":"opaque-unique-id","step":"apply_instruction","status":"ok","proposal":{"patch":[{"op":"replace","path":"/drivers/top_n","value":15}]},"confidence":"high","rationale":"The corrected value is an allowed integer.","questions":[],"warnings":[],"summary":"Show fifteen movements.","changes":[{"setting":"Top movements","from":"Ten","to":"Fifteen","reason":"Your instruction"}]}
```
Repeat all checks against immutable original context. One failure after repair means no change and a manual next step.

## Style profile
Optional `commentary.style_profile`; every property required when present, no extras:
```json
{"audience":"controller","length":"medium","structure":{"type":"overall","split_by":null},"tone":"neutral","instructions":"","example_style":{"summary_of_style":"","sample_phrases":[]},"include":["to_verify"]}
```
- audience: executive|controller|detailed|custom.
- length: short|medium|per_driver.
- structure exactly type:overall|split, split_by:string|null. Overall requires null; split requires an available grouping field.
- tone: neutral|risk_focused|fav_unfav; engine settings determine favorable meaning.
- instructions max3000; cannot override evidence/number/business constraints.
- example_style: sanitized ExampleStyle defined above.
- include: unique array drawn from timing|one_offs|to_verify; attention preferences, not permission to invent.
- Old specs without a profile remain valid; preserve legacy commentary behavior until a profile is chosen.

## Explanation status
Server precedence:
1. Nonmaterial by engine → below_threshold.
2. Material with valid explicit human confirmation/edit-save for current run/evidence → confirmed.
3. Material with missing/invalid/verify-tag/unsupported text → needs_explanation.
4. Material with valid supported AI draft → ai_review.

Run-scoped record:
`{run_id,driver_id,evidence_hash,text,status,origin:"ai"|"user",evidence_refs,confirmed_by:string|null,confirmed_at:ISO-string|null,updated_by:string,updated_at:ISO-string}`.
Audit edits/status changes. Display identity in the no-auth MVP is not authenticated identity. New run/evidence invalidates confirmation. Export counts/open-item subsets derive from deterministic materiality and these records, not model claims.

## Operational bounds and coordinated release
Keep the current 50KB request cap. Trim optional samples first; never drop expected schemas, protected constraints or required target drivers. Split/commentary batches and combine in engine order. Bound responses and use redacted audit metadata. Never log credentials or raw pasted examples.

Equinix invoke/poll remains the transport. Gemini 3.5 Flash selection, structured output and temperature support require actual service documentation; no undocumented fields. No live test is required for this plan.

Release together: style spec/schema, contracts.py/client/schema, step builders/proposal adapters/mocks, UI state/jobs, evidence/review/narrative checks, canonical instructions/contract and offline evaluation fixtures. Use a separate development agent or coordinated cutover. Do not point an old binary at these instructions.

## How the application implements this contract

- The application sends `contract_version: "journey-1"` on every request. Responses may include it; when present it must match.
- Every validated configuration change is applied straight away with a summary, a Change link and Undo. A response that arrives after the setup changed (a newer `spec_revision`) is discarded and the user is asked to send the request again.
- Requests aimed at one step (`target_step`) may still change other steps if the user asked for that, but protected paths (`/sources`, `/run_stamp`, removing mandatory controls) are always refused.
- `extract_commentary_style` may only change `/commentary/style_profile/example_style`. Its output is rejected if it repeats names, amounts or dates from the pasted example, and the pasted example is never saved.
- `describe_setup` is a suggestion only; the person decides whether to save it.
- Explanation status is calculated by the application. The model can never confirm an explanation.
- Offline mock mode implements every step deterministically so the full journey can be tested without the AI Engine.
