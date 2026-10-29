# Step 7 — Review and controls

Read the configuration summary, comparison slices, selected partial periods, rule origins and change log. Each log entry records time, actor, path, before/after and reason.

Run **Check controls** before the analysis. Red stop controls block output release. Amber warnings remain visible but do not block. Post-run reconciliation controls are run again before any pack is released.

Mandatory stops include missing columns, missing periods, overlapping source-file periods, duplicate-key fanout under the error policy and reconciliation failures. You cannot bypass those by removing their settings.

Inspect coverage warnings, new/removed dimension members, unmatched lookup keys and possibly partial months. Explain warnings in your finance review rather than assuming a successful calculation makes them immaterial.

Undo and Redo apply whole validated snapshots through the audited patch path. They change configuration, not uploaded files or completed historical runs. Recheck controls after any settings change.

## AI and overrides
The assistant can explain a configured rule or propose a settings correction, but it cannot waive a mandatory failed reconciliation. Ask `What does materiality mean here?` or, in live mode, describe the intended scope correction. Use the appropriate earlier form to correct source/mapping errors; do not lower tolerances just to get a green run.
