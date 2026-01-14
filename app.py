from flask import Flask, render_template, request, jsonify
from playwright.sync_api import sync_playwright
from concurrent.futures import ThreadPoolExecutor
import time
import os
import re
import json

app = Flask(__name__)

# ---------------- CONFIGURATION ---------------- #
SESSION_FILE = "instagram_session.json"
MAX_WORKERS = 2   # Keep low for Free Tier RAM limits
# ----------------------------------------------- #

def identify_url_type(url):
    if "/reel/" in url: return "REEL"
    if "/p/" in url: return "POST"
    if url.strip("/") == "https://www.instagram.com": return "SYSTEM"
    if "instagram.com/" in url: return "PROFILE"
    return "UNKNOWN"

def safe_find_key(obj, key):
    if isinstance(obj, dict):
        if key in obj: return obj[key]
        for k, v in obj.items():
            res = safe_find_key(v, key)
            if res is not None: return res
    elif isinstance(obj, list):
        for item in obj:
            res = safe_find_key(item, key)
            if res is not None: return res
    return None

def apply_stealth(page):
    """Hide automation flags"""
    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    page.add_init_script("window.navigator.chrome = { runtime: {} };")
    page.add_init_script("Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]})")
    page.add_init_script("Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']})")

def scrape_single_url(url):
    if not url or not url.strip(): return None

    # ✅ FIXED: Start Playwright INSIDE the thread (Prevents Greenlet Error)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions"
            ]
        )
        
        # Lightweight Context
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
            viewport={"width": 412, "height": 915},
            locale="en-US"
        )
        
        # 🔥 SPEED HACK: Block Images, Fonts, CSS to load instantly
        context.route("**/*.{png,jpg,jpeg,gif,webp,svg,css,woff,woff2}", lambda route: route.abort())
        
        page = context.new_page()
        apply_stealth(page)

        print(f"⚡ Processing: {url}")
        data = {
            "url": url,
            "type": identify_url_type(url),
            "author": None,
            "followers": "N/A",
            "likes": "N/A",
            "views": "N/A",
            "status": "Starting"
        }

        # --- NETWORK SNIFFER ---
        captured_data = {"play_count": None, "username": None, "like_count": None}

        def handle_response(response):
            if "instagram.com" in response.url and ("json" in response.headers.get("content-type", "") or "graphql" in response.url):
                try:
                    json_data = response.json()
                    if not captured_data["play_count"]:
                        plays = safe_find_key(json_data, "play_count") or safe_find_key(json_data, "video_view_count")
                        if plays: captured_data["play_count"] = plays
                    if not captured_data["like_count"]:
                        likes = safe_find_key(json_data, "like_count")
                        if likes: captured_data["like_count"] = likes
                    if not captured_data["username"]:
                        user = safe_find_key(json_data, "username")
                        if user: captured_data["username"] = user
                except: pass

        page.on("response", handle_response)

        try:
            # Load page (Fast timeout because we block images)
            page.goto(url, wait_until="domcontentloaded", timeout=25000)

            # Turbo Check: Look for data immediately
            for _ in range(8):
                page.wait_for_timeout(500)
                if captured_data["play_count"] and captured_data["username"]:
                    print("   🚀 Captured Data Instantly!")
                    break
            
            # Fill Data
            if captured_data["play_count"]: data["views"] = str(captured_data["play_count"])
            if captured_data["like_count"]: data["likes"] = str(captured_data["like_count"])
            if captured_data["username"]: data["author"] = captured_data["username"]

            # Exit early if successful
            if data["views"] != "N/A" and data["author"]:
                data["status"] = "Success"
                browser.close()
                return data

            # --- FALLBACK ---
            print("   ⚠️ Switching to Visual Fallback...")
            
            if not data["author"]:
                try:
                    title = page.title()
                    match = re.search(r'\(@(.*?)\)', title)
                    if match: data["author"] = match.group(1)
                except: pass

            if data["views"] == "N/A" and data["type"] == "REEL" and data["author"]:
                if "/reels/" not in page.url:
                    page.goto(f"https://www.instagram.com/{data['author']}/reels/", wait_until="domcontentloaded")
                
                try:
                    shortcode = url.split("/reel/")[1].split("/")[0]
                    card = page.locator(f"a[href*='{shortcode}']").first
                    if card.count() > 0:
                        txt = card.inner_text()
                        for line in txt.split('\n'):
                            if any(c.isdigit() for c in line):
                                data["views"] = line.strip()
                                break
                except: pass

            data["status"] = "Success"

        except Exception as e:
            data["status"] = "Error"
            print(f"❌ Error: {e}")

        browser.close()
        return data

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/scrape', methods=['POST'])
def scrape_api():
    data = request.json
    raw_urls = data.get('urls', [])
    final_urls = []
    
    if isinstance(raw_urls, list):
        raw_string = ",".join(raw_urls)
    else:
        raw_string = str(raw_urls)

    cleaned_items = raw_string.replace('\n', ',').split(',')
    for item in cleaned_items:
        clean_link = item.strip()
        if clean_link:
            final_urls.append(clean_link)

    if not final_urls:
        return jsonify({"error": "No valid URLs provided"}), 400
    
    print(f"🔥 Processing {len(final_urls)} links...")
    results = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        results_iterator = executor.map(scrape_single_url, final_urls)
        for res in results_iterator:
            if res: results.append(res)

    return jsonify(results)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)