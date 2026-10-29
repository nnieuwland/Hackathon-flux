# Step 2 — Column mappings

Map `value` to the signed amount and `period` to the accounting month/date. For debit-minus-credit value mode, also map `debit` and `credit`. Map `scenario` before using scenario slices.

- `dimensions`: groupings used to explain movements, such as country, department or cost centre.
- `keys`: transaction/business identifiers, such as purchase order.
- `driver_text`: one or more descriptions to consolidate for drill evidence and classification.
- Optional mappings can remain empty; required mappings must exist before a run.

On a replacement upload, the app retains exact matches and conservatively maps unambiguous similar header names. It logs renames. Ambiguous or absent mappings remain visible for correction; it does not invent a column.

Mapped amount values must be numeric. Null handling belongs to the value rules. Financial calculations do not run in the browser. Derived names and lookup outputs can be used by later rules, provided they exist at that point in processing.

## AI and overrides
Mapping suggestions use the profile, a few bounded column samples and previous role names. Change any mapping with the column-role controls and save. A live instruction could be `Use Functional_Net as value and Description as driver text`. Check that sign and debit/credit assumptions match the actual extract rather than trusting a similar header name.
