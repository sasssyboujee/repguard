"""Google Maps review scraper using Playwright.

Navigates to a Google Maps business page, opens the Reviews tab,
sorts by Newest, scrolls to load reviews, and extracts structured data.
"""

from __future__ import annotations

import asyncio
import random
import re
from pathlib import Path

from playwright.async_api import Page, async_playwright, TimeoutError as PwTimeout
from playwright_stealth import Stealth

from repguard.models import Review
from repguard.utils import console, DEFAULT_MAX_REVIEWS

class ScraperOutOfSyncError(Exception):
    """Raised when the scraper extracts empty fields, indicating DOM selectors are outdated."""
    pass


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
        for selector in [SEL_BUSINESS_NAME, 'h1.DUwDvf', 'h1']:
            name_el = page.locator(selector).first
            if await name_el.is_visible(timeout=2000):
                info["name"] = await name_el.inner_text()
                break
        else:
            info["name"] = "Unknown Business"
    except Exception:
        info["name"] = "Unknown Business"

    try:
        for selector in [SEL_BUSINESS_RATING, 'div.F7nice span[aria-hidden="true"]', 'span[aria-label*="stars"]', 'span[role="img"][aria-label*="stars"]']:
            try:
                rating_el = page.locator(selector).first
                if await rating_el.is_visible(timeout=1000):
                    rating_text = await rating_el.inner_text()
                    if rating_text.strip():
                        info["rating"] = float(rating_text.strip())
                        break
                    
                    aria = await rating_el.get_attribute("aria-label")
                    if aria:
                        match = re.search(r'([\d.]+)\s*stars?', aria, re.IGNORECASE)
                        if match:
                            info["rating"] = float(match.group(1))
                            break
            except Exception:
                continue
        else:
            info["rating"] = None
    except Exception:
        info["rating"] = None

    try:
        for selector in [SEL_BUSINESS_ADDRESS, 'button[data-item-id="address"] div', 'button[data-item-id="address"]', 'div.Io6YTe']:
            try:
                addr_el = page.locator(selector).first
                if await addr_el.is_visible(timeout=1000):
                    info["address"] = await addr_el.inner_text()
                    break
            except Exception:
                continue
        else:
            info["address"] = None
    except Exception:
        info["address"] = None

    return info


async def _click_reviews_tab(page: Page) -> None:
    """Click the Reviews tab or review count button to open the reviews panel."""
    console.print("  [muted]→ Clicking Reviews tab...[/muted]")
    
    # Let the UI settle
    await _random_delay(500, 1000)

    selectors_to_try = [
        SEL_REVIEWS_TAB,
        'button[role="tab"]:has-text("Reviews")',
        'div[role="tab"]:has-text("Reviews")',
        'button[data-item-id="review"]',
        'button:has-text("Reviews")',
        'div[role="tab"] button:has-text("Reviews")',
        'button[aria-label*="reviews"]',
        'div.F7nice',  # The whole rating block often acts as a link to reviews
        'span:has-text("reviews")'
    ]
    
    for selector in selectors_to_try:
        try:
            locators = page.locator(selector)
            count = await locators.count()
            for i in range(count):
                el = locators.nth(i)
                if await el.is_visible(timeout=500):
                    # Force click in case it's intercepted by a transparent overlay
                    await el.click(timeout=2000, force=True)
                    await _random_delay(1500, 2500) # Give it time to animate panel in
                    return
        except Exception:
            continue

    # Try aria-label text search as absolute fallback
    try:
        tab = page.get_by_role("tab", name=re.compile(r"Reviews", re.IGNORECASE))
        if await tab.first.is_visible(timeout=2000):
            await tab.first.click(force=True)
            await _random_delay(1500, 2500)
            return
    except Exception:
        pass

    console.print("  [warning]⚠ Could not click Reviews tab. Proceeding in case reviews are already open.[/warning]")


async def _sort_by_lowest_rating(page: Page) -> None:
    """Sort reviews by 'Lowest rating' using the sort dropdown."""
    console.print("  [muted]→ Sorting by Lowest rating...[/muted]")
    try:
        sort_locators = [
            SEL_SORT_BUTTON,
            'button[aria-label="Sort reviews"]',
            'button:has-text("Sort")'
        ]
        
        sort_btn = None
        for sel in sort_locators:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=1000):
                sort_btn = loc
                break
                
        if sort_btn:
            await sort_btn.click(timeout=4000)
            await _random_delay(800, 1200)

            lowest_locators = [
                'div[role="menuitemradio"]:has-text("Lowest rating")',
                'div:has-text("Lowest rating")',
                'div[role="menuitemradio"]:has-text("Lowest")'
            ]
            for sel in lowest_locators:
                newest_opt = page.locator(sel).first
                if await newest_opt.is_visible(timeout=1000):
                    await newest_opt.click(timeout=4000)
                    await _random_delay(1500, 2500)
                    return
    except Exception:
        pass
    console.print("  [warning]⚠ Could not find sort button — proceeding with default order[/warning]")


async def _scroll_reviews(page: Page, max_reviews: int) -> None:
    """Scroll the reviews panel to load more reviews."""
    console.print(f"  [muted]→ Scrolling to load up to {max_reviews} reviews...[/muted]")

    # Find the scrollable panel using multiple selectors
    scrollable = None
    for selector in [SEL_SCROLLABLE_PANEL, 'div[role="feed"]', 'div.m6QErb[tabindex="0"]']:
        locator = page.locator(selector).first
        try:
            if await locator.is_visible(timeout=1500):
                scrollable = locator
                break
        except Exception:
            continue

    if scrollable is None:
        raise ScraperOutOfSyncError("Could not find the scrollable review container. Google Maps UI may have changed.")

    previous_count = 0
    stale_rounds = 0

    for _ in range(max_reviews // 3 + 5):  # rough upper bound on scroll iterations
        # Check review card counts (with fallback)
        current_count = await page.locator(SEL_REVIEW_CARD).count()
        if current_count == 0:
            current_count = await page.locator("div.jftiEf").count()

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
    count = await cards.count()
    if count == 0:
        # Try fallback review class name
        cards = page.locator("div.jftiEf")
        count = await cards.count()

    count = min(count, max_reviews)

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
            review_id = None
            try:
                review_id = await card.get_attribute("data-review-id", timeout=1000)
            except (PwTimeout, Exception):
                pass

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

    # Deduplicate reviews (Google Maps DOM often contains duplicate nodes for accessibility/layout)
    unique_reviews = []
    seen = set()
    for r in reviews:
        # Use review_id if available, otherwise composite key
        key = r.review_id if r.review_id else f"{r.reviewer_name}::{r.text}"
        if key not in seen:
            seen.add(key)
            unique_reviews.append(r)
            
    if unique_reviews:
        empty_count = sum(1 for r in unique_reviews if r.reviewer_name == "Anonymous" and r.date == "Unknown")
        if empty_count / len(unique_reviews) > 0.5:
            raise ScraperOutOfSyncError("More than 50% of extracted reviews are empty. DOM selectors are likely out of sync.")
            
    return unique_reviews


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

    session_file = Path("session.json")
    is_first_run = not session_file.exists()
    
    # If it's the first run, we MUST show the browser so they can log in
    launch_headless = headless if not is_first_run else False

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(
            headless=launch_headless,
            channel="chrome",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        
        context_kwargs = {
            "viewport": {"width": 1280, "height": 900},
            "locale": "en-US",
        }
        if not is_first_run:
            context_kwargs["storage_state"] = str(session_file)
            
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

        if is_first_run:
            console.print("\n[warning]No session.json found. We are launching a visible browser for you to log in.[/warning]")
            console.print("[info]Please log into your Google Account. You have 60 seconds.[/info]")
            
            try:
                await page.goto("https://accounts.google.com/", wait_until="domcontentloaded")
            except Exception:
                pass
                
            for i in range(60, 0, -10):
                console.print(f"  [muted]... {i} seconds remaining to log in ...[/muted]")
                await asyncio.sleep(10)
                
            # Save cookies and local storage
            await context.storage_state(path=str(session_file))
            console.print("[success]✓ Session saved to session.json![/success]\n")

        try:
            # Navigate to the business page
            console.print("  [muted]→ Loading page...[/muted]")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await _random_delay(2000, 3000)

            # Accept cookies/consent if prompted
            try:
                consent_selectors = [
                    'button[aria-label*="Accept all"]',
                    'button[aria-label*="Accept the use of cookies"]',
                    'button:has-text("Accept all")',
                    'button:has-text("I agree")',
                    'button:has-text("Agree")',
                    'button:has-text("Accept")',
                    'form[action*="consent.google"] button',
                ]
                for selector in consent_selectors:
                    try:
                        btn = page.locator(selector).first
                        if await btn.is_visible(timeout=1500):
                            await btn.click()
                            console.print(f"  [muted]→ Bypassed consent screen ('{selector}')[/muted]")
                            await _random_delay(1000, 2000)
                            break
                    except Exception:
                        continue
            except Exception:
                pass

            # Extract business info
            business_info = await _extract_business_info(page)
            console.print(f"  [success]✓ Business:[/success] {business_info['name']}")
            if business_info.get("rating"):
                console.print(f"  [success]✓ Rating:[/success] {business_info['rating']}★")

            # Click reviews tab
            await _click_reviews_tab(page)

            # Sort by lowest rating (since we're hunting for fake negative reviews)
            await _sort_by_lowest_rating(page)

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


async def scrape_reviews_concurrent(
    browser,
    url: str,
    max_reviews: int = DEFAULT_MAX_REVIEWS,
) -> tuple[dict, list[Review]]:
    """Scrape reviews concurrently using a shared browser instance."""
    console.print(f"\n[info]🔍 Scraping reviews concurrently from:[/info] {url}")
    
    session_file = Path("session.json")
    context_kwargs = {
        "viewport": {"width": 1280, "height": 900},
        "locale": "en-US",
    }
    if session_file.exists():
        context_kwargs["storage_state"] = str(session_file)
        
    context = await browser.new_context(**context_kwargs)
    page = await context.new_page()

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await _random_delay(2000, 3000)

        # Accept cookies/consent if prompted
        try:
            consent_selectors = [
                'button[aria-label*="Accept all"]',
                'button[aria-label*="Accept the use of cookies"]',
                'button:has-text("Accept all")',
                'button:has-text("I agree")',
                'button:has-text("Agree")',
                'button:has-text("Accept")',
                'form[action*="consent.google"] button',
            ]
            for selector in consent_selectors:
                try:
                    btn = page.locator(selector).first
                    if await btn.is_visible(timeout=1500):
                        await btn.click()
                        await _random_delay(1000, 2000)
                        break
                except Exception:
                    continue
        except Exception:
            pass

        business_info = await _extract_business_info(page)
        await _click_reviews_tab(page)
        await _sort_by_lowest_rating(page)
        await _scroll_reviews(page, max_reviews)
        await _expand_review_text(page)
        reviews = await _extract_reviews(page, max_reviews)

        return business_info, reviews
    finally:
        await context.close()


def scrape_reviews_sync(
    url: str,
    max_reviews: int = DEFAULT_MAX_REVIEWS,
    headless: bool = True,
) -> tuple[dict, list[Review]]:
    """Synchronous wrapper around the async scraper for CLI convenience."""
    return asyncio.run(scrape_reviews(url, max_reviews, headless))
