# Step 8 — Results, commentary and audit

Results show base, current, movement, ranked drivers, Other items, exception flags, classification coverage, resolved materiality and join diagnostics. Current minus base is the movement convention.

Open a driver to see consolidated descriptions. Top descriptions plus the remainder reconcile to its movement. Those are aggregated evidence, not AI-created figures.

## Commentary checks
Generate all lines or regenerate a single driver line. Each line is checked for amount-first ordering, the exact provided amount token, driver order, word limit, forbidden words and unsupported numbers. A configured headline is copied exactly.

The AI sees, per movement, the base and current amounts, up to six earlier periods of the same length with a pattern decided by Python (one period, continuing, reversal…), volume/rate effects, the category mix with whether each category's rule was approved, flags and coverage (lines behind it, descriptions shown, unmatched or uncategorised lines, incomplete periods), plus report-wide data-quality findings. It never receives transaction rows. Lines may list claims separated into observations, possible explanations and stated context; trend words are rejected unless the history shows that pattern, and causes, timing or one-off wording need the verification tag unless they repeat something you told it on the Explain step. The Explain step's "What is the commentary for?" and "What do you already know?" are passed as attributed, unverified context; leave amounts out of them. Review cards show each movement's history and what to confirm.

Analyst edits are saved with provenance and line validation. Passing mechanical checks does not verify a business cause; manually edited commentary remains labelled unverified for distribution. Use the verification tag for statements requiring operational confirmation.

Ask questions about the current settings or a selected run's evidence. Answers cannot change calculations. Unsupported numeric claims are rejected. Offline answers are configuration-based explanations, not general AI reasoning.

## Exports
- **Excel review pack (primary):** opens on a Summary overview — the month comparison, base/current/movement totals, explanation status, the headline and the key drivers with their checked commentary — with links to every tab. Needs Explanation, Commentary, Drill-down, Data checks, Data and Settings follow. Amounts on these sheets are formulas over the Data sheet that recalculate in Excel (change Threshold on Settings to test sensitivity); when a setup cannot be expressed as exact formulas the pack says why and uses the engine's values. Supporting detail (Variance, Movement detail, Source lines, Classifications, Unmatched lookups) and the audit trail (Data controls, Setup changes, Explanation log, Run audit with input-file fingerprints, AI assistant log, FluxSpec) follow, grouped by tab colour.
- **FluxSpec JSON:** portable current run settings with a `run_stamp`; it can be imported again.

Word and Markdown downloads have been retired; the Excel pack carries the commentary, its status and the audit stamp. History keeps completed runs. Open preserves their evidence; Reuse applies only settings to current uploads and logs the action. To change the calculation, rerun the report rather than editing exported amounts.

## AI and overrides
Generate uses the checked evidence pack and your commentary rules. Edit a single line manually or use Regenerate for that driver. A question such as `Why is this purchase order flagged?` is answered from the stored rules/evidence in live mode; offline answers explain the configured rules. To change the calculation, use Describe change and rerun rather than rewriting an exported amount.
