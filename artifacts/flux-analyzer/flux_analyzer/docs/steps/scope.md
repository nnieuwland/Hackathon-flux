# Step 4 — Scope, signs, derived columns and joins

## Scope
Scope filters are combined with AND. Supported operators are equality/inequality, membership, numeric comparison, starts-with, contains, regex and null/not-null. The preview shows included and excluded amounts.

## Values and signs
Choose the mapped amount column or `debit_minus_credit`. Nulls are zero by default; disabling `null_as_zero` rejects missing value inputs. Conditional `flip_sign_when` filters multiply matching amounts by -1. Multiple matching rules flip repeatedly, so avoid unintended overlaps.

## Derived columns
- **Ordered rules:** first matching condition supplies a label; otherwise use the default.
- **Regex extraction:** try source columns in order, optionally remove a pattern first, extract the first capture group, then use a default if no match.
- **Map:** exact string lookup with a fallback.
- **Ratio:** numerator divided by denominator; zero denominators become null.
- **Concat:** join selected source columns with a separator.
- **Numeric buckets:** pandas-style numeric cut boundaries with optional labels.

Names are evaluated in order: a derived column can use an earlier derived column. Regex patterns are limited to 500 characters. Never paste Python code into a rule.

## Source-level lookup joins
Choose a named lookup, one or more left/right key pairs, columns and a prefix. Joins are left joins and never intentionally multiply facts. Normalization can trim whitespace, uppercase strings and strip leading zeros; the sequence is configurable.

`dedupe_right: first` keeps the first matching lookup record and records duplicate keys. `error` blocks release if matching duplicate keys would fan out the facts. Unmatched keys, row counts and signed values are audited. Optional lookup absence warns; required lookup absence fails.

Processing order is derived columns, value calculation, source joins, classification, scope, period normalization, measures/views, flags/gates, drivers and evidence. Consequently a derived column cannot depend on a later join output; create its source before the join or use joined fields in later scope/classification/measures.

## AI and overrides
The agent sees consolidated values/counts and current settings, not raw records. It can propose declarative filters and helper columns. Edit each section with its form or target its card using Describe change. `Only EMEA` is supported offline; a live example is `Extract the six-digit PO from Description, otherwise UNMATCHED`. Preview after saving, and inspect included/excluded values.
