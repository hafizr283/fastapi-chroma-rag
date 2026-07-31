"""Drive the Streamlit UI end-to-end and capture what a user actually sees.

Types a question, clicks "Get Answer", waits for the result to render, then
screenshots and dumps the visible text. Used to verify the 503 (LLM
unavailable) path surfaces a readable message rather than raw JSON.

Usage:  python ui_query_test.py "your question" out.png
"""
import sys
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8501"
QUESTION = sys.argv[1] if len(sys.argv) > 1 else "Who is the supervisor of this thesis?"
OUT = sys.argv[2] if len(sys.argv) > 2 else "ui_query.png"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1100})

        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.wait_for_selector('[data-testid="stAppViewContainer"]', timeout=45000)
        page.wait_for_timeout(3000)

        box = page.locator('[data-testid="stTextInput"] input').first
        box.scroll_into_view_if_needed()
        # Streamlit's input sits under a transient overlay right after hydration,
        # so fill() can fail the editability check. Click and type instead.
        box.click(force=True)
        page.keyboard.type(QUESTION, delay=15)
        print(f"typed: {QUESTION}")

        page.get_by_role("button", name="Get Answer").click()
        print("clicked Get Answer")

        # Streamlit reruns the script; the spinner must appear and clear before
        # the result is on screen.
        page.wait_for_timeout(2000)
        for _ in range(60):
            if page.locator('[data-testid="stSpinner"]').count() == 0:
                break
            page.wait_for_timeout(1000)
        page.wait_for_timeout(2000)

        page.screenshot(path=OUT, full_page=True)

        text = page.inner_text("body")
        print("\n=== VISIBLE TEXT AFTER QUERY ===")
        print(text)

        print("\n=== ALERT ROLES ===")
        for tid in ("stAlertContainer", "stException"):
            n = page.locator(f'[data-testid="{tid}"]').count()
            print(f"  {tid}: {n}")

        print("\n=== JS ERRORS ===")
        for e in errors or ["(none)"]:
            print(" ", e)

        print(f"\nScreenshot -> {OUT}")
        browser.close()


if __name__ == "__main__":
    main()
