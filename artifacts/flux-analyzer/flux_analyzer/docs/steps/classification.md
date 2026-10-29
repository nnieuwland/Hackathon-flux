# Step 5 — Classification review

Classification creates a category column from one or more description columns. `source_cols` may contain the exact token `{roles.driver_text}`. Selected texts are concatenated in their configured order.

Rules contain `keyword`, `category`, `match` and `reviewed`. Matching supports `contains`, `eq`, `startswith` and `regex`; case sensitivity is configurable. First match wins. Put specific keywords before broad ones, or use **Sort by specificity** and inspect the resulting order.

Agent-generated rules start unreviewed. Existing reviewed keyword rules are retained when the agent suggests additions. Use the review filter, search, select rows and bulk accept/delete. Mark a rule reviewed only after checking its meaning.

## Coverage
- **Row coverage:** percentage of analysed rows assigned something other than the fallback category.
- **Value coverage:** percentage of absolute value assigned something other than fallback. Absolute value avoids cancellation between positive and negative amounts.
- The preview consolidates identical text/category/review combinations and shows row counts and absolute value. It is not a dump of individual transactions.
- The default coverage control warns below 95% absolute-value coverage; it does not silently discard the fallback rows.

Unmatched texts go to the configured fallback, for example `Other / General Maintenance`. A fallback is a visible classification outcome, not proof that the text has been understood.

## AI and overrides
Suggest categories sends consolidated description terms and preset category guidance. Every new agent rule remains unreviewed. Use the table to edit the category, move a rule or mark reviewed. A live example is `Classify chlr as Chillers using contains, before the general maintenance rule`. Recheck coverage after changing order; do not bulk accept solely to remove amber indicators.
