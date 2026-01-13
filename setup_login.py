from playwright.sync_api import sync_playwright
import time

# Configuration
SESSION_FILE = "instagram_session.json"

def login_and_save_session():
    with sync_playwright() as p:
        # Launch browser (Headless=False so you can see it and type password)
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        print("🚀 Opening Instagram...")
        page.goto("https://www.instagram.com/")

        print("⚠️ ACTION REQUIRED: Please log in manually in the browser window.")
        print("⏳ Waiting for you to reach the Home Feed...")

        # We wait until we see a specific element that only appears when logged in
        # (e.g., the 'Home' icon or 'Search' icon in the sidebar)
        try:
            # Wait up to 300 seconds (5 minutes) for you to log in
            page.wait_for_selector("svg[aria-label='Home']", timeout=300000)
        except:
            print("❌ Timed out waiting for login. Please try again.")
            browser.close()
            return

        print("✅ Login detected!")
        
        # Give it a few seconds to ensure all cookies are set
        time.sleep(5)

        # SAVE THE SESSION
        context.storage_state(path=SESSION_FILE)
        print(f"💾 Session saved to: {SESSION_FILE}")
        print("🎉 You can now run the scraper script without logging in!")

        browser.close()

if __name__ == "__main__":
    login_and_save_session()