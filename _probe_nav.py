import asyncio, sys
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page(viewport={"width": 1300, "height": 900})
        try:
            # fresh load (no cache)
            await page.goto("https://mutxriterminal.com/?nocache=" + str(int(asyncio.get_event_loop().time()*1000)%99999), timeout=40000, wait_until="domcontentloaded")
            await page.wait_for_timeout(8000)
            state = await page.evaluate("""() => {
                const ctas = [...document.querySelectorAll('.nav-cta button, .nav-cta a')].map(b => b.textContent.trim());
                const heroBtns = [...document.querySelectorAll('.hero-cta button, .hero-cta a')].map(b => b.textContent.trim());
                const allText = document.body.innerText;
                return {
                    navCtas: ctas,
                    heroCtas: heroBtns,
                    hasOldGetAccess: allText.includes("Get Access"),
                    hasNewGetAccess: allText.includes("Get a demo")
                };
            }""")
            print("FRESH LOAD NAV:", state)
            # screenshot for proof
            await page.screenshot(path=r"D:\mutxri-terminal\_nav_proof.png")
            print("screenshot saved")
        except Exception as e:
            print("ERR:", str(e)[:300])
        await browser.close()

asyncio.run(main())
