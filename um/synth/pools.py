"""Attribute definitions and value tokens for generated users. Nothing here is real data."""

# (attribute, noun phrase used in statements, question)
USER_ATTRS = (
    ("employer", "employer", "Who is my employer?"),
    ("job_title", "job title", "What is my job title?"),
    ("home_city", "home city", "What city do I live in?"),
    ("gym", "gym", "Which gym do I go to?"),
    ("dentist", "dentist's practice", "What is my dentist's practice called?"),
    ("bank", "bank", "Which bank do I use?"),
    ("phone_carrier", "phone carrier", "Who is my phone carrier?"),
    ("car_model", "car model", "What model of car do I drive?"),
    ("coffee_order", "usual coffee order", "What is my usual coffee order called?"),
    ("code_editor", "code editor", "Which code editor do I use?"),
    ("laptop", "laptop model", "What laptop model do I use?"),
    ("team_name", "team's name", "What is my team called?"),
    ("manager", "manager's surname", "What is my manager's surname?"),
    ("project_codename", "current project's codename", "What is the codename of my current project?"),
    ("restaurant", "favourite restaurant", "What is my favourite restaurant?"),
    ("book_club_pick", "book club's current pick", "What is my book club's current pick?"),
    ("running_route", "usual running route", "What is my usual running route called?"),
    ("insurer", "insurance provider", "Who is my insurance provider?"),
    ("accountant", "accountant's firm", "What is my accountant's firm called?"),
    ("backup_service", "backup service", "Which backup service do I use?"),
    ("password_manager", "password manager", "Which password manager do I use?"),
    ("calendar_app", "calendar app", "Which calendar app do I use?"),
    ("standup_room", "stand-up meeting room", "Which room is my stand-up meeting in?"),
    ("holiday_spot", "usual holiday spot", "Where do I usually go on holiday?"),
)

SYSTEM_ATTRS = (
    ("connector_name", "budget connector's name", "What is my budget connector called?"),
    ("deploy_target", "deploy target", "What is my deploy target called?"),
    ("default_branch", "default branch name", "What is my repository's default branch called?"),
    ("issue_tracker", "issue tracker", "Which issue tracker do I use?"),
    ("ci_runner", "CI runner", "What is my CI runner called?"),
    ("staging_host", "staging host", "What is my staging host called?"),
)

_PREFIXES = ("Bright", "Oak", "Zen", "Alder", "Marl", "Quill", "Tamar", "Vireo", "Cinder", "Harbor", "Lumen",
             "Nimbus", "Pellam", "Rowan", "Sable", "Thistle", "Umber", "Wren", "Yarrow", "Dunmore")
_SUFFIXES = ("line", "field", "trix", "moor", "wick", "stead", "haven", "forge", "crest", "dale", "mere", "holt",
             "gate", "ridge", "brook", "vale", "port", "bury", "shaw", "combe")

# 400 distinct made-up names; none contains another because all are one prefix plus one suffix.
TOKENS = tuple(p + s for p in _PREFIXES for s in _SUFFIXES)

NEUTRAL_CHATS = (
    "Can you suggest a quick weeknight dinner?",
    "What's a good way to stretch after sitting all day?",
    "Explain how compound interest works in two sentences.",
    "Give me three names for a houseplant.",
    "How long should I steep green tea?",
    "What's a polite way to decline a meeting?",
)
