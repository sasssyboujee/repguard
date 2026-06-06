"""Google Maps review scraper using Playwright.

Navigates to a Google Maps business page, opens the Reviews tab,
sorts by Newest, scrolls to load reviews, and extracts structured data.
"""

from __future__ import annotations

import asyncio
import random
import re

from playwright.async_api import Page, async_playwright, TimeoutError as PwTimeout

from repguard.models import Review
from repguard.utils import console, DEFAULT_MAX_REVIEWS


# ── Selectors ──────────────────────────────────────────────────────────────────
# Google Maps DOM selectors (as of mid-2025). These may change over time.

SEL_REVIEWS_TAB = 'button[role="tab"]:has-text("Reviews")'
SEL_SORT_BUTTON = 'button[aria-label="Sort reviews"]'
SEL_SORT_NEWEST = 'div[role="menuitemradio"]:has-text("Newest")'
SEL_REVIEW_CARD = 'div[data-review-id]'
SEL_REVIEWER_NAME = 'div.d4r55'
SEL_REVIEWER_LINK = 'a[data-review-id]'
SEL_STAR_RATING = 'span[role="img"][aria-label*="star"]'
SEL_REVIEW_TEXT = 'span.wiI7pd'
SEL_REVIEW_DATE = 'span.rsqaWe'
SEL_MORE_BUTTON = 'button.w8nwRe'
SEL_OWNER_RESPONSE = 'div.CDe7pd'
SEL_SCROLLABLE_PANEL = 'div.m6QErb.DxyBCb'
SEL_BUSINESS_NAME = 'h1.DUwDvf'
SEL_BUSINESS_RATING = 'div.F7nice span[aria-hidden="true"]'
SEL_BUSINESS_ADDRESS = 'button[data-item-id="address"] div.fontBodyMedium'


async def _random_delay(min_ms: int = 300, max_ms: int = 800) -> None:
    """Human-like random delay to avoid detection."""
    await asyncio.sleep(random.randint(min_ms, max_ms) / 1000)


async def _extract_business_info(page: Page) -> dict:
    """Extract business name, rating, and address from the page."""
    info: dict = {}

    try:
        name_el = page.locator(SEL_BUSINESS_NAME).first
        info["name"] = await name_el.inner_text(timeout=5000)
    except (PwTimeout, Exception):
        info["name"] = "Unknown Business"

    try:
        rating_el = page.locator(SEL_BUSINESS_RATING).first
        rating_text = await rating_el.inner_text(timeout=3000)
        info["rating"] = float(rating_text.strip())
    except (PwTimeout, ValueError, Exception):
        info["rating"] = None

    try:
        addr_el = page.locator(SEL_BUSINESS_ADDRESS).first
        info["address"] = await addr_el.inner_text(timeout=3000)
    except (PwTimeout, Exception):
        info["address"] = None

    return info


async def _click_reviews_tab(page: Page) -> None:
    """Click the Reviews tab to open the reviews panel."""
    console.print("  [muted]→ Clicking Reviews tab...[/muted]")
    try:
        tab = page.locator(SEL_REVIEWS_TAB).first
        await tab.click(timeout=10000)
        await _random_delay(800, 1500)
    except PwTimeout:
        # Fallback: try clicking by text
        await page.get_by_role("tab", name=re.compile(r"Reviews", re.IGNORECASE)).click(timeout=10000)
        await _random_delay(800, 1500)


async def _sort_by_newest(page: Page) -> None:
    """Sort reviews by 'Newest' using the sort dropdown."""
    console.print("  [muted]→ Sorting by Newest...[/muted]")
    try:
        sort_btn = page.locator(SEL_SORT_BUTTON).first
        await sort_btn.click(timeout=8000)
        await _random_delay(500, 1000)

        newest_opt = page.locator(SEL_SORT_NEWEST).first
        await newest_opt.click(timeout=5000)
        await _random_delay(1000, 2000)
    except PwTimeout:
        console.print("  [warning]⚠ Could not find sort button — proceeding with default order[/warning]")


async def _scroll_reviews(page: Page, max_reviews: int) -> None:
    """Scroll the reviews panel to load more reviews."""
    console.print(f"  [muted]→ Scrolling to load up to {max_reviews} reviews...[/muted]")

    scrollable = page.locator(SEL_SCROLLABLE_PANEL).first
    previous_count = 0
    stale_rounds = 0

    for _ in range(max_reviews // 3 + 5):  # rough upper bound on scroll iterations
        current_count = await page.locator(SEL_REVIEW_CARD).count()

        if current_count >= max_reviews:
            break

        if current_count == previous_count:
            stale_rounds += 1
            if stale_rounds >= 3:
                console.print(f"  [muted]→ No more reviews to load (found {current_count})[/muted]")
                break
        else:
            stale_rounds = 0

        previous_count = current_count

        try:
            await scrollable.evaluate("el => el.scrollTop = el.scrollHeight")
        except Exception:
            # Fallback: keyboard scroll
            await page.keyboard.press("End")

        await _random_delay(600, 1200)


async def _expand_review_text(page: Page) -> None:
    """Click all 'More' buttons to expand truncated review text."""
    more_buttons = page.locator(SEL_MORE_BUTTON)
    count = await more_buttons.count()

    for i in range(count):
        try:
            await more_buttons.nth(i).click(timeout=2000)
            await _random_delay(100, 300)
        except (PwTimeout, Exception):
            continue


async def _extract_reviews(page: Page, max_reviews: int) -> list[Review]:
    """Parse review cards from the DOM into Review models."""
    reviews: list[Review] = []
    cards = page.locator(SEL_REVIEW_CARD)
    count = min(await cards.count(), max_reviews)

    for i in range(count):
        card = cards.nth(i)

        try:
            # Reviewer name
            name = "Anonymous"
            try:
                name_el = card.locator(SEL_REVIEWER_NAME).first
                name = await name_el.inner_text(timeout=2000)
            except (PwTimeout, Exception):
                pass

            # Reviewer profile URL
            reviewer_url = None
            try:
                link_el = card.locator("button.WEBjve").first
                reviewer_url = await link_el.get_attribute("data-href", timeout=2000)
            except (PwTimeout, Exception):
                pass

            # Star rating
            rating = 1
            try:
                star_el = card.locator(SEL_STAR_RATING).first
                aria = await star_el.get_attribute("aria-label", timeout=2000)
                if aria:
                    match = re.search(r"(\d)", aria)
                    if match:
                        rating = int(match.group(1))
            except (PwTimeout, Exception):
                pass

            # Review text
            text = ""
            try:
                text_el = card.locator(SEL_REVIEW_TEXT).first
                text = await text_el.inner_text(timeout=2000)
            except (PwTimeout, Exception):
                pass

            # Date
            date = "Unknown"
            try:
                date_el = card.locator(SEL_REVIEW_DATE).first
                date = await date_el.inner_text(timeout=2000)
            except (PwTimeout, Exception):
                pass

            # Owner response
            response = None
            try:
                resp_el = card.locator(SEL_OWNER_RESPONSE).first
                response = await resp_el.inner_text(timeout=2000)
            except (PwTimeout, Exception):
                pass

            # Review ID
            review_id = await card.get_attribute("data-review-id")

            reviews.append(
                Review(
                    reviewer_name=name.strip(),
                    reviewer_url=reviewer_url,
                    rating=rating,
                    text=text.strip(),
                    date=date.strip(),
                    response=response.strip() if response else None,
                    review_id=review_id,
                )
            )

        except Exception as e:
            console.print(f"  [warning]⚠ Failed to parse review {i + 1}: {e}[/warning]")
            continue

    return reviews


async def scrape_reviews(
    url: str,
    max_reviews: int = DEFAULT_MAX_REVIEWS,
    headless: bool = True,
) -> tuple[dict, list[Review]]:
    """Scrape Google Maps reviews for a business.

    Args:
        url: Google Maps URL for the business.
        max_reviews: Maximum number of reviews to scrape.
        headless: Run browser in headless mode (set False for debugging).

    Returns:
        Tuple of (business_info_dict, list_of_reviews).
    """
    console.print(f"\n[info]🔍 Scraping reviews from:[/info] {url}")
    console.print(f"[info]   Target: up to {max_reviews} reviews[/info]\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        page = await context.new_page()

        try:
            # Navigate to the business page
            console.print("  [muted]→ Loading page...[/muted]")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await _random_delay(2000, 3000)

            # Accept cookies/consent if prompted
            try:
                consent = page.locator('button:has-text("Accept all")')
                if await consent.count() > 0:
                    await consent.first.click(timeout=3000)
                    await _random_delay(500, 1000)
            except (PwTimeout, Exception):
                pass

            # Extract business info
            business_info = await _extract_business_info(page)
            console.print(f"  [success]✓ Business:[/success] {business_info['name']}")
            if business_info.get("rating"):
                console.print(f"  [success]✓ Rating:[/success] {business_info['rating']}★")

            # Click reviews tab
            await _click_reviews_tab(page)

            # Sort by newest
            await _sort_by_newest(page)

            # Scroll to load reviews
            await _scroll_reviews(page, max_reviews)

            # Expand truncated reviews
            await _expand_review_text(page)

            # Extract review data
            console.print("  [muted]→ Extracting review data...[/muted]")
            reviews = await _extract_reviews(page, max_reviews)

            console.print(f"\n  [success]✓ Successfully scraped {len(reviews)} reviews[/success]")

            # Summary stats
            if reviews:
                avg_rating = sum(r.rating for r in reviews) / len(reviews)
                one_star = sum(1 for r in reviews if r.rating == 1)
                console.print(f"  [info]  Average rating: {avg_rating:.1f}★[/info]")
                console.print(f"  [info]  1-star reviews: {one_star}[/info]")

            return business_info, reviews

        except Exception as e:
            console.print(f"\n[danger]✗ Scraping failed: {e}[/danger]")
            raise
        finally:
            await browser.close()


def scrape_reviews_sync(
    url: str,
    max_reviews: int = DEFAULT_MAX_REVIEWS,
    headless: bool = True,
) -> tuple[dict, list[Review]]:
    """Synchronous wrapper around the async scraper for CLI convenience."""
    return asyncio.run(scrape_reviews(url, max_reviews, headless))
