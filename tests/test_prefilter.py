"""Unit tests for the local ML/NLP pre-filter."""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from repguard.prefilter import (
    extract_features,
    compute_heuristic_suspicion,
    predict_suspicion,
    log_labeled_review,
    LABELED_DATA_PATH,
)


def test_extract_features():
    """Verify that features are extracted correctly with valid types."""
    review_text = "Worst service ever! Extremely disappointed."
    rating = 1
    
    features = extract_features(review_text, rating)
    
    assert isinstance(features, dict)
    assert features["rating"] == 1.0
    assert features["word_count"] == 6.0
    assert features["char_count"] == len(review_text)
    assert "vader_compound" in features
    assert features["sentiment_rating_mismatch"] == 0.0  # VADER sentiment should be negative, matches 1-star (no mismatch)
    assert features["generic_template_count"] >= 1.0  # Should match "worst service" or "worst experience" or "terrible"


def test_sentiment_rating_mismatch():
    """Verify sentiment rating mismatch is flagged correctly."""
    # Positive text with negative rating (mismatch = 1.0)
    features_bad = extract_features("Great service! Love it here, the best place ever.", 1)
    assert features_bad["sentiment_rating_mismatch"] == 1.0
    
    # Negative text with positive rating (mismatch = 1.0)
    features_good = extract_features("Worst experience ever, awful and terrible customer service.", 5)
    assert features_good["sentiment_rating_mismatch"] == 1.0
    
    # Negative text with negative rating (mismatch = 0.0)
    features_match = extract_features("Worst experience ever, awful and terrible customer service.", 1)
    assert features_match["sentiment_rating_mismatch"] == 0.0


def test_heuristic_suspicion_calculation():
    """Verify suspicion score calculation for clear fake vs. clean reviews."""
    # Short low-rating generic review (should be high suspicion)
    features_fake = extract_features("Terrible place!", 1)
    score_fake = compute_heuristic_suspicion(features_fake)
    assert score_fake > 0.40  # Brief 1-star review is highly suspicious
    
    # Detailed specific review (should be low suspicion)
    detailed_text = (
        "I came here on a Tuesday afternoon. The food was average but the wait time "
        "was extremely long. Staff seemed friendly but busy. Probably won't come back."
    )
    features_clean = extract_features(detailed_text, 2)
    score_clean = compute_heuristic_suspicion(features_clean)
    assert score_clean < 0.25  # Detailed reviews are not flagged as suspicious locally


def test_log_labeled_review(tmp_path, monkeypatch):
    """Test that reviews are correctly logged to CSV."""
    test_csv = tmp_path / "test_labels.csv"
    
    # Mock LABELED_DATA_PATH to point to test_csv
    monkeypatch.setattr("repguard.prefilter.LABELED_DATA_PATH", test_csv)
    
    log_labeled_review("This is a test review text.", 3, is_suspicious=True, confidence_score=0.85)
    
    assert test_csv.exists()
    content = test_csv.read_text(encoding="utf-8")
    assert "This is a test review text." in content
    assert "0.85" in content
    assert "is_suspicious" in content
