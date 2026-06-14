"""Batch analysis module for detecting coordinated review attacks."""

from __future__ import annotations

from collections import Counter
from typing import Sequence

from repguard.models import AttackAnalysis, AuditResult, Review


def _calculate_jaccard_similarity(text1: str, text2: str) -> float:
    """Calculate the Jaccard similarity between two texts based on word sets."""
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())
    if not words1 or not words2:
        return 0.0
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    return len(intersection) / len(union)


def detect_linguistic_overlap(negative_reviews: list[Review]) -> bool:
    """Detect if multiple negative reviews share templated or copied language."""
    # Check all pairs of negative reviews for high similarity
    for i in range(len(negative_reviews)):
        for j in range(i + 1, len(negative_reviews)):
            text1 = negative_reviews[i].text.strip()
            text2 = negative_reviews[j].text.strip()
            
            # Ignore extremely short reviews like "terrible"
            if len(text1.split()) < 4 or len(text2.split()) < 4:
                continue
                
            sim = _calculate_jaccard_similarity(text1, text2)
            if sim > 0.6:  # 60% word overlap is highly suspicious for long texts
                return True
    return False


def analyze_attack_patterns(
    all_reviews: Sequence[Review], 
    flagged_results: Sequence[AuditResult]
) -> AttackAnalysis:
    """Analyze a batch of reviews to determine if the business is under attack."""
    if not all_reviews:
        return AttackAnalysis()

    # We focus on 1-star and 2-star reviews as the "attack vectors"
    negative_reviews = [r for r in all_reviews if r.rating <= 2]
    total_reviews = len(all_reviews)
    
    if len(negative_reviews) < 3:
        # Not enough data to call it a coordinated attack
        return AttackAnalysis()

    # 1. Detect Velocity Spike
    # Group negative reviews by their relative date string (e.g., "2 weeks ago")
    date_counts = Counter(r.date for r in negative_reviews)
    velocity_spike = False
    spike_date = ""
    for date_str, count in date_counts.items():
        # If >=3 negative reviews AND they make up >30% of all negative reviews
        if count >= 3 and (count / len(negative_reviews)) >= 0.3:
            velocity_spike = True
            spike_date = date_str
            break

    # 2. Detect Linguistic Overlap
    linguistic_overlap = detect_linguistic_overlap(negative_reviews)

    # 3. Detect Rating Polarization (U-shape distribution)
    five_star_reviews = [r for r in all_reviews if r.rating == 5]
    polarization = False
    if total_reviews >= 10:
        extreme_ratings = len(negative_reviews) + len(five_star_reviews)
        if (extreme_ratings / total_reviews) > 0.85:
            polarization = True

    # 4. Determine overall attack status
    # We require either a velocity spike + polarization, OR a velocity spike + AI flagged reviews
    # to confidently call it an attack.
    is_under_attack = False
    reasons = []

    if velocity_spike:
        reasons.append(f"Abnormal velocity spike: {date_counts[spike_date]} bad reviews posted '{spike_date}'.")
        
    if linguistic_overlap:
        reasons.append("Linguistic overlap: Multiple bad reviews share identical phrasing/templates.")
        is_under_attack = True  # Overlap alone is basically proof of a bot
        
    if polarization:
        reasons.append("Rating polarization: Abnormal U-shaped rating distribution (only 1s and 5s).")

    # If it has a spike and at least one review was actually flagged by Gemini, call it an attack.
    if velocity_spike and len(flagged_results) > 0:
        is_under_attack = True

    summary = " ".join(reasons) if is_under_attack else "No coordinated attack patterns detected."

    return AttackAnalysis(
        is_under_attack=is_under_attack,
        velocity_spike_detected=velocity_spike,
        linguistic_overlap_detected=linguistic_overlap,
        rating_polarization_detected=polarization,
        attack_summary=summary,
    )
