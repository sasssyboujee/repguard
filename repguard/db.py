"""Database module for tracking leads and preventing duplicate audits."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from repguard.utils import PROJECT_ROOT

DB_PATH = PROJECT_ROOT / "repguard.db"


def init_db() -> None:
    """Initialize the SQLite database and create tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_name TEXT NOT NULL,
            url TEXT UNIQUE NOT NULL,
            rating REAL,
            risk_score REAL,
            fake_reviews_found INTEGER,
            audited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def has_been_audited(url: str, days_threshold: int = 30) -> bool:
    """Check if a URL has been audited recently.
    
    Args:
        url: The Google Maps URL of the business.
        days_threshold: Number of days before we consider re-auditing.
        
    Returns:
        True if the business was audited within the threshold.
    """
    if not DB_PATH.exists():
        init_db()
        return False
        
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT audited_at FROM leads WHERE url = ?", 
        (url,)
    )
    result = cursor.fetchone()
    conn.close()
    
    if result:
        audited_at = datetime.fromisoformat(result[0])
        days_since = (datetime.now() - audited_at).days
        return days_since < days_threshold
        
    return False


def record_audit(
    business_name: str,
    url: str,
    rating: float | None,
    risk_score: float,
    fake_reviews_found: int,
) -> None:
    """Save the results of an audit to the database."""
    init_db()
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    cursor = conn.cursor()
    
    # We use REPLACE so if the URL already exists, it updates the record
    cursor.execute("""
        INSERT OR REPLACE INTO leads 
        (business_name, url, rating, risk_score, fake_reviews_found, audited_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        business_name, 
        url, 
        rating, 
        risk_score, 
        fake_reviews_found, 
        datetime.now().isoformat()
    ))
    
    conn.commit()
    conn.close()
