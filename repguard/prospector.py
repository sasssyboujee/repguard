"""Prospector module for finding leads (businesses) on Google Maps."""

from __future__ import annotations

import asyncio
from urllib.parse import quote_plus
from playwright.async_api import async_playwright, Page, TimeoutError as PwTimeout
from playwright_stealth import Stealth

from repguard.utils import console, PROJECT_ROOT


async def _scroll_results_pane(page: Page, limit: int):
    """Scroll the search results pane to load more businesses."""
    # The scrollable pane in Google Maps search results usually has role="feed"
    feed_locator = page.locator("div[role='feed']")
    try:
        await feed_locator.wait_for(timeout=10000)
    except PwTimeout:
        console.print("  [warning]⚠ Could not find results feed to scroll.[/warning]")
        return

    # Scroll down a few times
    for _ in range(min(5, limit // 5 + 1)):
        try:
            await feed_locator.evaluate("el => el.scrollTop = el.scrollHeight")
            await asyncio.sleep(1.5)
        except Exception:
            break


async def find_businesses(query: str, limit: int = 5, headless: bool = True) -> list[str]:
    """Search Google Maps for a query and return a list of business URLs."""
    urls = []
    
    # Use session storage if available to avoid consent popups
    session_file = PROJECT_ROOT / "session.json"
    
    async with Stealth().use_async(async_playwright()) as p:
        browser_opts = {
            "headless": headless,
            "args": ["--disable-blink-features=AutomationControlled"],
            "channel": "chrome",
        }
        browser = await p.chromium.launch(**browser_opts)
        
        context_opts = {"viewport": {"width": 1280, "height": 800}}
        if session_file.exists():
            context_opts["storage_state"] = str(session_file)
            
        context = await browser.new_context(**context_opts)
        page = await context.new_page()
        
        console.print(f"  → Searching Google Maps for: [cyan]{query}[/cyan]")
        encoded_query = quote_plus(query)
        search_url = f"https://www.google.com/maps/search/{encoded_query}/"
        
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)  # Wait for map and initial results to render
            
            # Scroll to load enough results
            await _scroll_results_pane(page, limit)
            
            # Extract links
            # Google Maps business links in search results often use the class 'hfpxzc'
            links = page.locator("a.hfpxzc")
            count = await links.count()
            
            for i in range(min(count, limit)):
                href = await links.nth(i).get_attribute("href")
                if href and "maps/place" in href:
                    urls.append(href)
                    
        except Exception as e:
            console.print(f"  [danger]✗ Failed to search Google Maps: {e}[/danger]")
        finally:
            await browser.close()
            
    # Deduplicate while preserving order
    unique_urls = list(dict.fromkeys(urls))
    return unique_urls
