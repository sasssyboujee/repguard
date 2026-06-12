"""Shared utilities: configuration loading, logging, and constants."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.theme import Theme

# ── Paths ──────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
TEMPLATES_DIR = PROJECT_ROOT / "templates"

# Ensure output directory exists
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Environment ────────────────────────────────────────────────────────────────

load_dotenv(PROJECT_ROOT / ".env")


def get_api_key() -> str:
    """Get the Google API key from environment, raising a clear error if missing."""
    key = os.getenv("GOOGLE_API_KEY")
    if not key or key == "your_gemini_api_key_here":
        raise EnvironmentError(
            "GOOGLE_API_KEY is not set.\n"
            "1. Get a key from https://aistudio.google.com/apikey\n"
            "2. Add it to your .env file: GOOGLE_API_KEY=your_key_here"
        )
    return key


# ── Constants ──────────────────────────────────────────────────────────────────

# Gemini model to use for analysis
GEMINI_MODEL = "gemini-2.5-flash"

# Rate limiting for Gemini API (requests per minute for free tier)
GEMINI_RPM_LIMIT = 15

# Default max reviews to scrape per business
DEFAULT_MAX_REVIEWS = 50

# Confidence threshold for flagging a review as suspicious
SUSPICION_THRESHOLD = 0.6

# Suspicion threshold for the local ML pre-filter (below this, reviews bypass Gemini)
PREFILTER_THRESHOLD = 0.25

# ── Rich Console ───────────────────────────────────────────────────────────────

custom_theme = Theme({
    "info": "cyan",
    "success": "bold green",
    "warning": "bold yellow",
    "danger": "bold red",
    "highlight": "bold magenta",
    "muted": "dim white",
})

console = Console(theme=custom_theme)


def print_banner() -> None:
    """Print the RepGuard startup banner."""
    console.print()
    console.print("  ┌───────────────────────────────────────────────┐", style="info")
    console.print("  │   [bold cyan]RepGuard[/bold cyan] — Reputation Defense Engine        │", style="info")
    console.print("  │   AI-Powered Fake Review Detection            │", style="info")
    console.print("  │   v0.1.0                                      │", style="info")
    console.print("  └───────────────────────────────────────────────┘", style="info")
    console.print()

