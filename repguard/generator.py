"""Generator module for dispute letters and cold outreach emails."""

from __future__ import annotations

from pathlib import Path
from datetime import datetime

from repguard.models import AuditReport, AuditResult
from repguard.utils import OUTPUT_DIR, TEMPLATES_DIR, console


def generate_dispute_letters(report: AuditReport) -> list[Path]:
    """Generate a filled-out dispute letter for each suspicious review."""
    template_path = TEMPLATES_DIR / "dispute_template.txt"
    if not template_path.exists():
        console.print("[warning]⚠ Dispute template not found, skipping letter generation.[/warning]")
        return []

    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    generated_files = []
    suspicious_results = report.flagged_reviews

    for i, result in enumerate(suspicious_results):
        review = result.review
        analysis = result.analysis

        # Prepare variables
        evidence = analysis.reasoning
        
        # Pad indicators to 3
        indicators = analysis.fraud_indicators.copy()
        while len(indicators) < 3:
            indicators.append("N/A")

        # Fill template
        content = template
        content = content.replace("[BUSINESS_NAME]", report.business_name)
        content = content.replace("[REVIEWER_NAME]", review.reviewer_name)
        content = content.replace("[REVIEW_DATE]", review.date)
        content = content.replace("[STAR_RATING]", str(review.rating))
        content = content.replace("[REVIEW_TEXT]", review.text)
        
        # Fill evidence and indicators
        content = content.replace("[ADD ADDITIONAL SPECIFIC EVIDENCE HERE]", evidence)
        content = content.replace("[IF APPLICABLE: Evidence suggesting this reviewer is affiliated with\n     a competing business or has a personal conflict]", "N/A based on text analysis alone.")
        content = content.replace("[CONFIDENCE_SCORE]", str(int(analysis.confidence_score * 100)))
        content = content.replace("[INDICATOR_1]", indicators[0])
        content = content.replace("[INDICATOR_2]", indicators[1])
        content = content.replace("[INDICATOR_3]", indicators[2])

        # Fill placeholders with safe defaults for the user to edit
        content = content.replace("[YOUR_NAME]", "Your Name / Agency")
        content = content.replace("[YOUR_TITLE]", "Reputation Manager")
        content = content.replace("[BUSINESS_PHONE]", "[Business Phone Number]")
        content = content.replace("[BUSINESS_EMAIL]", "[Business Email]")

        # Save to file
        safe_name = "".join(c if c.isalnum() else "_" for c in review.reviewer_name)
        filename = f"{report.business_name.replace(' ', '_')}_Dispute_{i+1}_{safe_name}.txt"
        out_path = OUTPUT_DIR / filename
        
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        generated_files.append(out_path)
        
    return generated_files


def generate_outreach_email(report: AuditReport) -> Path:
    """Generate a cold outreach email template for the business owner."""
    suspicious_count = len(report.flagged_reviews)
    total_scraped = report.total_reviews_scraped
    
    is_attack = report.attack_analysis is not None and report.attack_analysis.is_under_attack
    
    if is_attack:
        subject = f"Urgent: Coordinated Review Attack Detected on your Google Maps Profile"
        body = f"""Hi {report.business_name} Team,

I run a reputation management service, and we recently ran a security sweep of local businesses in your area. Our AI systems detected that you are currently the victim of a coordinated fake review attack.

We identified {suspicious_count} highly suspicious 1-star reviews out of the {total_scraped} we analyzed.
{report.attack_analysis.attack_summary}

This is not just a few angry customers—this is a targeted attack. Fake review bombs severely impact local SEO ranking and can permanently drive away potential customers.

I have attached a free preview report detailing exactly 3 of the fake reviews we found, along with the AI's fraud reasoning. 

Because this is an active attack, time is of the essence. If you'd like to unlock the full audit report and have our team handle the entire removal and dispute escalation process for you, I'd love to jump on a quick 5-minute call today.

Let me know if you have any questions about the attached preview report!"""
    else:
        subject = f"Urgent: {suspicious_count} Fake Reviews Found on your Google Maps Profile"
        body = f"""Hi {report.business_name} Team,

I run a reputation management service, and we recently ran a security sweep of local businesses in your area. Our AI systems flagged {suspicious_count} highly suspicious, likely fraudulent 1-star reviews on your Google Maps profile out of the {total_scraped} we analyzed.

Fake reviews severely impact local SEO ranking and drive away potential customers. 

I have attached a free preview report detailing exactly 3 of the fake reviews we found, along with our AI's fraud reasoning. 

If you'd like to unlock the full audit report and have our team handle the entire removal and dispute escalation process for you, I'd love to jump on a quick 5-minute call today.

Let me know if you have any questions about the attached preview report!"""

    content = f"""Subject: {subject}

{body}

Best regards,
[Your Name]
RepGuard Reputation Defense
"""
    filename = f"{report.business_name.replace(' ', '_')}_Outreach_Email.txt"
    out_path = OUTPUT_DIR / filename
    
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    return out_path
