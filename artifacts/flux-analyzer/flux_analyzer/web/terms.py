"""Finance-facing words for Simple mode, plus step copy and contextual help.

Advanced mode keeps the technical names; Simple mode only uses the right-hand
side of TERMS. Keep this the single source so templates, summaries and help
stay consistent.
"""

TERMS = {
    "spec": "setup",
    "FluxSpec": "setup",
    "preset": "starting template",
    "roles": "columns",
    "value": "amount",
    "period": "month",
    "scenario": "version (actual, forecast…)",
    "dimensions": "grouping fields",
    "driver_text": "description",
    "scope": "what's included",
    "derive": "calculated field",
    "joins": "matched lookup",
    "classification": "categories",
    "views": "groupings",
    "drivers": "important movements",
    "materiality": "importance threshold",
    "top_n": "number of movements shown",
    "others_label": "label for everything else",
    "drill": "supporting detail",
    "controls": "data checks",
    "commentary": "explanations",
    "verify_tag": "needs-confirmation marker",
    "run": "report",
}

STEPS = [
    {
        "id": "data", "number": 1, "label": "Data",
        "question": "Which columns hold the numbers?",
        "helper": "Tell us where the amounts, months and descriptions are. Everything else follows from this.",
        "help": "We read your file's column names and pick the amount, month and description columns. Grouping fields are columns like Country or Account that you can break movements down by.",
        "examples": ["Use Functional Net as the amount.", "The month is in Period Name.", "Descriptions are in Line Description."],
    },
    {
        "id": "compare", "number": 2, "label": "Compare",
        "question": "Which periods are you comparing?",
        "helper": "Pick the months that make up the earlier period and the later period.",
        "help": "The report compares the later period with the earlier one. A movement is the difference between them. Months with very few rows are flagged so you can leave them out.",
        "examples": ["Compare Q2 vs Q1.", "Compare the latest quarter with the previous quarter.", "Compare June vs May."],
    },
    {
        "id": "include", "number": 3, "label": "Include",
        "question": "What should be included?",
        "helper": "Keep everything, or narrow the report to the parts of the business you are responsible for.",
        "help": "Filters remove rows before anything is added up. Leave this empty to include every row in your file.",
        "examples": ["Only EMEA.", "Only include account 54100.", "Include everything."],
    },
    {
        "id": "group", "number": 4, "label": "Group",
        "question": "How should movements be grouped?",
        "helper": "Choose the fields that split the total movement into explainable pieces.",
        "help": "Each combination of the grouping fields becomes one movement line, for example one line per country. Fewer fields give fewer, bigger lines.",
        "examples": ["Group by country.", "Group by country and account.", "Group by region."],
    },
    {
        "id": "important", "number": 5, "label": "Important",
        "question": "Which movements need explaining?",
        "helper": "Movements at or above the threshold need an explanation. Everything smaller is grouped together.",
        "help": "The importance threshold decides which movements need explaining. We show the largest ones first, up to the number you choose, and add the rest to one line so the total still adds up.",
        "examples": ["Set the threshold to 250k.", "Show the top 10 movements.", "Show the top 20 movements."],
    },
    {
        "id": "explain", "number": 6, "label": "Explain",
        "question": "How should the explanations read?",
        "helper": "Choose who will read the commentary, how long it should be and the tone. You can paste an example you like.",
        "help": "These preferences shape the AI's draft explanations. Amounts always come from the calculation, and anything the data cannot support is marked for you to confirm.",
        "examples": ["Executive audience, short commentary.", "Risk-focused tone.", "One line per movement."],
    },
]

AUDIENCE_LABELS = {"executive": "Executive", "controller": "Controller", "detailed": "Detailed analyst", "custom": "Custom"}
LENGTH_LABELS = {"short": "Short summary", "medium": "Medium", "per_driver": "One line per movement"}
TONE_LABELS = {"neutral": "Neutral", "risk_focused": "Risk-focused", "fav_unfav": "Favourable / adverse"}
INCLUDE_LABELS = {"timing": "Timing effects", "one_offs": "One-off items", "to_verify": "Mark what needs confirming"}
STATUS_LABELS = {"needs_explanation": "Needs explanation", "ai_review": "Explained by AI — please review", "confirmed": "Confirmed", "below_threshold": "Below threshold"}
CONTROL_LABELS = {
    "required_columns": "The columns this setup needs are in your file",
    "periods_present": "Both periods have data",
    "no_duplicate_periods_across_files": "No month appears in two files",
    "sections_reconcile": "Sections add up to the total",
    "flags_sum_to_rows": "Every line has exactly one flag",
    "drivers_reconcile": "Movements add up to the total",
    "debit_minus_credit_equals_value": "Debit minus credit equals the amount",
    "new_or_removed_members": "New or disappeared lines",
    "join_unmatched_keys": "Lookup matches",
    "join_fanout": "Lookups do not duplicate rows",
    "classification_coverage": "Descriptions sorted into categories",
    "partial_period_used": "Months with unusually few rows",
    "configuration_ready": "Setup is complete",
}


def client_meta() -> dict:
    """Copy and labels the Simple-mode front end needs."""
    return {"steps": STEPS, "status_labels": STATUS_LABELS, "audience": AUDIENCE_LABELS, "length": LENGTH_LABELS, "tone": TONE_LABELS, "include": INCLUDE_LABELS, "controls": CONTROL_LABELS}
