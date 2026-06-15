"""LLM-based fake review detection using Gemini 2.5 Flash.

Sends reviews to Gemini with a carefully engineered prompt and receives
structured FraudAnalysis output via Pydantic schema enforcement.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Optional

from aiolimiter import AsyncLimiter
from pydantic import ValidationError
from google.genai import errors as genai_errors

from google import genai
from google.genai import types

from repguard.models import FraudAnalysis, RecommendedAction, Review, AuditResult
from repguard.utils import (
    console,
    get_api_key,
    GEMINI_MODEL,
    GEMINI_RPM_LIMIT,
    SUSPICION_THRESHOLD,
    PREFILTER_THRESHOLD,
)


# ── System Prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an expert forensic analyst specializing in detecting fake, fraudulent, \
and malicious online business reviews. You work for RepGuard, a reputation \
defense company that protects businesses from review fraud.

Your job is to analyze a single Google Maps review and determine whether it is \
likely fraudulent, malicious, or part of a coordinated attack against the business.

## Fraud Indicators to Look For

1. **Generic / Vague Language**: The review lacks ANY specific details about the \
   business, its products, services, staff, or location. Real customers mention \
   concrete experiences.

2. **Extreme Brevity with Low Rating**: A 1-star review with only a few words and \
   no explanation is a red flag (e.g., "Terrible place" or "Worst ever").

3. **Copy-Paste Patterns**: Language that sounds templated, robotic, or could \
   apply to any business in any industry.

4. **Sentiment-Rating Mismatch**: The text describes an okay or even positive \
   experience but gives 1 star, or vice versa.

5. **No Evidence of Visit**: The reviewer doesn't mention anything that would \
   require actually visiting or using the business.

6. **Inflammatory / Personal Attacks**: Reviews that attack the owner personally \
   rather than describing a service experience.

7. **Competitor Sabotage Signals**: References to competing businesses, \
   suspiciously timed clusters, or mentions of going somewhere else specifically.

## CRITICAL: Minimize False Positives

Not every negative review is fake. Legitimate customers write short, angry \
reviews too. A real 1-star review usually has at least ONE specific complaint \
(e.g., "waited 45 minutes", "the burger was cold", "rude receptionist"). \
Only flag reviews where multiple fraud indicators converge.

When in doubt, err on the side of marking a review as "likely_legitimate" \
or "monitor" rather than "flag_for_dispute". The cost of wrongly accusing a \
real customer is much higher than missing a fake review.
"""


# ── Prompt Template ────────────────────────────────────────────────────────────

ANALYSIS_PROMPT = """\
Analyze the following Google Maps review for signs of fraud or manipulation.

## Business Context
- **Business Name**: {business_name}
- **Business Category**: {business_category}

## Review Under Analysis
- **Reviewer**: {reviewer_name}
- **Rating**: {rating} / 5 stars
- **Date Posted**: {date}
- **Review Text**: "{review_text}"
- **Owner Response**: {owner_response}

Provide your fraud analysis based on the indicators described in your instructions. \
Be precise in your reasoning and cite specific textual evidence from the review.
"""


# Models to try in order (primary → fallback)
MODEL_CHAIN = [GEMINI_MODEL, "gemini-2.0-flash"]

# Retry settings
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # seconds

# Rate limit: 200 requests per 60 seconds (safe for pay-as-you-go)
RATE_LIMITER = AsyncLimiter(200, 60)


def _build_client() -> genai.Client:
    """Build and return a configured Gemini client."""
    api_key = get_api_key()
    return genai.Client(api_key=api_key)


async def analyze_review(
    review: Review,
    business_name: str = "Unknown Business",
    business_category: str = "Unknown",
    client: Optional[genai.Client] = None,
) -> FraudAnalysis:
    """Analyze a single review for fraud using Gemini.

    Args:
        review: The Review object to analyze.
        business_name: Name of the business for context.
        business_category: Category/type of business.
        client: Optional pre-built Gemini client (for batching).

    Returns:
        A FraudAnalysis object with the model's assessment.
    """
    if client is None:
        client = _build_client()

    prompt = ANALYSIS_PROMPT.format(
        business_name=business_name,
        business_category=business_category,
        reviewer_name=review.reviewer_name,
        rating=review.rating,
        date=review.date,
        review_text=review.text,
        owner_response=review.response or "None",
    )

    # Try each model in the chain with retries
    last_error = None
    for model_name in MODEL_CHAIN:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        response_schema=FraudAnalysis,
                        temperature=0.2,
                    ),
                )
                analysis = FraudAnalysis.model_validate_json(response.text)
                return analysis

            except ValidationError as e:
                console.print(f"    [danger]✗ {model_name} failed Pydantic validation. Failing fast without retries.[/danger]")
                raise e
            except Exception as e:
                last_error = e
                # If it's a rate limit error, wait longer
                if "429" in str(e) or "quota" in str(e).lower() or "exhausted" in str(e).lower():
                    delay = 15  # Fallback to 15s for rate limits
                    # Try to extract the requested retry delay
                    match = re.search(r'retry in ([\d.]+)s', str(e), re.IGNORECASE)
                    if match:
                        delay = float(match.group(1)) + 1.0  # Add 1s buffer
                else:
                    delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                
                console.print(
                    f"    [warning]⚠ {model_name} failed: {e.__class__.__name__} "
                    f"(attempt {attempt}/{MAX_RETRIES}), "
                    f"retrying in {delay:.1f}s...[/warning]"
                )
                await asyncio.sleep(delay)

        console.print(
            f"    [warning]⚠ {model_name} failed after {MAX_RETRIES} attempts, "
            f"trying fallback...[/warning]"
        )

    raise RuntimeError(
        f"All models failed after retries. Last error: {last_error}"
    )


async def analyze_reviews_batch(
    reviews: list[Review],
    business_name: str = "Unknown Business",
    business_category: str = "Unknown",
    filter_low_ratings: bool = True,
    use_prefilter: bool = True,
) -> list[AuditResult]:
    """Analyze a batch of reviews, respecting rate limits.

    Args:
        reviews: List of Review objects to analyze.
        business_name: Name of the business.
        business_category: Category of the business.
        filter_low_ratings: If True, only analyze 1-3 star reviews (skip clearly good ones).
        use_prefilter: If True, use local pre-filter to bypass LLM for low suspicion reviews.

    Returns:
        List of AuditResult objects for reviews flagged as suspicious.
    """
    client = _build_client()

    # Optionally filter to only low-rating reviews (the prime suspects)
    candidates = reviews
    if filter_low_ratings:
        candidates = [r for r in reviews if r.rating <= 3]
        console.print(
            f"  [info]Filtered to {len(candidates)} low-rating reviews "
            f"(out of {len(reviews)} total)[/info]"
        )

    if not candidates:
        console.print("  [success]✓ No low-rating reviews found — business looks clean![/success]")
        return []

    results: list[AuditResult] = []

    # 1. First pass: Apply local pre-filter
    suspicious_candidates = []
    for i, review in enumerate(candidates):
        console.print(
            f"  [muted]Prefiltering review {i + 1}/{len(candidates)} "
            f"({review.rating}★ by {review.reviewer_name})...[/muted]"
        )
        if use_prefilter:
            from repguard.prefilter import predict_suspicion
            local_suspicion = predict_suspicion(review.text, review.rating)
            if local_suspicion < PREFILTER_THRESHOLD:
                console.print(
                    f"    [success]✓ Clean[/success] "
                    f"(local pre-filter: suspicion {local_suspicion:.0%})"
                )
                continue
        suspicious_candidates.append((i, review))

    if not suspicious_candidates:
        console.print("\n  [highlight]Analysis complete:[/highlight] 0 suspicious out of 0 sent to AI")
        return []

    # 2. Second pass: AI Analysis in parallel chunks
    chunk_size = GEMINI_RPM_LIMIT
    
    for chunk_start in range(0, len(suspicious_candidates), chunk_size):
        chunk = suspicious_candidates[chunk_start:chunk_start + chunk_size]
        
        async def process_review(orig_idx: int, rev: Review) -> Optional[AuditResult]:
            try:
                analysis = await analyze_review(
                    review=rev,
                    business_name=business_name,
                    business_category=business_category,
                    client=client,
                )
                
                # Log the Gemini output to the local dataset for bootstrapping
                from repguard.prefilter import log_labeled_review
                log_labeled_review(
                    text=rev.text,
                    rating=rev.rating,
                    is_suspicious=analysis.is_suspicious,
                    confidence_score=analysis.confidence_score,
                )

                # Show result inline
                if analysis.is_suspicious and analysis.confidence_score >= SUSPICION_THRESHOLD:
                    console.print(
                        f"    [danger]🚩 Review {orig_idx + 1}: SUSPICIOUS[/danger] "
                        f"(confidence: {analysis.confidence_score:.0%}) — "
                        f"{analysis.fraud_indicators[0] if analysis.fraud_indicators else 'See reasoning'}"
                    )
                    return AuditResult(review=rev, analysis=analysis)
                else:
                    console.print(
                        f"    [success]✓ Review {orig_idx + 1}: Clean[/success] "
                        f"(confidence of fraud: {analysis.confidence_score:.0%})"
                    )
                    return None
                    
            except Exception as e:
                console.print(f"    [warning]⚠ Review {orig_idx + 1} Analysis failed: {e}[/warning]")
                return None

        # Run chunk concurrently, controlled by AsyncLimiter
        async def ratelimited_process(orig_idx: int, rev: Review) -> Optional[AuditResult]:
            async with RATE_LIMITER:
                return await process_review(orig_idx, rev)

        chunk_tasks = [ratelimited_process(orig_idx, rev) for orig_idx, rev in chunk]
        chunk_results = await asyncio.gather(*chunk_tasks)
        
        for res in chunk_results:
            if res:
                results.append(res)

    console.print(
        f"\n  [highlight]Analysis complete:[/highlight] "
        f"{len(results)} suspicious out of {len(suspicious_candidates)} analyzed by AI"
    )

    return results


def analyze_single_review_sync(
    review_text: str,
    rating: int = 1,
    business_name: str = "Test Business",
) -> FraudAnalysis:
    """Quick synchronous analysis of a single review text (for CLI testing)."""
    review = Review(
        reviewer_name="Test Reviewer",
        rating=rating,
        text=review_text,
        date="recently",
    )
    return asyncio.run(
        analyze_review(review, business_name=business_name)
    )
