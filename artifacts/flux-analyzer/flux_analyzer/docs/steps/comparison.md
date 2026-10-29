# Step 3 — Comparison

The engine compares **current less base**. Choose month chips for both slices. Imported labels such as `JAN-26` and `2026-01` normalize to the same month, `2026-01`.

Supported workflows include month-on-month, quarter-on-quarter, year-on-year, year-to-date, custom ranges and Actual versus Forecast. The comparison `type` is a label; the explicit slice months and filters determine the calculation.

Each slice supports `months`, optional `scenario` and optional `filters`. Scenarios require a mapped scenario column. A fiscal calendar can be supplied as `periods.calendar: {"start_month": 4}`; quarter labels use that fiscal start.

## Input formats
Choose `auto`, `YYYY-MM`, `MON-YY`, `MON-YYYY`, `MM/YYYY`, `DD/MM/YYYY`, `MM/DD/YYYY`, or `YYYY-MM-DD`. Explicit formats are preferable for ambiguous numeric dates.

## Partial months
Monthly row counts are shown beside the chips. A month with fewer than half the median monthly row count is flagged as possibly partial. This is a heuristic, not a calendar-completeness guarantee. Explicit `partial_periods` are also respected. Selected partial months warn; missing selected months stop.

Recheck the comparison whenever reusing a run against new uploads. Reuse preserves historic periods rather than guessing that the newest month should be used.

## AI and overrides
The agent receives available periods and counts and can suggest complete comparison ranges. Its result preselects the chips; inspect them before running. Override directly with the comparison dropdown/chips or say `Compare May vs April` (also supported offline). Use explicit years in live instructions if files span several years.
