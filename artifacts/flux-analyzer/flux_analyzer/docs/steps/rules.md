# Step 6 — Analysis rules

Every rule is shown as a sentence with its origin. Use the generated form, describe a change targeting that card, or open Advanced JSON. All successful edits use the same validated patch/audit path.

## Measures and views
A measure specifies `agg`, `col`, optional `filter` and optional `slice`. Aggregations are sum, count, distinct count, mean, min and max. Omit `slice` for ordinary base/current comparison. **`slice: none` deliberately ignores the comparison slice**, useful only with explicit filters such as a first-month token.

A view chooses keys and measure names, and whether to compare base/current or show fixed sliced measures. Driver measures must be additive sums so transaction evidence reconciles.

## Flags, gates and sections
Ordered flags select the first true expression, otherwise the default label. Gates select exception rows with a safe boolean expression. Expressions use column names, arithmetic, comparisons, boolean logic and `abs`, never arbitrary Python.

Sections split movement by a column and reconcile to the selected measure. Optional volume/rate decomposition separates volume-at-base-rate from a residual rate effect; inspect assumptions before using that explanation.

## Materiality
- `abs`: use the absolute amount threshold.
- `pct_of_total`: fraction times the absolute selected total basis.
- `max_of`: higher of the absolute and fractional thresholds.
- `min_of`: lower of those thresholds.

`pct: 0.05` means **5%**, not 0.05%. Default basis is absolute total movement. The resolved threshold is shown with results. Materiality affects presentation only: excluded drivers are retained in Other items and still reconcile.

## Commentary
Set units M/K/none, decimals, currency symbol, plus/minus or favourable/unfavourable wording, maximum line words, verification tag, forbidden terms, optional dimension aliases and headline template. Example headline: `Total {label} movement {delta_fmt}, mainly {top_driver}.`

Driver lines must start with the provided formatted movement. AI must use only checked evidence and mark unsupported business causes for verification.

## AI and overrides
The agent proposes settings from the current spec and selected preset guidance, not calculated financial conclusions. Add rule opens Describe change first; **Use a form instead** works without AI. Existing cards open small forms. `Set materiality to 250k` works offline. Live examples include `Flag countries above 10% as Material` or `Split commentary by Region`. Review the actual patch summary and use Undo if it does not reflect your meaning.
