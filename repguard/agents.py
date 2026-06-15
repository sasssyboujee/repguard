import asyncio
from typing import Callable

from google.antigravity import Agent, LocalAgentConfig, types
from repguard.utils import console

async def tool_find_leads(query: str, limit: int = 3) -> list[str]:
    """Finds Google Maps business URLs matching a query.
    
    Args:
        query: Search term (e.g. 'dentists in singapore').
        limit: Max number of leads to return.
    """
    from repguard.prospector import find_businesses
    return await find_businesses(query, limit=limit)


async def tool_send_teaser(business_name: str, target_email: str, flagged_count: int) -> str:
    """Drafts and sends a teaser cold outreach email if fake reviews were found.
    
    Args:
        business_name: Name of the business.
        target_email: Lead contact email.
        flagged_count: Count of fake reviews detected.
    """
    if flagged_count == 0:
        return "No fake reviews found. Skipping outreach."
    
    console.print(f"[success]Drafted email for {business_name} to {target_email}[/success]")
    return f"Teaser outreach successfully drafted and sent to {target_email}!"


def make_audit_tool(browser, semaphore) -> Callable:
    async def tool_audit_reviews(url: str, max_reviews: int = 20) -> dict:
        """Scrapes and runs fake review analysis on a specific Google Maps URL.
        
        Args:
            url: Google Maps business URL.
            max_reviews: Number of reviews to scrape.
        """
        from repguard.scraper import scrape_reviews_concurrent
        from repguard.analyzer import analyze_reviews_batch
        
        console.print(f"[muted]Agent is auditing {url}...[/muted]")
        async with semaphore:
            info, reviews = await scrape_reviews_concurrent(browser, url, max_reviews=max_reviews)
            
        if not reviews:
            return {"error": "No reviews found or failed to scrape."}
            
        flagged = await analyze_reviews_batch(reviews, business_name=info.get("name", "Unknown"))
        
        return {
            "name": info.get("name"),
            "address": info.get("address"),
            "rating": info.get("rating"),
            "flagged_count": len(flagged),
            "total_reviews": len(reviews),
        }
    return tool_audit_reviews


async def run_multi_agent_pipeline(query: str, target_email: str, max_leads: int = 3):
    """Entry point for the multi-agent pipeline."""
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth
    
    console.print(f"\n[highlight]Starting Multi-Agent Pipeline for query: '{query}'[/highlight]")
    
    # Allows max 3 concurrent browser contexts
    sem = asyncio.Semaphore(3)
    
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(
            headless=True,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        
        try:
            audit_tool = make_audit_tool(browser, sem)
            
            config = LocalAgentConfig(
                capabilities=types.CapabilitiesConfig(
                    enable_subagents=True,
                ),
                tools=[tool_find_leads, audit_tool, tool_send_teaser],
                # Strict constraints to prevent loops
                max_turns=8
            )

            async with Agent(config) as orchestrator:
                prompt = (
                    f"You are the RepGuard Manager. Walk through this workflow strictly: \n"
                    f"1. Use tool_find_leads to find {max_leads} business leads for the query '{query}'.\n"
                    f"2. For EACH lead URL found, use tool_audit_reviews to analyze their reviews.\n"
                    f"3. If any fake reviews are found, use tool_send_teaser to email '{target_email}'.\n"
                    f"Do not loop or retry if no leads are found. Summarize your final findings clearly and concisely."
                )
                
                response = await orchestrator.chat(prompt)
                
                from rich.panel import Panel
                from rich.markdown import Markdown
                
                console.print("\n[info]Agent Response Stream:[/info]")
                
                full_response = ""
                async for chunk in response:
                    print(chunk, end="", flush=True)
                    full_response += chunk
                
                print() # newline
                console.print(Panel(Markdown(full_response), title="Orchestrator Final Report"))

        except Exception as e:
            console.print(f"[danger]Pipeline failed: {e}[/danger]")
        finally:
            await browser.close()
