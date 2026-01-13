from flask import Flask, render_template, request, jsonify
from playwright.sync_api import sync_playwright
from concurrent.futures import ThreadPoolExecutor
import time
import os
import re

app = Flask(__name__)

# ---------------- CONFIGURATION ---------------- #
SESSION_FILE = "instagram_session.json"
MAX_WORKERS = 3 
# ----------------------------------------------- #

def identify_url_type(url):
    if "/reel/" in url: return "REEL"
    if "/p/" in url: return "POST"
    if url.strip("/") == "https://www.instagram.com": return "SYSTEM"
    if "/explore/" in url or "/direct/" in url or "/stories/" in url: return "SYSTEM"
    if "instagram.com/" in url: return "PROFILE"
    return "UNKNOWN"

# --- HELPER: RECURSIVE SEARCH ---
def find_username_in_json(obj):
    if isinstance(obj, dict):
        if "owner" in obj and isinstance(obj["owner"], dict):
            if "username" in obj["owner"]: return obj["owner"]["username"]
        if "username" in obj and "is_verified" in obj: return obj["username"]
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                res = find_username_in_json(v)
                if res: return res
    elif isinstance(obj, list):
        for item in obj:
            res = find_username_in_json(item)
            if res: return res
    return None

def scrape_single_url(url):
    if not url or not url.strip(): return None

    with sync_playwright() as p:
        # 🔥 STEALTH CONFIGURATION FOR CLOUD SERVERS 🔥
        browser = p.chromium.launch(
            headless=True,  # Must be True for Hugging Face
            args=["--disable-blink-features=AutomationControlled"] # Hides "bot" flag
        )
        
        # Inject "Real Human" User-Agent (Windows Chrome)
        context_args = {
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "viewport": {"width": 1280, "height": 720},
            "locale": "en-US"
        }
        
        if os.path.exists(SESSION_FILE):
            context = browser.new_context(storage_state=SESSION_FILE, **context_args)
        else:
            context = browser.new_context(**context_args)
        
        page = context.new_page()
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

        if data["type"] in ["SYSTEM", "UNKNOWN"]:
            data["status"] = "Skipped"
            browser.close()
            return data

        try:
            if data["type"] == "PROFILE":
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(3)
                try:
                    followers_link = page.locator("a[href*='/followers/']").first
                    if followers_link.count() > 0:
                        title = followers_link.locator("span[title]").first
                        if title.count() > 0:
                            data["followers"] = title.get_attribute("title")
                        else:
                            data["followers"] = followers_link.inner_text().split("\n")[0]
                except: pass
                data["author"] = url.strip("/").split("/")[-1]
                data["status"] = "Success"

            elif data["type"] in ["REEL", "POST"]:
                if "/reel/" in url:
                    shortcode = url.split("/reel/")[1].split("/")[0]
                else:
                    shortcode = url.split("/p/")[1].split("/")[0]

                captured_info = {"username": None}
                
                def handle_response(response):
                    if "instagram.com" in response.url and "json" in response.headers.get("content-type", ""):
                        try:
                            json_data = response.json()
                            found = find_username_in_json(json_data)
                            if found and not captured_info["username"]:
                                captured_info["username"] = found
                        except: pass

                page.on("response", handle_response)
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(4) 
                page.remove_listener("response", handle_response)

                try:
                    meta_desc = page.locator('meta[property="og:description"]').get_attribute("content")
                    if meta_desc:
                        likes_match = re.search(r'^([0-9,.]+[KkMm]?) likes', meta_desc)
                        if likes_match: data["likes"] = likes_match.group(1)
                except: pass

                if captured_info["username"]: 
                    data["author"] = captured_info["username"]
                
                if not data["author"]:
                    try:
                        title = page.title()
                        match = re.search(r'\(@(.*?)\)', title) 
                        if match: data["author"] = match.group(1)
                        else:
                            match_b = re.search(r'^(.*?)\son\sInstagram', title)
                            if match_b:
                                parts = match_b.group(1).split(" ")
                                if len(parts) == 1: data["author"] = parts[0]
                    except: pass

                if not data["author"]:
                    try:
                        links = page.locator("a[href*='/reels/']").all()
                        for link in links:
                            href = link.get_attribute("href")
                            if href:
                                parts = href.strip("/").split("/")
                                if len(parts) >= 2 and parts[-1] == "reels":
                                    candidate = parts[-2]
                                    if candidate not in ["reels", "instagram"]:
                                        data["author"] = candidate
                                        break
                    except: pass

                if data["author"]:
                    is_video = False
                    try:
                        og_type = page.locator('meta[property="og:type"]').get_attribute("content")
                        if og_type and "video" in og_type: is_video = True
                    except: pass
                    if data["type"] == "REEL": is_video = True

                    if is_video:
                        profile_reels_url = f"https://www.instagram.com/{data['author']}/reels/"
                        page.goto(profile_reels_url, wait_until="domcontentloaded")
                        time.sleep(3)
                        
                        if "/reels/" not in page.url:
                            data["views"] = "Hidden (Main Grid)"
                        else:
                            try:
                                target_selector = f"a[href*='{shortcode}']"
                                page.wait_for_selector(target_selector, timeout=8000)
                                target_card = page.locator(target_selector).first
                                card_text = target_card.inner_text()
                                for line in card_text.split('\n'):
                                    if any(char.isdigit() for char in line):
                                        data["views"] = line.strip()
                                        break
                            except:
                                data["views"] = "Not Found"
                    else:
                        data["views"] = "N/A (Photo)"
                    
                    try:
                        fol_link = page.locator("a[href*='/followers/']").first
                        if fol_link.count() > 0:
                            title = fol_link.locator("span[title]").first
                            if title.count() > 0:
                                data["followers"] = title.get_attribute("title")
                    except: pass
                    
                    data["status"] = "Success"
                else:
                    data["status"] = "Failed (No Author)"

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
    
    print(f"🔥 API Request: Processing {len(final_urls)} links...")

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        results_iterator = executor.map(scrape_single_url, final_urls)
        for res in results_iterator:
            if res: results.append(res)

    return jsonify(results)

if __name__ == '__main__':
    # HUGGING FACE REQUIRES PORT 7860
    app.run(host='0.0.0.0', port=7860)