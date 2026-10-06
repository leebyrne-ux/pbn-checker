import os
import json
import time
import shutil
import traceback
import requests

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ============================================================
# CONFIGURATION
# ============================================================

ROS_URL = "https://www.ros.ie/customs-roro-control-web/ros/pbn/status"
WATCHLIST_FILE = "watchlist.json"

MAX_RETRIES = 3
PAGE_LOAD_TIMEOUT = 45
RESULT_WAIT_TIMEOUT = 30


# ============================================================
# GOOGLE CHAT
# ============================================================

def get_google_chat_webhook():
    return os.getenv("GOOGLE_CHAT_WEBHOOK")


def send_google_chat_notification(webhook_url, trailer, pbn, status_text):
    """Send a notification to Google Chat when a PBN clears."""
    message = {
        "text": (
            "🟢 *PBN CLEARANCE ALERT*\n\n"
            f"🚛 *Trailer / Reg:* {trailer}\n"
            f"📄 *PBN:* {pbn}\n"
            f"📍 *Status:* *{status_text}*\n\n"
            "✅ Unit cleared and removed from active watchlist."
        )
    }

    try:
        response = requests.post(
            webhook_url,
            json=message,
            timeout=15,
        )
        response.raise_for_status()
        print(f"✅ Google Chat notification sent for {trailer} ({pbn}).")
    except Exception as error:
        print(f"⚠️ Failed to send Google Chat notification: {type(error).__name__}: {error}")


# ============================================================
# BROWSER SETUP
# ============================================================

def find_chromium():
    """Try to locate Chromium on the GitHub Actions runner."""
    possible_paths = [
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/snap/bin/chromium",
    ]

    for path in possible_paths:
        if path and os.path.exists(path):
            print(f"✅ Chromium found at: {path}")
            return path

    print("⚠️ Chromium binary could not be located. Driver will attempt default lookup.")
    return None


def create_driver():
    """Create a fresh Chrome/Chromium Selenium driver."""
    print("Starting Chromium...")
    options = webdriver.ChromeOptions()

    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-sync")

    chromium_path = find_chromium()
    if chromium_path:
        options.binary_location = chromium_path

    try:
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        print("✅ Chromium started successfully.")
        return driver
    except Exception as error:
        print("❌ Failed to start Chromium.")
        print(f"Exception message: {error!r}")
        traceback.print_exc()
        raise


# ============================================================
# DEBUGGING
# ============================================================

def save_debug_files(driver, pbn_id, attempt):
    """Save screenshot and HTML whenever a ROS check fails."""
    if not driver:
        return

    safe_pbn = "".join(c for character in pbn_id if (c := character).isalnum())
    screenshot_file = f"debug_{safe_pbn}_attempt_{attempt}.png"
    html_file = f"debug_{safe_pbn}_attempt_{attempt}.html"

    try:
        driver.save_screenshot(screenshot_file)
        print(f"  📸 Debug screenshot saved: {screenshot_file}")
    except Exception as error:
        print(f"  Could not save screenshot: {error!r}")

    try:
        with open(html_file, "w", encoding="utf-8") as file:
            file.write(driver.page_source)
        print(f"  📄 Debug HTML saved: {html_file}")
    except Exception as error:
        print(f"  Could not save HTML: {error!r}")


# ============================================================
# ROS PAGE INTERACTION
# ============================================================

def wait_for_ros_page(driver):
    """Open ROS page and return PBN input element once visible."""
    print(f"Opening ROS page: {ROS_URL}")
    driver.get(ROS_URL)
    wait = WebDriverWait(driver, RESULT_WAIT_TIMEOUT)

    input_box = wait.until(
        EC.visibility_of_element_located((By.XPATH, "//input[not(@type='hidden')]"))
    )
    print("✅ PBN input found.")
    return input_box


def find_check_button(driver):
    """Locate the ROS Check Status button via normalized text matching."""
    wait = WebDriverWait(driver, RESULT_WAIT_TIMEOUT)
    button = wait.until(
        EC.element_to_be_clickable(
            (
                By.XPATH,
                "//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'check status')]"
            )
        )
    )
    print("✅ Check Status button found.")
    return button


# ============================================================
# PBN CHECK
# ============================================================

def check_pbn_status(driver, pbn_id):
    """Check one PBN on Revenue ROS with retry logic."""
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"  Attempt {attempt}/{MAX_RETRIES} for PBN {pbn_id}")

        try:
            input_box = wait_for_ros_page(driver)
            input_box.clear()
            input_box.send_keys(pbn_id)
            print("  PBN entered.")

            submit_button = find_check_button(driver)
            driver.execute_script("arguments[0].click();", submit_button)
            print("  Check Status clicked.")

            # Wait until status text or indicators render
            wait = WebDriverWait(driver, RESULT_WAIT_TIMEOUT)

            def result_has_loaded(d):
                text = d.find_element(By.TAG_NAME, "body").text.strip().upper()
                indicators = [
                    "EXIT THE PORT",
                    "CALL TO CUSTOMS",
                    "CALL TO CUSTOMS - TRANSIT",
                    "CALL TO CUSTOMS - SEAL",
                    "GOOD TO PROCEED TO CHECK-IN",
                    "PROCEED",
                    "PBN STATUS",
                    "PBN ID",
                    "STATUS",
                ]
                return any(ind in text for ind in indicators)

            wait.until(result_has_loaded)
            time.sleep(1)

            page_text = driver.find_element(By.TAG_NAME, "body").text.strip()
            if not page_text:
                raise RuntimeError("ROS returned an empty page.")

            print("  ✅ ROS returned a result.")
            return driver, page_text

        except Exception as error:
            last_error = error
            print(f"  ⚠️ Attempt {attempt} failed.")
            print(f"  Error type: {type(error).__name__}")
            print(f"  Error: {error!r}")

            save_debug_files(driver, pbn_id, attempt)

            if attempt < MAX_RETRIES:
                print("  Retrying in 5 seconds...")
                time.sleep(5)
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = create_driver()
            else:
                print(f"❌ All {MAX_RETRIES} attempts failed for PBN {pbn_id}.")

    raise last_error


# ============================================================
# STATUS INTERPRETATION
# ============================================================

def is_cleared(page_text):
    """Determine whether the PBN has received an Exit the Port channel."""
    text = page_text.upper()
    if "EXIT THE PORT" in text:
        return True, "Exit the Port"
    return False, None


def print_status_summary(page_text):
    """Print ROS response summary to logs."""
    print("\n---------- ROS RESPONSE ----------")
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    for line in lines:
        print(line)
    print("-------- END ROS RESPONSE --------\n")


# ============================================================
# MAIN EXECUTION
# ============================================================

def main():
    print("\n========================================")
    print("        ROS PBN WATCHER")
    print("========================================\n")

    webhook_url = get_google_chat_webhook()
    print("Google Chat webhook: " + ("CONFIGURED" if webhook_url else "MISSING"))

    if not os.path.exists(WATCHLIST_FILE):
        print(f"❌ {WATCHLIST_FILE} not found.")
        return

    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as file:
            watchlist = json.load(file)
    except Exception as error:
        print(f"❌ Could not read {WATCHLIST_FILE}: {type(error).__name__}: {error}")
        return

    if not watchlist:
        print("Watchlist is empty. Nothing to check.")
        return

    print(f"Loaded {len(watchlist)} item(s) from watchlist.")

    driver = None
    remaining_watchlist = []

    try:
        driver = create_driver()

        for item in watchlist:
            pbn = str(item.get("pbn", "")).strip()
            trailer = str(item.get("trailer", "Unknown")).strip()

            if not pbn:
                print("⚠️ Watchlist item has no PBN. Keeping item.")
                remaining_watchlist.append(item)
                continue

            print("\n========================================")
            print(f"Checking Trailer: {trailer}")
            print(f"PBN: {pbn}")
            print("========================================")

            try:
                driver, page_text = check_pbn_status(driver, pbn)
                print_status_summary(page_text)

                cleared, status = is_cleared(page_text)

                if cleared:
                    print(f"🟢 CLEARANCE DETECTED for {trailer} ({pbn})!")
                    if webhook_url:
                        send_google_chat_notification(
                            webhook_url, trailer, pbn, status
                        )
                    else:
                        print("⚠️ Cleared, but webhook is missing.")
                else:
                    print(f"⏳ Still pending for {trailer} ({pbn}).")
                    remaining_watchlist.append(item)

            except Exception as error:
                print(f"\n❌ ERROR checking PBN {pbn}")
                print(f"Exception message: {error!r}")
                traceback.print_exc()
                remaining_watchlist.append(item)

    except Exception as fatal_error:
        print(f"\n❌ FATAL BROWSER ERROR: {fatal_error!r}")
        traceback.print_exc()
        remaining_watchlist = watchlist

    finally:
        if driver:
            try:
                driver.quit()
                print("Browser closed.")
            except Exception:
                pass

    try:
        with open(WATCHLIST_FILE, "w", encoding="utf-8") as file:
            json.dump(remaining_watchlist, file, indent=2, ensure_ascii=False)

        print("\n========================================")
        print("Watchlist updated successfully.")
        print(f"Before: {len(watchlist)} item(s)")
        print(f"After:  {len(remaining_watchlist)} item(s)")
        print("========================================\n")

    except Exception as error:
        print(f"❌ Could not save watchlist: {type(error).__name__}: {error}")
        raise


if __name__ == "__main__":
    main()
