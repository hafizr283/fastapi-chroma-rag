"""Playwright smoke probe for the Streamlit UI.

Loads the running Streamlit app, waits for the widget tree to hydrate,
then dumps a screenshot plus the visible text so it can be inspected
without a real browser.

Usage:  python ui_probe.py [url] [out_png]
"""
import sys
from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8501"
OUT = sys.argv[2] if len(sys.argv) > 2 else "ui_shot.png"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})

        console = []
        page.on("console", lambda m: console.append(f"[{m.type}] {m.text}"))
        page.on("pageerror", lambda e: console.append(f"[pageerror] {e}"))

        page.goto(URL, wait_until="networkidle", timeout=60000)

        # Streamlit renders into [data-testid="stAppViewContainer"] over a
        # websocket, so the DOM is empty until the first script run lands.
        page.wait_for_selector('[data-testid="stAppViewContainer"]', timeout=45000)
        page.wait_for_timeout(4000)

        page.screenshot(path=OUT, full_page=True)

        print("=== TITLE ===")
        print(page.title())

        print("\n=== VISIBLE TEXT ===")
        body = page.inner_text("body")
        print(body[:4000])

        print("\n=== INTERACTIVE ELEMENTS ===")
        for tid in ("stFileUploader", "stTextInput", "stTextArea",
                    "stButton", "stSelectbox", "stSlider", "stChatInput"):
            n = page.locator(f'[data-testid="{tid}"]').count()
            if n:
                print(f"  {tid}: {n}")

        print("\n=== CONSOLE ===")
        for line in console[:40] or ["(none)"]:
            print(" ", line)

        print(f"\nScreenshot -> {OUT}")
        browser.close()


if __name__ == "__main__":
    main()
