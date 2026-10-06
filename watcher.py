import os
import json
import time
import traceback
import shutil
import requests

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


ROS_URL = "https://www.ros.ie/customs-roro-control-web/ros/pbn/status"
WATCHLIST_FILE = "watchlist.json"
GOOGLE_CHAT_WEBHOOK = os.environ.get("GOOGLE_CHAT_WEBHOOK")


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


def create_driver():
    """Create a headless Chromium Selenium driver."""

    options = Options()

    # GitHub Actions / Linux settings
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    # Try to locate Chromium automatically.
    chromium_paths = [
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/snap/bin/chromium",
    ]

    chromium_path = None

    for path in chromium_paths:
        if os.path.exists(path):
            chromium_path = path
            break

    if chromium_path:
        print(f"Using Chromium: {chromium_path}")
        options.binary_location = chromium_path
    else:
        print("Chromium binary not found explicitly.")
        print("Allowing Selenium to locate the browser.")

    print("Starting Chromium...")

    driver = webdriver.Chrome(options=options)

    driver.set_page_load_timeout(60)

    return driver


def get_page_text(driver):
    """Return all visible page text."""

    try:
        return driver.find_element(By.TAG_NAME, "body").text.upper()
    except Exception:
        return ""


def check_pbn_status(driver, pbn):
    """
    Check a single PBN on the ROS website.

    Returns:
        page_text, driver
    """

    print("")
    print("=" * 60)
    print(f"Checking PBN: {pbn}")
    print("=" * 60)

    try:
        driver.get(ROS_URL)

        wait = WebDriverWait(driver, 30)

        print("ROS page loaded.")

        # Find a visible text input.
        input_element = wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//input[not(@type='hidden') "
                    "and not(@type='submit') "
                    "and not(@type='button')]"
                )
            )
        )

        print("PBN input found.")

        input_element.clear()
        input_element.send_keys(pbn)

        print(f"Entered PBN: {pbn}")

        # Look for a button containing "check status".
        button = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[contains("
                    "translate(normalize-space(.), "
                    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                    "'abcdefghijklmnopqrstuvwxyz'), "
                    "'check status')]"
                )
            )
        )

        print("Check Status button found.")

        driver.execute_script(
            "arguments[0].click();",
            button
        )

        print("Check Status clicked.")

        # Give the ROS page time to process the request.
        time.sleep(5)

        # Get the resulting page text.
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

        # Save diagnostic information if possible.
        try:
            screenshot_name = (
                f"error_{pbn.replace('/', '_')}.png"
            )

            html_name = (
                f"error_{pbn.replace('/', '_')}.html"
            )

            driver.save_screenshot(screenshot_name)

            with open(html_name, "w", encoding="utf-8") as f:
                f.write(driver.page_source)

            print(f"Saved diagnostic screenshot: {screenshot_name}")
            print(f"Saved diagnostic HTML: {html_name}")

        except Exception as debug_error:
            print(
                f"Could not save diagnostic files: {debug_error}"
            )

        # Keep the PBN on the watchlist if checking failed.
        return None, driver


def is_cleared(page_text):
    """
    Determine whether ROS reports that the unit has cleared.

    We deliberately use the specific phrase rather than simply
    checking for the word EXIT.
    """

    if not page_text:
        return False

    text = page_text.upper()

    return "EXIT THE PORT" in text


def load_watchlist():
    """Load watchlist.json."""

    if not os.path.exists(WATCHLIST_FILE):
        print("watchlist.json not found.")
        return []

    try:
        with open(
            WATCHLIST_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            data = json.load(f)

        if not isinstance(data, list):
            print("watchlist.json does not contain a list.")
            return []

        return data

    except Exception as e:
        print(f"Could not read watchlist.json: {e}")
        return []


def save_watchlist(watchlist):
    """Save the remaining watchlist."""

    temporary_file = WATCHLIST_FILE + ".tmp"

    try:
        with open(
            temporary_file,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                watchlist,
                f,
                indent=2,
                ensure_ascii=False
            )

        os.replace(
            temporary_file,
            WATCHLIST_FILE
        )

        print("watchlist.json updated.")

    except Exception as e:
        print(f"Could not save watchlist.json: {e}")

        if os.path.exists(temporary_file):
            try:
                os.remove(temporary_file)
            except Exception:
                pass


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

            # Support either:
            # {"pbn": "...", "trailer": "..."}
            # or
            # {"PBN": "...", "trailer": "..."}
            # and similar common variations.

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
                print(
                    f"Skipping item with no PBN: {item}"
                )

                remaining_items.append(item)
                continue

            page_text, driver = check_pbn_status(
                driver,
                str(pbn)
            )

            # If the check failed, keep the item.
            if page_text is None:
                remaining_items.append(item)
                continue

            # Check whether ROS reports clearance.
            if is_cleared(page_text):

                print("")
                print("🟢 CLEARANCE DETECTED")
                print(f"Trailer: {trailer}")
                print(f"PBN: {pbn}")

                message = (
                    "🟢 PBN CLEARANCE ALERT\n\n"
                    f"Trailer/Reg: {trailer}\n"
                    f"PBN: {pbn}\n"
                    "Status: EXIT THE PORT\n\n"
                    "Unit cleared and removed from "
                    "active watchlist."
                )

                send_google_chat(message)

                # Do NOT add it back to remaining_items.
                # This removes it from the active watchlist.

            else:

                print("")
                print("🟡 Still active / not cleared")
                print(f"Trailer: {trailer}")
                print(f"PBN: {pbn}")

                # Keep it for the next run.
                remaining_items.append(item)

    except Exception as e:

        print("")
        print("FATAL ERROR")
        print(str(e))
        traceback.print_exc()

        # If something goes wrong outside an individual check,
        # preserve the original watchlist.
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
