# Control catalogue

Every control has `id`, `severity` (`stop` or `warn`), optional `tolerance`, and optional `params`. Not every control uses a tolerance; money reconciliations default to a cent.

- **required_columns:** mapped and referenced source columns exist. Mandatory stop.
- **periods_present:** selected base/current months contain records. Mandatory stop.
- **no_duplicate_periods_across_files:** fact files do not overlap accounting periods. Mandatory stop.
- **new_or_removed_members:** dimensions occurring in only one comparison slice. Warning by default.
- **drivers_reconcile:** presented drivers and Other items equal total movement. Mandatory stop.
- **flags_sum_to_rows:** ordered flag counts equal the flagged view row count. Mandatory stop.
- **sections_reconcile:** section movements equal total movement. Mandatory stop when sections are enabled.
- **debit_minus_credit_equals_value:** optional debit-credit tie-out against the value column. Warning by default.
- **join_unmatched_keys:** unmatched lookup keys, rows and signed value; respects per-join unmatched severity. Warning by default.
- **join_fanout:** matching right-side duplicates under `dedupe_right: error` would multiply facts. Mandatory stop. `first` duplicates are retained in audit but do not stop.
- **classification_coverage:** absolute-value coverage meets `params.minimum_percentage`, default 95. Warning by default. Row coverage is reported separately.
- **partial_period_used:** selected months are explicitly marked partial or contain fewer than half the median row count. Warning by default.

Pre-run checks and post-run reconciliation have different timing. A green preflight does not mean post-run checks are skipped. If a mandatory control fails, no finished result pack is released.

## What to do when a check fails
- Missing columns: correct the source rectangle or mappings; check derived names and spelling.
- Missing periods: upload the missing months or choose comparison chips that exist. Do not substitute a neighbouring month without an explicit business decision.
- Overlapping periods across files: remove a duplicate extract or consolidate legitimate disjoint populations into one correctly defined source before uploading.
- New/removed members: inspect the underlying dimension and confirm whether new sites, accounts or renames explain the membership change.
- Driver reconciliation: check additive measure settings, slice filters and grouping. Do not distribute an unreconciled pack.
- Flag counts: inspect the selected view and ordered/default flag rules; every row must have one label.
- Section reconciliation: select a consistent additive measure and split column, and inspect null/extra categories.
- Debit/credit tie-out: confirm the amount definition, source signs and null handling against the ledger.
- Unmatched joins: review normalized keys, lookup freshness, source names and required versus optional policy. Do not infer lookup values for unmatched keys.
- Fanout: correct duplicate lookup keys or deliberately choose first with a documented reason and deterministic source order.
- Classification coverage: inspect high-value fallback texts, add/reorder narrow rules and review the resulting categories. Raising the minimum does not improve coverage.
- Partial month: confirm completeness with the source owner, upload a complete extract or explicitly keep the partial comparison with a caveat.
