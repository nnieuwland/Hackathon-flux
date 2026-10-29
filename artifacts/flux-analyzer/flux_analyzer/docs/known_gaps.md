# Known limits and important assumptions

- This is a local trusted-operator application, not a corporate authenticated multi-user service.
- State, uploads and completed outputs are local files. Pending jobs are lost on restart; multiple Gunicorn processes do not share the job registry.
- Live corporate AI connectivity is environment-specific and is not verified by passing offline tests.
- Offline natural-language handling is deliberately limited; it does not pretend to interpret every business instruction.
- Financial inputs must be numeric and periods parseable. Ambiguous numeric date formats should be explicitly selected.
- Partial-month detection is based on row-count imbalance, not a business calendar or source-system completeness feed.
- Overlapping periods across fact files are stopped conservatively, even if the files might represent disjoint populations.
- First-match classification can hide broad-rule overlaps. Review order and coverage, not just category names.
- Lookup `first` deduplication depends on file/upload order. Use `error` when that ordering is not a justified business rule.
- Derived columns run before source joins. Cyclic derived/join dependencies and arbitrary custom Python are unsupported.
- Driver evidence requires additive sum measures. Mean/min/max/count/distinct measures can appear in other view columns but are not reconciling monetary driver measures.
- Percentage-of-total materiality uses an absolute net total, not a sum of absolute driver movements. Net cancellation can lower that threshold.
- Volume/rate decomposition is a deterministic arithmetic model, not proof of causality. Residual rate impact may include mix, timing and interaction effects.
- Dimension code style does not guess external country codes; supply explicit alias mappings when stored labels are not already codes.
- Narrative validation checks evidence amounts, order, word limits and prohibited terms. It does not establish truth of qualitative business explanations.
- Regexes are length-limited but not executed in a sandbox with a separate per-pattern timeout; use simple trusted patterns.
- Exports are snapshots. Editing an Excel pack does not change the stored spec or recalculate the local run.
