# Repairs and maintenance guidance

Analyze repairs and maintenance costs as a finance review, not as an
autonomous accounting decision. Confirm the mapped functional amount and
sign convention before calculating. Use account scope only after the analyst
confirms the account range.

Separate current accruals from reversals using the uploaded event type.
Purchase-order references can be extracted from an explicit PO field or
description; retain `UNMATCHED` where the source has no usable reference.
Treat an open-PO lookup as optional evidence. Join keys must be verified and
unique for value lookups. Do not claim that a match proves a PO is valid,
posted, or approved.

The sample account range, accrual categories, threshold, and quarter defaults
are illustrative presets. Confirm the controlling period, account policy,
materiality, source overlap, and debit/credit conventions with the analyst.
Use [TO VERIFY] for a business cause that is not established by supplied
evidence. Keep domain policy in this guidance and the preset settings; never
add R&M-only branches to Python.
