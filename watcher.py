import os
import json
import time
import shutil
import traceback
import requests

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ============================================================
# CONFIGURATION
# ============================================================

ROS_URL = "https://www.ros.ie/tis/pbn-status-web/pbnStatus/index.html"
WATCHLIST_FILE = "watchlist.json"
GOOGLE_CHAT_WEBHOOK = os.environ.get("GOOGLE_CHAT_WEBHOOK")

# ============================================================
# GOOGLE CHAT
# ============================================================

def send_google_chat(message):
    """Send a message to Google Chat."""
    if not GOOGLE_CHAT_WEBHOOK:
        print("GOOGLE_CHAT_WEBHOOK is not configured.")
        return

    try:
        response = requests.post(
            GOOGLE_CHAT_WEBHOOK,
            json={"text": message},
            timeout=20
        )

        if response.status_code >= 300:
            print(
                f"Google Chat webhook returned "
                f"{response.status_code}: {response.text}"
            )
        else:
            print("Google Chat notification sent.")

    except Exception as e:
        print(f"Failed to send Google Chat notification: {e}")

# ============================================================
# BROWSER SETUP
# ============================================================

def find_chromium():
    """Locate Chromium binary on Ubuntu runner."""
    possible_paths = [
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/snap/bin/chromium",
    ]
    for path in possible_paths:
        if path and os.path.exists(path):
            return path
    return None

def create_driver():
    """Create a headless Chromium Selenium driver."""
    options = Options()

    # Headless mode for GitHub Actions
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    chromium_path = find_chromium()
    if chromium_path:
        print(f"Using Chromium binary at: {chromium_path}")
        options.binary_location = chromium_path
    else:
        print("Chromium binary not found explicitly. Relying on Selenium Manager.")

    print("Starting Chromium...")
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)

    return driver

# ============================================================
# ROS PBN CHECK
# ============================================================

def get_page_text(driver):
    """Return all visible page text."""
    try:
        return driver.find_element(By.TAG_NAME, "body").text.upper()
    except Exception:
        return ""

def check_pbn_status(driver, pbn):
    """Check a single PBN on the ROS website."""
    print("")
    print("=" * 60)
    print(f"Checking PBN: {pbn}")
    print("=" * 60)

    try:
        driver.get(ROS_URL)
        wait = WebDriverWait(driver, 30)

        print("ROS page loaded.")

        # Wait for ROS Angular PBN input element
        input_element = wait.until(
            EC.presence_of_element_located((By.ID, "pbn"))
        )

        print("PBN input found.")
        input_element.clear()
        input_element.send_keys(pbn)
        print(f"Entered PBN: {pbn}")

        # Wait for submit button and click via JS
        button = wait.until(
            EC.presence_of_element_located((By.ID, "submitPbn"))
        )
        print("Check Status button found.")

        driver.execute_script("arguments[0].click();", button)
        print("Check Status clicked.")

        # Allow Angular DOM update
        time.sleep(5)

        page_text = get_page_text(driver)

        print("")
        print("ROS RESPONSE:")
        print("-" * 60)
        print(page_text[:5000])
        print("-" * 60)

        return page_text, driver

    except Exception as e:
        print("")
        print(f"ERROR checking PBN {pbn}")
        print(str(e))
        traceback.print_exc()

        try:
            screenshot_name = f"error_{pbn.replace('/', '_')}.png"
            html_name = f"error_{pbn.replace('/', '_')}.html"

            driver.save_screenshot(screenshot_name)
            with open(html_name, "w", encoding="utf-8") as f:
                f.write(driver.page_source)

            print(f"Saved diagnostic screenshot: {screenshot_name}")
            print(f"Saved diagnostic HTML: {html_name}")

        except Exception as debug_error:
            print(f"Could not save diagnostic files: {debug_error}")

        return None, driver

def is_cleared(page_text):
    """Determine whether ROS reports clearance."""
    if not page_text:
        return False

    text = page_text.upper()
    return "EXIT THE PORT" in text or "EXIT PORT" in text

def load_watchlist():
    """Load watchlist.json."""
    if not os.path.exists(WATCHLIST_FILE):
        print("watchlist.json not found.")
        return []

    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            print("watchlist.json does not contain a list.")
            return []

        return data

    except Exception as e:
        print(f"Could not read watchlist.json: {e}")
        return []

def save_watchlist(watchlist):
    """Save remaining watchlist atomically."""
    temporary_file = WATCHLIST_FILE + ".tmp"

    try:
        with open(temporary_file, "w", encoding="utf-8") as f:
            json.dump(watchlist, f, indent=2, ensure_ascii=False)

        os.replace(temporary_file, WATCHLIST_FILE)
        print("watchlist.json updated.")

    except Exception as e:
        print(f"Could not save watchlist.json: {e}")
        if os.path.exists(temporary_file):
            try:
                os.remove(temporary_file)
            except Exception:
                pass

# ============================================================
# MAIN
# ============================================================

def main():
    print("")
    print("=" * 60)
    print("PBN WATCHER STARTING")
    print("=" * 60)

    watchlist = load_watchlist()

    if not watchlist:
        print("Watchlist is empty.")
        return

    print(f"Loaded {len(watchlist)} watchlist item(s).")

    driver = None
    remaining_items = []

    try:
        driver = create_driver()

        for item in watchlist:
            pbn = (
                item.get("pbn")
                or item.get("PBN")
                or item.get("pbn_id")
                or item.get("PBN_ID")
            )

            trailer = (
                item.get("trailer")
                or item.get("Trailer")
                or item.get("registration")
                or item.get("Registration")
                or item.get("reg")
                or item.get("REG")
                or "Unknown"
            )

            if not pbn:
                print(f"Skipping item with no PBN: {item}")
                remaining_items.append(item)
                continue

            page_text, driver = check_pbn_status(driver, str(pbn))

            if page_text is None:
                remaining_items.append(item)
                continue

            if is_cleared(page_text):
                print("")
                print("🟢 CLEARANCE DETECTED")
                print(f"Trailer: {trailer}")
                print(f"PBN: {pbn}")

                message = (
                    "🟢 *PBN CLEARANCE ALERT*\n\n"
                    f"🚛 *Trailer/Reg:* {trailer}\n"
                    f"📄 *PBN:* {pbn}\n"
                    f"📍 *Status:* *EXIT THE PORT*\n\n"
                    "✅ Unit cleared and removed from active watchlist."
                )

                send_google_chat(message)
            else:
                print("")
                print("🟡 Still active / not cleared")
                print(f"Trailer: {trailer}")
                print(f"PBN: {pbn}")

                remaining_items.append(item)

    except Exception as e:
        print("")
        print("FATAL ERROR")
        print(str(e))
        traceback.print_exc()
        remaining_items = watchlist

    finally:
        if driver:
            try:
                driver.quit()
                print("Browser closed.")
            except Exception:
                pass

    save_watchlist(remaining_items)

    print("")
    print("=" * 60)
    print("PBN WATCHER FINISHED")
    print("=" * 60)
    print(f"Items originally checked: {len(watchlist)}")
    print(f"Items remaining: {len(remaining_items)}")
    print("")

if __name__ == "__main__":
    main()
