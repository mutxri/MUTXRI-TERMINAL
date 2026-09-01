import asyncio, sys
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page(viewport={"width": 1300, "height": 900})
        try:
            # verify SBK investor sheet now has all fields filled
            await page.goto("https://mutxriterminal.com/terminal/?ex=JSE&view=info&sym=SBK.JO&v=141414", timeout=45000, wait_until="domcontentloaded")
            await page.wait_for_timeout(15000)
            info = await page.evaluate("""() => {
                const text = document.getElementById("rightInfo") ? document.getElementById("rightInfo").innerText : "";
                return text;
            }""")
            print(info[:1200])
        except Exception as e:
            print("ERR:", str(e)[:300])
        await browser.close()

asyncio.run(main())
