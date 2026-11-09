"""Runtime configuration, loaded from .env at the repo root."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODELS = [
    m.strip()
    for m in os.getenv("GEMINI_MODELS", "gemini-flash-lite-latest").split(",")
    if m.strip()
]
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

# live | replay | auto
SOURCE_MODE = os.getenv("SOURCE_MODE", "auto").strip().lower()

DB_PATH = ROOT / "runs.db"
FRONTEND_DIR = ROOT / "frontend"

# --- Policy knobs. These are the numbers an operator would actually argue about,
# --- so they live in one place and are surfaced in the UI.
SIGNAL_MAX_AGE_DAYS = 180        # anything older is stale and never used as a hook
SIGNAL_FRESH_DAYS = 30           # "fresh" tier for the recency score
SIGNAL_RECENT_DAYS = 90          # "recent" tier
MIN_HOOK_SCORE = 55              # below this we will not personalise on it
MIN_PERSON_HOOK_SCORE = 62       # person-level hooks are held to a higher bar
HTTP_TIMEOUT = 20

MAX_DRAFT_WORDS = 120            # an SDR email nobody reads past this
DRAFT_REPAIR_ATTEMPTS = 1        # re-draft once if a claim fails verification

# Halting a run on an identity verdict is expensive -- it tells the rep their
# CRM is wrong and produces no draft. The job-move probe deliberately searches
# unscoped for "joins / steps down" language, which means it reliably surfaces
# unrelated namesakes. So a halt requires a confident verdict that cites a
# specific source; anything weaker degrades to a warning and the run continues
# on company-level hooks.
IDENTITY_HALT_CONFIDENCE = 70

# Who the rep works for. A draft needs a point, not just a compliment -- this is
# what the hook gets connected to. Editable from the Settings view.
SELLER = {
    "company": "Zamp",
    "one_liner": "AI agents that run finance and back-office operations",
    "what_we_do": (
        "We automate the operational work inside finance teams: accounts payable "
        "and invoice processing, vendor onboarding and verification, reconciliation, "
        "and the approval workflows around them. Our customers are typically "
        "finance and operations leaders at companies scaling past the point where "
        "spreadsheets and manual review hold up."
    ),
    "proof": "Teams using us cut invoice handling time by 70-80% and close faster.",
    "rep_name": "Mohesh V",
    "rep_title": "AI Solutions Analyst",
}
