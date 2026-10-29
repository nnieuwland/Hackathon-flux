# Flux Analyzer frontend contract

This is intentionally a **Flask + Jinja2 + HTMX + Alpine** application, not React. Create `flux_analyzer/web/templates/index.html`, `flux_analyzer/web/static/app.css`, and `flux_analyzer/web/static/app.js` inside this artifact. Main agent owns all Python, requirements, vendor assets and service config. Do not edit those. Local vendor scripts: `/static/vendor/htmx.min.js`, `/static/vendor/alpine.min.js`, `/static/vendor/chart.min.js`, `/static/vendor/tailwind.js`. Load Alpine after app.js (defer both). CSS can be handcrafted, no network/font dependency. All app routes served by Flask at root.

`GET /` and `GET /step/<step>` render `index.html` with `initial` (dict, embed via `{{ initial|tojson }}`), `step` (string). Initial:
```
{
 project_id, agent_mock: true, step:"sources",
 sources:[{id,name,size,sheets:[],defined:false,role:"primary",definition:{sheet,header_row,start_col,end_col,role,name,combine_sheets:[],tag_column},columns:[],n_rows:0}],
 spec:{spec_version:"1.0",flux_name:"Untitled analysis",skill:null,sources:{},roles:{value:null,period:null,scenario:null,keys:[],dimensions:[],driver_text:[]},scope:[],derive:[],periods:{calendar:"calendar"},comparison:{type:"QoQ",base:{months:[]},current:{months:[]}},measures:{},views:[],flags:[],gates:[],drivers:{materiality_abs:300000,top_n:15,others_label:"Other items"},drill:{top_n:5},commentary:{units:"M",decimals:1,verify_tag:"[TO VERIFY]"},controls:[]},
 profile:{n_rows:0,columns:[{name,dtype_guess,pct_empty,n_unique,samples:[]}]},
 periods:[],scenarios:[],saved_specs:[{name,file,updated}],runs:[{id,name,created,status}],latest_proposal:null, controls:[],result:null
}
```
Step slugs: `sources`, `flux`, `columns`, `comparison`, `rules`, `review`, `results`. Navigation can stay client-side and state persists backend. Don't prepopulate fake uploaded files. First screen must be excellent, complete empty state with upload plus an explicit "Try sample data" action (real synthetic fixture backend).

All mutation endpoints accept JSON except upload and return JSON (errors `{error:"friendly"}` with non-2xx). Use fetch, handle errors/loading. No `/api` prefix. Include CSRF header `X-CSRF-Token: initial.csrf_token` on all POST/DELETE requests. Calls return updated state when indicated. No secrets browser-side.

- `GET /state` -> full initial state, rehydrate after mutations.
- `POST /sources/upload` multipart `files` (multiple CSV/XLSX) -> full state.
- `POST /sources/demo` `{}` -> full state; real labeled synthetic R&M general-ledger CSV + Open PO XLSX. Not a fake run.
- `DELETE /sources/<id>` -> full state.
- `GET /sources/<id>/preview?sheet=<urlencoded>&header_row=1&start_col=A&end_col=` -> `{grid:[[]],suggested_header:1,letters:["A",...],sheets:[],parsed:{columns:[],rows:[[]],n_rows:0}}`. Grid raw 25x30; header_row 1-based. Selecting row number/column letters updates parsed preview via refetch. XLSX actual names preserved.
- `POST /sources/<id>/define` `{sheet,header_row:1,start_col:"A",end_col:null,role:"primary"|"lookup"|"forecast",name:"short_name",combine_sheets:[],tag_column:null}` -> full state.
- `POST /config/<agent_step>/suggest` `{user_message:"",skill:null}` -> `{job_id}`; agent steps detect_flux, map_columns, define_comparison, derive_columns, classify_terms, define_rules.
- `GET /jobs/<id>` -> `{id,status:"pending"|"done"|"error",message,result,error}`. Poll every 1500ms, done result is response envelope `{request_id,step,status,proposal,confidence,rationale,questions:[],warnings:[]}` for agent jobs or `{run_id}` for run jobs. Show progress message. Suggestions must stay editable and NOT silently become accepted spec. Display AI suggested tags, confidence/rationale/question chips, errors/warnings. Buttons explicitly accept edited proposal.
- `POST /config/<agent_step>/accept` `{proposal:{...}}` -> full state; merges according to step.
  - detect_flux proposal `{skill,flux_name}`
  - map_columns `{roles:{value,period,scenario,keys:[],dimensions:[],driver_text:[],debit:null,credit:null}}`
  - define_comparison `{comparison:{type,base:{months:[],scenario:null},current:{months:[],scenario:null}},period_format:"MON-YY"}`
  - derive_columns `{scope:[],derive:[]}`
  - classify_terms `{mappings:[],target_col:"Category",source_col:"Description"}`
  - define_rules `{measures:{amount:{agg:"sum",col:"{roles.value}"}},views:[{name:"by_dimension",keys:[],measures:["amount"],compare:true}],sections:null,decompose:null,flags:[],gates:[],drivers:{view:"by_dimension",measure:"amount",materiality_abs:300000,top_n:15,others_label:"Other items"},drill:{group_by:"{roles.driver_text}",top_n:5},commentary:{units:"M",decimals:1,verify_tag:"[TO VERIFY]"},controls:[{id:"required_columns",severity:"stop"},{id:"periods_present",severity:"stop"}]}`
- `POST /config/update` `{spec: <complete edited spec>}` -> full state, JSON schema validated. Use for manual edits and rules JSON editors. Rules accordions need JSON editing for full scope/derive/measures/views/flags/gates plus materiality/units controls. Don't silently discard edits on navigating.
- `POST /config/preview/<section>` `{}` -> `{n_rows,totals:[{value,count,total}],columns:[]}` (section scope or derive).
- `POST /review/controls` `{}` -> `{controls:[{id,status:"pass"|"warn"|"stop",message,details}]}`
- `POST /run` `{}` -> `{job_id}`, async, calculate only after controls pass; poll then `GET /results/<run_id>?format=json` -> result below. GET without format renders index with result.
- `GET /specs` -> `[{name,file,updated}]`
- `POST /specs/save` `{name:"R&M QoQ"}` -> full state.
- `POST /specs/load` `{file:"name.json"}` -> full state plus `missing_columns:[]`; if missing show remap action; no missing -> go review.
- `POST /specs/import` `{spec:<FluxSpec JSON>}` -> full state; expose JSON import control.
- `GET /download/<run_id>/excel` -> XLSX file; `.../spec` -> JSON; `.../docx` -> document. Use normal anchor links.
- `POST /results/<run_id>/commentary` `{text:"user edited commentary"}` -> `{ok:true}`. Editable commentary should show save.
- `POST /results/<run_id>/narrative` `{}` -> `{job_id}`; returns schema-checked commentary suggestions; same approve pattern, then save edited text via commentary endpoint.
- `GET /results/<run_id>/drill/<driver_id>` -> `[{text,base,current,delta,n_lines}]`
- `POST /project/new` `{}` -> full fresh state (confirmation before clearing current browser's project; old project files retained).

Result:
```
{id,name,created,base,current,delta,delta_pct,n_drivers,n_exceptions,
 drivers:[{driver_id,label,dimensions:{},base,current,delta,delta_fmt,n_lines,top_texts:[],flags_summary:{}}],
 views:{view_name:[{key_columns...,amount_base,amount_current,amount_delta,amount_delta_pct,...}]},
 controls:[],exceptions:[],flags:[],sections:[],
 commentary:{text:"...",issues:[],verified:true,mock:true},
 spec:{...},warnings:[]}
```
Amounts numeric from Python, delta_fmt already formatted. Never compute financial totals in JS; chart only plots provided data. Use Chart.js for waterfall style bar (base/current and movement drivers). Table click opens drill drawer. Show totals, exception/controls/variance tabs, editable commentary, downloads. Human readable values formatting is fine.

User-requested visual requirements: Equinix-style neutral white/dark grey with single red #ED1C24 primary accent; light/dark mode. Always-visible left numbered seven-step stepper; right agent panel with rationale, confidence, warnings, questions and context box. Calm and spacious, one primary action per screen. Screen1 upload/dropzone with file cards and source definition modal, raw grid row/column selector, parsed sample preview, role selector, multi-sheet union. Laptop 1280px, responsive, keyboard accessible visible focus, all inputs labeled, no emojis. Use restrained transitions/hover polish.
