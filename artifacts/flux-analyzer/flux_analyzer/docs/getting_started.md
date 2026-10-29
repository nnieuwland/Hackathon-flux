# Getting started

Flux Analyzer explains why balances moved between two periods. Python calculates every amount and reconciliation. AI can set up the report from your description and draft explanations; it never calculates your results and never confirms an explanation for you.

## The guided journey (Simple mode)
1. **Upload** your file. The header row is found for you.
2. **Describe your flux** in a sentence, for example “Compare Q2 with Q1 by country, threshold 100k, top 10”, or choose **Set up step by step**.
3. **Six steps** — Data, Compare, Include, Group, Important, Explain. Steps the assistant could fill are marked ready; anything it was unsure about is marked **Needs input**.
4. **Review** the plain-English summary and the data checks, then run the report.
5. **Results** lead with what needs your input: write or confirm each explanation. AI drafts are marked for review; only a person can confirm them.
6. **Download** the Excel review pack (formula-backed, with a Needs Explanation sheet) and **save the setup** so your team can reuse it.

Every AI change applies straight away with a short summary and **Undo**. If you change something while the assistant is still working, its answer is discarded rather than overwriting your change.

## Advanced mode
Switch to **Advanced** in the header for the full set of controls below. Both modes edit the same setup.
- **Sources:** upload CSV/XLSX files, select the sheet, header row and column bounds, then confirm each definition. Choose or create a preset.
- **Columns:** map amount, period, optional debit/credit and scenario columns, dimensions, keys and transaction descriptions.
- **Comparison:** choose base/current month chips. These are stored as `YYYY-MM`, regardless of the uploaded labels.
- **Scope:** filter rows, net debits and credits, flip signs conditionally, define derived columns and optional lookup joins.
- **Classification:** review ordered keyword/category rules and inspect row/value coverage. First match wins.
- **Rules:** configure measures, views, flags, gates, sections, driver materiality, drill depth and commentary style.
- **Review:** run controls. Resolve every red stop; inspect amber warnings. Review the change log.
- **Results:** inspect drivers and consolidated evidence, review commentary line checks, ask questions and export the audit pack.

## Make changes safely
Use manual forms or the persistent **Describe a change** box. Valid AI configuration changes apply automatically, including low-confidence changes; low confidence is marked “Please check.” Partial valid suggestions can apply while the assistant asks follow-up questions. Invalid or unsupported suggestions do not change settings. Undo and Redo are available.

Offline mode supports specific examples: `Only EMEA`, `Set materiality to 250k`, `Compare May vs April`, and `Show top 5 drivers`. General natural-language interpretation requires the live AI Engine. Manual forms remain usable offline.

## Save and reuse
Save a preset for future analyses, export it to share settings, or reuse a completed run against your currently uploaded files. Historical run inputs and results are not overwritten by reuse.

Read the [complete parameter reference](/docs?doc=reference) for exact settings, and [AI and local setup](/docs?doc=ai_and_data) before connecting corporate services.
