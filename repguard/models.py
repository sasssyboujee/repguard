"""Pydantic data models for the entire RepGuard pipeline.

These models define the shape of data flowing from scraper → analyzer → report.
The FraudAnalysis model doubles as the Gemini structured output schema.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ReviewRating(int, Enum):
    """Google Maps star ratings."""
    ONE = 1
    TWO = 2
    THREE = 3
    FOUR = 4
    FIVE = 5


class RecommendedAction(str, Enum):
    """What to do with a flagged review."""
    FLAG_FOR_DISPUTE = "flag_for_dispute"
    MONITOR = "monitor"
    LIKELY_LEGITIMATE = "likely_legitimate"


class Review(BaseModel):
    """A single Google Maps review, as scraped from the page."""

    reviewer_name: str = Field(description="Display name of the reviewer")
    reviewer_url: str | None = Field(
        default=None,
        description="URL to the reviewer's Google Maps profile",
    )
    rating: int = Field(ge=1, le=5, description="Star rating (1-5)")
    text: str = Field(description="Full review text content")
    date: str = Field(
        description="Relative date string from Google (e.g. '2 weeks ago')",
    )
    response: str | None = Field(
        default=None,
        description="Owner's reply to the review, if any",
    )
    review_id: str | None = Field(
        default=None,
        description="Unique identifier extracted from the review element",
    )


class FraudAnalysis(BaseModel):
    """Structured output from the Gemini LLM fraud detection.

    This model is passed directly to Gemini as the response_schema,
    guaranteeing the output matches this shape exactly.
    """

    is_suspicious: bool = Field(
        description="Whether this review shows signs of being fake or malicious",
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence that this review is fraudulent (0.0 = certainly real, 1.0 = certainly fake)",
    )
    fraud_indicators: list[str] = Field(
        default_factory=list,
        description="Specific red flags detected (e.g. 'Generic vague language', 'No business-specific details')",
    )
    reasoning: str = Field(
        description="Detailed explanation of the analysis and conclusion",
    )
    recommended_action: RecommendedAction = Field(
        description="Recommended next step based on the analysis",
    )


class AuditResult(BaseModel):
    """A single review paired with its fraud analysis."""

    review: Review
    analysis: FraudAnalysis


class AuditReport(BaseModel):
    """Complete audit report for a single business."""

    business_name: str = Field(description="Name of the business being audited")
    business_url: str = Field(description="Google Maps URL of the business")
    business_address: str | None = Field(
        default=None,
        description="Physical address of the business",
    )
    business_rating: float | None = Field(
        default=None,
        ge=1.0,
        le=5.0,
        description="Overall Google Maps rating",
    )
    total_reviews_scraped: int = Field(
        description="Total number of reviews processed",
    )
    flagged_reviews: list[AuditResult] = Field(
        default_factory=list,
        description="Reviews flagged as potentially fraudulent",
    )
    clean_reviews_count: int = Field(
        default=0,
        description="Number of reviews that passed the audit",
    )
    generated_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when the report was generated",
    )
    overall_risk_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Aggregate risk score for the business (0.0 = clean, 1.0 = heavily targeted)",
    )
