"""Professional PDF report generator for RepGuard audit results.

Generates a polished, client-ready 'Reputation Audit Report' PDF
with branded styling, flagged review details, and dispute templates.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    PageBreak,
    PageTemplate,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from repguard.models import AuditReport, AuditResult
from repguard.utils import OUTPUT_DIR, TEMPLATES_DIR, console


# ── Color Palette ──────────────────────────────────────────────────────────────

NAVY = colors.HexColor("#0F1B2D")
DARK_BLUE = colors.HexColor("#1A2744")
ACCENT_BLUE = colors.HexColor("#3B82F6")
AMBER = colors.HexColor("#F59E0B")
RED = colors.HexColor("#EF4444")
GREEN = colors.HexColor("#22C55E")
LIGHT_GRAY = colors.HexColor("#F3F4F6")
MID_GRAY = colors.HexColor("#9CA3AF")
DARK_TEXT = colors.HexColor("#1F2937")
WHITE = colors.white


# ── Styles ─────────────────────────────────────────────────────────────────────

def _build_styles() -> dict[str, ParagraphStyle]:
    """Build the custom paragraph styles for the report."""
    base = getSampleStyleSheet()

    return {
        "cover_title": ParagraphStyle(
            "cover_title",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=28,
            textColor=NAVY,
            alignment=TA_CENTER,
            spaceAfter=12,
        ),
        "cover_subtitle": ParagraphStyle(
            "cover_subtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=14,
            textColor=MID_GRAY,
            alignment=TA_CENTER,
            spaceAfter=6,
        ),
        "section_heading": ParagraphStyle(
            "section_heading",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=16,
            textColor=NAVY,
            spaceBefore=20,
            spaceAfter=10,
        ),
        "sub_heading": ParagraphStyle(
            "sub_heading",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=DARK_BLUE,
            spaceBefore=12,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            textColor=DARK_TEXT,
            leading=14,
            alignment=TA_JUSTIFY,
            spaceAfter=6,
        ),
        "body_bold": ParagraphStyle(
            "body_bold",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=DARK_TEXT,
            leading=14,
            spaceAfter=4,
        ),
        "quote": ParagraphStyle(
            "quote",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=10,
            textColor=colors.HexColor("#4B5563"),
            leading=14,
            leftIndent=20,
            rightIndent=20,
            spaceBefore=6,
            spaceAfter=6,
            borderColor=ACCENT_BLUE,
            borderWidth=2,
            borderPadding=8,
            backColor=LIGHT_GRAY,
        ),
        "indicator_bad": ParagraphStyle(
            "indicator_bad",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            textColor=RED,
            leftIndent=30,
            spaceAfter=2,
        ),
        "footer": ParagraphStyle(
            "footer",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=MID_GRAY,
            alignment=TA_CENTER,
        ),
        "risk_high": ParagraphStyle(
            "risk_high",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=24,
            textColor=RED,
            alignment=TA_CENTER,
        ),
        "risk_medium": ParagraphStyle(
            "risk_medium",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=24,
            textColor=AMBER,
            alignment=TA_CENTER,
        ),
        "risk_low": ParagraphStyle(
            "risk_low",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=24,
            textColor=GREEN,
            alignment=TA_CENTER,
        ),
        "dispute_text": ParagraphStyle(
            "dispute_text",
            parent=base["Normal"],
            fontName="Courier",
            fontSize=9,
            textColor=DARK_TEXT,
            leading=13,
            leftIndent=10,
            rightIndent=10,
            spaceBefore=6,
            spaceAfter=6,
            backColor=LIGHT_GRAY,
            borderPadding=10,
        ),
    }


# ── Page Header / Footer ──────────────────────────────────────────────────────

def _add_page_header_footer(canvas, doc):
    """Add header line and footer to every page."""
    canvas.saveState()

    # Header bar
    canvas.setFillColor(NAVY)
    canvas.rect(0, letter[1] - 35, letter[0], 35, fill=True, stroke=False)
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(30, letter[1] - 24, "🛡️ RepGuard — Reputation Audit Report")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(letter[0] - 30, letter[1] - 24, f"Confidential")

    # Footer
    canvas.setFillColor(MID_GRAY)
    canvas.setFont("Helvetica", 8)
    canvas.drawCentredString(
        letter[0] / 2, 20,
        f"Page {doc.page} — Generated by RepGuard v0.1.0 — {datetime.now().strftime('%B %d, %Y')}",
    )

    canvas.restoreState()


# ── Stars Rendering ────────────────────────────────────────────────────────────

def _stars_text(rating: int) -> str:
    """Generate a text representation of star rating."""
    return "★" * rating + "☆" * (5 - rating)


# ── Risk Score Label ───────────────────────────────────────────────────────────

def _risk_label(score: float) -> tuple[str, str]:
    """Return (label, style_key) for a risk score."""
    if score >= 0.7:
        return "HIGH RISK", "risk_high"
    elif score >= 0.4:
        return "MODERATE RISK", "risk_medium"
    else:
        return "LOW RISK", "risk_low"


# ── Report Builder ─────────────────────────────────────────────────────────────

def generate_report(report: AuditReport, output_path: Path | None = None, is_teaser: bool = False) -> Path:
    """Generate a professional PDF audit report.

    Args:
        report: The complete AuditReport data.
        output_path: Custom output path. Defaults to output/<business_name>_audit.pdf.
        is_teaser: If True, limit the report to 3 reviews and add a call to action.

    Returns:
        Path to the generated PDF file.
    """
    if output_path is None:
        safe_name = "".join(
            c if c.isalnum() or c in " -_" else ""
            for c in report.business_name
        ).strip().replace(" ", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = OUTPUT_DIR / f"{safe_name}_audit_{timestamp}.pdf"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    styles = _build_styles()

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        topMargin=50,
        bottomMargin=40,
        leftMargin=40,
        rightMargin=40,
    )

    story: list = []

    # ── Cover Page ─────────────────────────────────────────────────────────

    story.append(Spacer(1, 1.5 * inch))
    story.append(Paragraph("🛡️", styles["cover_title"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph("REPUTATION AUDIT REPORT", styles["cover_title"]))
    story.append(Spacer(1, 0.3 * inch))
    story.append(
        HRFlowable(
            width="40%", thickness=2, color=ACCENT_BLUE,
            spaceAfter=20, hAlign="CENTER",
        )
    )
    story.append(Paragraph(report.business_name, styles["cover_title"]))

    if report.business_address:
        story.append(Paragraph(report.business_address, styles["cover_subtitle"]))

    if report.business_rating:
        story.append(
            Paragraph(
                f"Current Rating: {_stars_text(int(round(report.business_rating)))} "
                f"({report.business_rating:.1f}/5.0)",
                styles["cover_subtitle"],
            )
        )

    story.append(Spacer(1, 0.5 * inch))
    story.append(
        Paragraph(
            f"Report Generated: {report.generated_at.strftime('%B %d, %Y at %I:%M %p')}",
            styles["cover_subtitle"],
        )
    )
    story.append(Paragraph("Prepared by RepGuard™", styles["cover_subtitle"]))

    # Risk score badge
    story.append(Spacer(1, 0.8 * inch))
    risk_label, risk_style = _risk_label(report.overall_risk_score)
    story.append(Paragraph(f"Overall Assessment: {risk_label}", styles[risk_style]))
    story.append(
        Paragraph(
            f"Risk Score: {report.overall_risk_score:.0%}",
            styles["cover_subtitle"],
        )
    )

    story.append(PageBreak())

    # ── Executive Summary ──────────────────────────────────────────────────

    story.append(Paragraph("Executive Summary", styles["section_heading"]))
    story.append(
        HRFlowable(
            width="100%", thickness=1, color=ACCENT_BLUE,
            spaceAfter=12, hAlign="LEFT",
        )
    )

    if report.attack_analysis and report.attack_analysis.is_under_attack:
        story.append(
            Paragraph(
                "🚨 COORDINATED ATTACK DETECTED 🚨",
                ParagraphStyle(
                    "attack_banner",
                    parent=styles["Normal"],
                    fontName="Helvetica-Bold",
                    fontSize=14,
                    textColor=WHITE,
                    backColor=RED,
                    alignment=TA_CENTER,
                    spaceBefore=10,
                    spaceAfter=5,
                    borderPadding=8,
                )
            )
        )
        story.append(
            Paragraph(
                report.attack_analysis.attack_summary,
                ParagraphStyle(
                    "attack_desc",
                    parent=styles["Normal"],
                    fontName="Helvetica",
                    fontSize=11,
                    textColor=RED,
                    spaceBefore=5,
                    spaceAfter=15,
                )
            )
        )

    summary_data = [
        ["Metric", "Value"],
        ["Total Reviews Analyzed", str(report.total_reviews_scraped)],
        ["Reviews Flagged as Suspicious", str(len(report.flagged_reviews))],
        ["Clean Reviews", str(report.clean_reviews_count)],
        [
            "Fraud Detection Rate",
            f"{len(report.flagged_reviews) / max(report.total_reviews_scraped, 1) * 100:.1f}%",
        ],
        ["Overall Risk Score", f"{report.overall_risk_score:.0%}"],
    ]

    summary_table = Table(summary_data, colWidths=[3 * inch, 3 * inch])
    summary_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, MID_GRAY),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GRAY]),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ])
    )
    story.append(summary_table)
    story.append(Spacer(1, 0.3 * inch))

    if not report.flagged_reviews:
        story.append(
            Paragraph(
                "✅ <b>No suspicious reviews were detected.</b> "
                "Your online reputation appears healthy based on our analysis. "
                "We recommend scheduling regular audits to maintain this status.",
                styles["body"],
            )
        )
    else:
        story.append(
            Paragraph(
                f"⚠️ <b>Our analysis identified {len(report.flagged_reviews)} review(s) "
                f"with suspicious characteristics.</b> "
                f"Each flagged review is detailed below with our AI's reasoning "
                f"and recommended dispute strategy.",
                styles["body"],
            )
        )

    story.append(PageBreak())

    # ── Flagged Reviews Detail ─────────────────────────────────────────────

    if report.flagged_reviews:
        story.append(Paragraph("Flagged Reviews — Detailed Analysis", styles["section_heading"]))
        story.append(
            HRFlowable(
                width="100%", thickness=1, color=RED,
                spaceAfter=12, hAlign="LEFT",
            )
        )

        display_reviews = report.flagged_reviews
        if is_teaser:
            display_reviews = report.flagged_reviews[:3]

        for idx, result in enumerate(display_reviews, 1):
            review = result.review
            analysis = result.analysis

            # Review header
            story.append(
                Paragraph(
                    f"Review #{idx} — {_stars_text(review.rating)} by {review.reviewer_name}",
                    styles["sub_heading"],
                )
            )
            story.append(
                Paragraph(f"Posted: {review.date}", styles["body"])
            )

            # Confidence badge
            conf_pct = f"{analysis.confidence_score:.0%}"
            conf_color = "red" if analysis.confidence_score >= 0.8 else "orange"
            story.append(
                Paragraph(
                    f'<font color="{conf_color}"><b>Fraud Confidence: {conf_pct}</b></font> '
                    f'| Action: <b>{analysis.recommended_action.value.replace("_", " ").title()}</b>',
                    styles["body"],
                )
            )
            story.append(Spacer(1, 6))

            # Quoted review text
            review_text = review.text if review.text else "<i>(No text provided)</i>"
            story.append(Paragraph(f'"{review_text}"', styles["quote"]))
            story.append(Spacer(1, 6))

            # Fraud indicators
            if analysis.fraud_indicators:
                story.append(Paragraph("Fraud Indicators:", styles["body_bold"]))
                for indicator in analysis.fraud_indicators:
                    story.append(
                        Paragraph(f"🚩 {indicator}", styles["indicator_bad"])
                    )
                story.append(Spacer(1, 6))

            # AI reasoning
            story.append(Paragraph("AI Analysis:", styles["body_bold"]))
            story.append(Paragraph(analysis.reasoning, styles["body"]))

            # Separator between reviews
            story.append(Spacer(1, 8))
            story.append(
                HRFlowable(
                    width="80%", thickness=0.5, color=MID_GRAY,
                    spaceAfter=12, hAlign="CENTER",
                )
            )

        if is_teaser and len(report.flagged_reviews) > 3:
            hidden_count = len(report.flagged_reviews) - 3
            story.append(Spacer(1, 15))
            story.append(
                Paragraph(
                    f"🔒 {hidden_count} Additional Fake Reviews Hidden 🔒",
                    ParagraphStyle(
                        "cta_banner",
                        parent=styles["Normal"],
                        fontName="Helvetica-Bold",
                        fontSize=14,
                        textColor=WHITE,
                        backColor=DARK_BLUE,
                        alignment=TA_CENTER,
                        spaceBefore=10,
                        spaceAfter=5,
                        borderPadding=10,
                    )
                )
            )
            story.append(
                Paragraph(
                    "This is a limited preview report. We have identified multiple other highly suspicious reviews dragging down your online reputation. Contact us to receive the full, unlocked audit report and to begin the removal process.",
                    ParagraphStyle(
                        "cta_desc",
                        parent=styles["Normal"],
                        fontName="Helvetica",
                        fontSize=11,
                        textColor=DARK_TEXT,
                        alignment=TA_CENTER,
                        spaceBefore=5,
                        spaceAfter=15,
                    )
                )
            )
            
        story.append(PageBreak())

    if is_teaser:
        # Build the final doc and exit early to skip dispute templates
        doc.build(story, onFirstPage=_add_page_header_footer, onLaterPages=_add_page_header_footer)
        return output_path

    # ── Dispute Templates ──────────────────────────────────────────────────

    story.append(Paragraph("Dispute Templates", styles["section_heading"]))
    story.append(
        HRFlowable(
            width="100%", thickness=1, color=ACCENT_BLUE,
            spaceAfter=12, hAlign="LEFT",
        )
    )
    story.append(
        Paragraph(
            "Below are pre-written dispute templates you can submit directly to "
            "Google Maps Support. Copy the text, fill in any [BRACKETED] placeholders, "
            "and submit via Google Business Profile → Reviews → Flag as inappropriate.",
            styles["body"],
        )
    )
    story.append(Spacer(1, 12))

    # Load dispute template
    template_text = _load_dispute_template(report.business_name)
    story.append(Paragraph("Google Maps Review Dispute Template:", styles["body_bold"]))
    story.append(Spacer(1, 4))

    # Wrap long lines in the template for PDF rendering
    for line in template_text.split("\n"):
        if line.strip():
            story.append(Paragraph(line, styles["dispute_text"]))
        else:
            story.append(Spacer(1, 4))

    # ── Final Page ─────────────────────────────────────────────────────────

    story.append(Spacer(1, 0.5 * inch))
    story.append(
        HRFlowable(
            width="100%", thickness=1, color=NAVY,
            spaceAfter=12, hAlign="LEFT",
        )
    )
    story.append(
        Paragraph(
            "<b>Next Steps:</b> If you would like RepGuard to manage the full dispute "
            "process, monitor your reviews 24/7, and deploy immediate counter-measures "
            "when new attacks are detected, contact us to discuss a retainer plan.",
            styles["body"],
        )
    )
    story.append(Spacer(1, 0.3 * inch))
    story.append(
        Paragraph(
            "This report was generated by RepGuard™ — AI-Powered Reputation Defense. "
            "The analysis is provided for informational purposes. Review fraud determinations "
            "are probabilistic assessments, not legal findings.",
            styles["footer"],
        )
    )

    # Build the PDF
    doc.build(story, onFirstPage=_add_page_header_footer, onLaterPages=_add_page_header_footer)

    console.print(f"\n  [success]📄 Report saved to:[/success] {output_path}")
    return output_path


def _load_dispute_template(business_name: str) -> str:
    """Load the dispute template and fill in the business name."""
    template_path = TEMPLATES_DIR / "dispute_template.txt"

    if template_path.exists():
        template = template_path.read_text()
    else:
        template = _default_dispute_template()

    return template.replace("[BUSINESS_NAME]", business_name)


def _default_dispute_template() -> str:
    """Fallback dispute template if the file doesn't exist."""
    return (
        "Subject: Request for Removal of Fraudulent Review\n"
        "\n"
        "Dear Google Maps Support Team,\n"
        "\n"
        "I am writing to formally request the removal of a review posted on our\n"
        "Google Business Profile for [BUSINESS_NAME]. After careful analysis,\n"
        "we believe this review violates Google's review policies.\n"
        "\n"
        "The review in question was posted by [REVIEWER_NAME] on [DATE].\n"
        "\n"
        "We believe this review is fraudulent because:\n"
        "- [REASON_1]\n"
        "- [REASON_2]\n"
        "\n"
        "This review violates Google's policies on:\n"
        "- Fake engagement (policy section 3.4)\n"
        "- Spam and fake content\n"
        "\n"
        "We respectfully request that this review be investigated and removed.\n"
        "\n"
        "Thank you for your attention to this matter.\n"
        "\n"
        "Sincerely,\n"
        "[YOUR_NAME]\n"
        "[BUSINESS_NAME]\n"
    )
