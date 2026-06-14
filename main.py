"""RepGuard CLI — AI-Powered Fake Review Detection & Reputation Defense.

Usage:
    # Full audit on a Google Maps business
    python main.py audit "https://maps.google.com/...?cid=..." --max-reviews 50

    # Quick-test: analyze a single review text
    python main.py analyze "This place is terrible, worst experience ever"

    # Batch audit from a file of URLs
    python main.py batch urls.txt --output ./reports/
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from repguard.models import AuditReport
from repguard.utils import console, print_banner, OUTPUT_DIR, SUSPICION_THRESHOLD


def cmd_audit(args: argparse.Namespace) -> None:
    """Run a full audit on a single Google Maps business."""
    from repguard.scraper import scrape_reviews_sync
    from repguard.analyzer import analyze_reviews_batch
    from repguard.report import generate_report

    print_banner()
    console.print("[highlight]Mode: Full Audit[/highlight]\n")

    # Step 1: Scrape reviews
    console.rule("[bold cyan]Step 1 — Scraping Reviews[/bold cyan]")
    business_info, reviews = scrape_reviews_sync(
        url=args.url,
        max_reviews=args.max_reviews,
        headless=not args.visible,
    )

    if not reviews:
        console.print("\n[warning]No reviews found. Check the URL and try again.[/warning]")
        return

    # Step 2: Analyze with LLM
    console.rule("[bold cyan]Step 2 — AI Fraud Analysis[/bold cyan]")
    flagged = asyncio.run(
        analyze_reviews_batch(
            reviews=reviews,
            business_name=business_info.get("name", "Unknown"),
            business_category=args.category or "General Business",
            filter_low_ratings=not args.analyze_all,
            use_prefilter=not args.no_prefilter,
        )
    )

    # Step 3: Build report data
    total = len(reviews)
    flagged_count = len(flagged)
    clean_count = total - flagged_count

    # Calculate overall risk score
    if flagged:
        avg_confidence = sum(r.analysis.confidence_score for r in flagged) / flagged_count
        risk_score = min(1.0, (flagged_count / max(total, 1)) * 2 * avg_confidence)
    else:
        risk_score = 0.0

    # Detect coordinated attacks
    from repguard.attack_detector import analyze_attack_patterns
    attack_analysis = analyze_attack_patterns(reviews, flagged)

    report = AuditReport(
        business_name=business_info.get("name", "Unknown Business"),
        business_url=args.url,
        business_address=business_info.get("address"),
        business_rating=business_info.get("rating"),
        total_reviews_scraped=total,
        flagged_reviews=flagged,
        clean_reviews_count=clean_count,
        attack_analysis=attack_analysis,
        generated_at=datetime.now(),
        overall_risk_score=risk_score,
    )

    # Step 4: Generate Report and Assets
    console.rule("[bold cyan]Step 3 — Generating Report & Assets[/bold cyan]")
    output_path = Path(args.output) if args.output else None
    pdf_path = generate_report(report, output_path)
    
    dispute_files = []
    outreach_file = None
    if flagged:
        from repguard.generator import generate_dispute_letters, generate_outreach_email
        dispute_files = generate_dispute_letters(report)
        outreach_file = generate_outreach_email(report)

    # Summary
    console.print()
    console.rule("[bold green]Audit Complete[/bold green]")
    console.print(f"  [info]Business:[/info]     {report.business_name}")
    console.print(f"  [info]Reviews:[/info]      {total} scraped")
    console.print(f"  [info]Suspicious:[/info]   {flagged_count}")
    console.print(f"  [info]Clean:[/info]        {clean_count}")
    console.print(f"  [info]Risk Score:[/info]   {risk_score:.0%}")
    console.print(f"  [info]Report:[/info]       {pdf_path}")
    
    if flagged:
        console.print(f"  [info]Disputes:[/info]     {len(dispute_files)} letters generated")
        console.print(f"  [info]Outreach:[/info]     {outreach_file}")
    console.print()


def cmd_analyze(args: argparse.Namespace) -> None:
    """Quick-test: analyze a single review text against the LLM."""
    from repguard.analyzer import analyze_single_review_sync

    print_banner()
    console.print("[highlight]Mode: Single Review Analysis[/highlight]\n")

    console.print(f'[info]Review text:[/info] "{args.text}"')
    console.print(f"[info]Rating:[/info]       {args.rating}★")
    console.print(f"[info]Business:[/info]     {args.business}\n")

    console.rule("[bold cyan]AI Analysis[/bold cyan]")

    try:
        analysis = analyze_single_review_sync(
            review_text=args.text,
            rating=args.rating,
            business_name=args.business,
        )
    except EnvironmentError as e:
        console.print(f"\n[danger]✗ {e}[/danger]")
        return
    except RuntimeError as e:
        console.print(f"\n[danger]✗ {e}[/danger]")
        console.print("[warning]Tip: Gemini may be overloaded. Wait a minute and try again.[/warning]")
        return

    # Display results
    console.print()
    if analysis.is_suspicious:
        console.print(
            f"[danger]🚩 SUSPICIOUS — Confidence: {analysis.confidence_score:.0%}[/danger]"
        )
    else:
        console.print(
            f"[success]✓ LIKELY LEGITIMATE — Confidence of fraud: {analysis.confidence_score:.0%}[/success]"
        )

    console.print(f"\n[info]Recommended Action:[/info] {analysis.recommended_action.value.replace('_', ' ').title()}")

    if analysis.fraud_indicators:
        console.print(f"\n[info]Fraud Indicators:[/info]")
        for indicator in analysis.fraud_indicators:
            console.print(f"  [danger]🚩 {indicator}[/danger]")

    console.print(f"\n[info]Reasoning:[/info]")
    console.print(f"  {analysis.reasoning}")
    console.print()


def cmd_batch(args: argparse.Namespace) -> None:
    """Run audits on multiple businesses from a URL list file."""
    from repguard.scraper import scrape_reviews_sync
    from repguard.analyzer import analyze_reviews_batch
    from repguard.report import generate_report

    print_banner()
    console.print("[highlight]Mode: Batch Audit[/highlight]\n")

    urls_file = Path(args.file)
    if not urls_file.exists():
        console.print(f"[danger]✗ File not found: {urls_file}[/danger]")
        return

    urls = [
        line.strip()
        for line in urls_file.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    console.print(f"[info]Found {len(urls)} URLs to audit[/info]\n")

    output_dir = Path(args.output) if args.output else OUTPUT_DIR

    for i, url in enumerate(urls, 1):
        console.rule(f"[bold cyan]Business {i}/{len(urls)}[/bold cyan]")

        try:
            business_info, reviews = scrape_reviews_sync(
                url=url,
                max_reviews=args.max_reviews,
                headless=True,
            )

            if not reviews:
                console.print("[warning]  No reviews found, skipping.[/warning]\n")
                continue

            flagged = asyncio.run(
                analyze_reviews_batch(
                    reviews=reviews,
                    business_name=business_info.get("name", "Unknown"),
                    use_prefilter=not args.no_prefilter,
                )
            )

            total = len(reviews)
            flagged_count = len(flagged)

            if flagged:
                avg_conf = sum(r.analysis.confidence_score for r in flagged) / flagged_count
                risk_score = min(1.0, (flagged_count / max(total, 1)) * 2 * avg_conf)
            else:
                risk_score = 0.0

            from repguard.attack_detector import analyze_attack_patterns
            attack_analysis = analyze_attack_patterns(reviews, flagged)

            report = AuditReport(
                business_name=business_info.get("name", "Unknown"),
                business_url=url,
                business_address=business_info.get("address"),
                business_rating=business_info.get("rating"),
                total_reviews_scraped=total,
                flagged_reviews=flagged,
                clean_reviews_count=total - flagged_count,
                attack_analysis=attack_analysis,
                generated_at=datetime.now(),
                overall_risk_score=risk_score,
            )

            generate_report(report, output_dir / f"audit_{i}.pdf")

        except Exception as e:
            console.print(f"[danger]✗ Failed: {e}[/danger]\n")
            continue

    console.print(f"\n[success]Batch audit complete. Reports saved to {output_dir}[/success]\n")


def cmd_train_filter(args: argparse.Namespace) -> None:
    """Train the local pre-filter model using the logged dataset."""
def cmd_prospect(args: argparse.Namespace) -> None:
    """Search Google Maps for leads, scrape reviews, and generate outreach materials."""
    from repguard.prospector import find_businesses
    from repguard.scraper import scrape_reviews_sync
    from repguard.analyzer import analyze_reviews_batch
    from repguard.report import generate_report
    from repguard.generator import generate_dispute_letters, generate_outreach_email
    import time

    print_banner()
    console.rule(f"[bold cyan]Prospecting: {args.query}[/bold cyan]")
    
    # 1. Find leads
    console.print(f"\n[bold]Step 1: Finding Businesses...[/bold]")
    urls = asyncio.run(find_businesses(args.query, limit=args.limit, headless=not args.visible))
    
    if not urls:
        console.print("[warning]⚠ No businesses found for that query.[/warning]")
        return
        
    console.print(f"  [success]✓ Found {len(urls)} target businesses[/success]\n")
    
    from repguard.db import has_been_audited, record_audit

    # 2. Process each lead
    for idx, url in enumerate(urls):
        console.rule(f"[bold yellow]Lead {idx+1}/{len(urls)}[/bold yellow]")
        
        if has_been_audited(url):
            console.print("  [muted]Skipping: Business has already been audited recently.[/muted]")
            continue
            
        try:
            # Scrape
            business_info, reviews = scrape_reviews_sync(url, max_reviews=args.max_reviews, headless=not args.visible)
            if not reviews:
                console.print("  [muted]No reviews found, skipping...[/muted]")
                record_audit(business_info.get("name", "Unknown"), url, business_info.get("rating"), 0.0, 0)
                continue
                
            # Analyze
            flagged = asyncio.run(
                analyze_reviews_batch(
                    reviews=reviews,
                    business_name=business_info.get("name", "Unknown"),
                    filter_low_ratings=True,
                    use_prefilter=True,
                )
            )
            
            # Generate materials if fake reviews found
            if flagged:
                console.print(f"  [bold green]★ OPPORTUNITY FOUND: {len(flagged)} fake reviews![/bold green]")
                
                # Build Report
                total = len(reviews)
                avg_conf = sum(r.analysis.confidence_score for r in flagged) / len(flagged)
                risk_score = min(1.0, (len(flagged) / max(total, 1)) * 2 * avg_conf)
                
                from repguard.attack_detector import analyze_attack_patterns
                attack_analysis = analyze_attack_patterns(reviews, flagged)

                report = AuditReport(
                    business_name=business_info.get("name", "Unknown"),
                    business_url=url,
                    business_address=business_info.get("address"),
                    business_rating=business_info.get("rating"),
                    total_reviews_scraped=total,
                    flagged_reviews=flagged,
                    clean_reviews_count=total - len(flagged),
                    attack_analysis=attack_analysis,
                    generated_at=datetime.now(),
                    overall_risk_score=risk_score,
                )
                
                # Output
                output_path = Path("leads") / report.business_name.replace(" ", "_")
                output_path.mkdir(parents=True, exist_ok=True)
                
                pdf_path = generate_report(report, str(output_path))
                generate_dispute_letters(report)
                outreach_email = generate_outreach_email(report)
                
                console.print(f"  [success]✓ Outreach package saved to: {output_path}[/success]")
                
                # Auto-email dispatch
                if hasattr(args, "notify_email") and args.notify_email:
                    from repguard.mailer import send_outreach_email
                    
                    with open(outreach_email, "r", encoding="utf-8") as f:
                        email_content = f.read()
                        
                    # Extract subject from the generated text file
                    subject_line = "Urgent: Fake Reviews Found"
                    lines = email_content.split("\n")
                    if lines[0].startswith("Subject:"):
                        subject_line = lines[0].replace("Subject:", "").strip()
                        email_content = "\n".join(lines[1:]).strip()
                        
                    send_outreach_email(
                        to_email=args.notify_email,
                        subject=subject_line,
                        body=email_content,
                        attachments=[pdf_path]
                    )
                
                record_audit(report.business_name, url, report.business_rating, risk_score, len(flagged))
            else:
                console.print("  [muted]No fake reviews found. Clean profile.[/muted]")
                record_audit(business_info.get("name", "Unknown"), url, business_info.get("rating"), 0.0, 0)
                
        except Exception as e:
            console.print(f"  [warning]⚠ Failed to process lead: {e}[/warning]")
            
        # Rate limit between businesses
        if idx < len(urls) - 1:
            console.print("  [muted]Pausing before next lead...[/muted]")
            time.sleep(5)


def cmd_train(args: argparse.Namespace) -> None:
    """Train the offline Random Forest model using accumulated review data."""
    from repguard.prefilter import train_prefilter
    print_banner()
    console.rule("[bold cyan]Training ML Prefilter[/bold cyan]")
    
    try:
        model_path = train_prefilter()
        console.print(f"\n  [success]✓ Successfully trained Random Forest model![/success]")
        console.print(f"  [info]Model saved to:[/info] {model_path}")
        console.print("  [muted]RepGuard will automatically use this model for future audits to save API tokens.[/muted]\n")
    except Exception as e:
        console.print(f"\n  [danger]✗ Training failed:[/danger] {e}\n")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="repguard",
        description="🛡️ RepGuard — AI-Powered Fake Review Detection & Reputation Defense",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── audit ──────────────────────────────────────────────────────────────
    p_audit = subparsers.add_parser(
        "audit",
        help="Run a full audit on a Google Maps business",
    )
    p_audit.add_argument(
        "url",
        help="Google Maps URL of the business to audit",
    )
    p_audit.add_argument(
        "--max-reviews", "-n",
        type=int,
        default=50,
        help="Maximum number of reviews to scrape (default: 50)",
    )
    p_audit.add_argument(
        "--category", "-c",
        type=str,
        default=None,
        help="Business category for better analysis context (e.g., 'Restaurant', 'Law Firm')",
    )
    p_audit.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Custom output path for the PDF report",
    )
    p_audit.add_argument(
        "--visible",
        action="store_true",
        help="Show the browser window during scraping (for debugging)",
    )
    p_audit.add_argument(
        "--analyze-all",
        action="store_true",
        help="Analyze all reviews, not just low-rated ones",
    )
    p_audit.add_argument(
        "--no-prefilter",
        action="store_true",
        help="Disable local NLP pre-filter and analyze all matching reviews with Gemini",
    )
    p_audit.set_defaults(func=cmd_audit)

    # ── analyze ────────────────────────────────────────────────────────────
    p_analyze = subparsers.add_parser(
        "analyze",
        help="Quick-test: analyze a single review text",
    )
    p_analyze.add_argument(
        "text",
        help="The review text to analyze",
    )
    p_analyze.add_argument(
        "--rating", "-r",
        type=int,
        default=1,
        choices=[1, 2, 3, 4, 5],
        help="Star rating of the review (default: 1)",
    )
    p_analyze.add_argument(
        "--business", "-b",
        type=str,
        default="Test Business",
        help="Business name for context (default: 'Test Business')",
    )
    p_analyze.set_defaults(func=cmd_analyze)

    # ── batch ──────────────────────────────────────────────────────────────
    p_batch = subparsers.add_parser(
        "batch",
        help="Run audits on multiple businesses from a URL list",
    )
    p_batch.add_argument(
        "file",
        help="Path to a text file with one Google Maps URL per line",
    )
    p_batch.add_argument(
        "--max-reviews", "-n",
        type=int,
        default=30,
        help="Max reviews per business (default: 30)",
    )
    p_batch.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output directory for reports (default: ./output/)",
    )
    p_batch.add_argument(
        "--no-prefilter",
        action="store_true",
        help="Disable local NLP pre-filter and analyze all matching reviews with Gemini",
    )
    p_batch.set_defaults(func=cmd_batch)

    # ── train-filter ───────────────────────────────────────────────────────
    p_train = subparsers.add_parser(
        "train-filter",
        help="Train the local Random Forest pre-filter using collected labeled data",
    )
    p_train.set_defaults(func=cmd_train_filter)

    # ── prospect ───────────────────────────────────────────────────────────
    prospect_parser = subparsers.add_parser("prospect", help="Automatically find target businesses and audit them")
    prospect_parser.add_argument("query", help="Search query (e.g., 'yoga studios in singapore')")
    prospect_parser.add_argument("--limit", type=int, default=3, help="Max businesses to process (default: 3)")
    prospect_parser.add_argument("--max-reviews", type=int, default=20, help="Max reviews to scrape per business (default: 20)")
    prospect_parser.add_argument("--visible", action="store_true", help="Run browser in visible mode")
    prospect_parser.add_argument("--notify-email", type=str, help="Email address to send the generated leads to (e.g., your own inbox)")
    prospect_parser.set_defaults(func=cmd_prospect)

    return parser


def main() -> None:
    """Entry point for the RepGuard CLI."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        print_banner()
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
