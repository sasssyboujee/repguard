import asyncio
import re
from playwright.async_api import async_playwright

async def main():
    url = "https://maps.app.goo.gl/Yq7ZdKfsQtdHbYDh9"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="en-US"
        )
        page = await context.new_page()
        print(f"Navigating to {url}...")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(5)
            print(f"Redirected URL: {page.url}")
            print(f"Page Title: {await page.title()}")
            
            # Check for consent screen
            consent_buttons = await page.locator('button').all()
            print(f"Total buttons found: {len(consent_buttons)}")
            for i, btn in enumerate(consent_buttons[:15]):
                txt = await btn.inner_text()
                role = await btn.get_attribute("role")
                aria = await btn.get_attribute("aria-label")
                print(f"Button {i}: text='{txt.strip()}', role='{role}', aria-label='{aria}'")
            
            # Print all role="tab" elements
            tabs = await page.locator('[role="tab"]').all()
            print(f"\nTotal tabs found: {len(tabs)}")
            for i, tab in enumerate(tabs):
                txt = await tab.inner_text()
                aria = await tab.get_attribute("aria-label")
                print(f"Tab {i}: text='{txt.strip()}', aria-label='{aria}'")
                
            # Let's save a screenshot
            screenshot_path = "output/diagnose_screenshot.png"
            await page.screenshot(path=screenshot_path)
            print(f"\nSaved screenshot to {screenshot_path}")
            
        except Exception as e:
            print(f"Error occurred: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
