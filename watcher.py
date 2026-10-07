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
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    StaleElementReferenceException,
)

# ============================================================
# CONFIGURATION
# ============================================================

ROS_URL = "https://www.ros.ie/customs-roro-control-web/ros/freight/lookup"

WATCHLIST_FILE = "watchlist.json"

MAX_RETRIES = 3
PAGE_LOAD_TIMEOUT = 45
RESULT_WAIT_TIMEOUT = 30

GOOGLE_CHAT_WEBHOOK = os.environ.get("GOOGLE_CHAT_WEBHOOK", "").strip()


# ============================================================
# GOOGLE CHAT
# ============================================================

def send_google_chat(message):
    if not GOOGLE_CHAT_WEBHOOK:
        print("⚠️ GOOGLE_CHAT_WEBHOOK is not configured.")
        return False

    try:
        response = requests.post(
            GOOGLE_CHAT_WEBHOOK,
            json={"text": message},
            timeout=20,
        )

        if response.status_code in (200, 204):
            print("✅ Google Chat notification sent.")
            return True

        print(
            f"⚠️ Google Chat returned HTTP "
            f"{response.status_code}: {response.text[:500]}"
        )
        return False

    except Exception as exc:
        print(f"⚠️ Google Chat notification failed: {exc}")
        return False


# ============================================================
# BROWSER
# ============================================================

def find_browser():
    possible_browsers = [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/snap/bin/chromium",
    ]

    for browser in possible_browsers:
        if os.path.exists(browser):
            print(f"✅ Browser found at: {browser}")
            return browser

    print("❌ No Chrome/Chromium browser found.")
    return None


def create_driver():
    browser_path = find_browser()

    if not browser_path:
        raise RuntimeError("Could not find Google Chrome or Chromium.")

    options = webdriver.ChromeOptions()

    options.binary_location = browser_path

    # GitHub Actions / Linux settings
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")

    # Large browser window so screenshots show the whole page properly
    options.add_argument("--window-size=1920,1080")

    # Reduce unnecessary browser activity
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-sync")
    options.add_argument("--disable-features=Translate")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")

    options.add_argument(
        "--user-agent=Mozilla/5.0 "
        "(X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/155.0.0.0 Safari/537.36"
    )

    print("Starting Google Chrome...")

    driver = webdriver.Chrome(options=options)

    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)

    print("✅ Google Chrome started successfully.")

    return driver


# ============================================================
# PAGE HELPERS
# ============================================================

def get_visible_inputs(driver):
    """
    Return visible input elements on the current page.
    """
    inputs = []

    try:
        for element in driver.find_elements(By.TAG_NAME, "input"):
            try:
                if element.is_displayed() and element.is_enabled():
                    inputs.append(element)
            except StaleElementReferenceException:
                continue
    except Exception:
        pass

    return inputs


def find_pbn_input(driver):
    """
    Find the visible PBN input on the Customs Channel Lookup page.

    The Revenue page can contain conditional inputs, so we deliberately
    look for a visible/enabled input rather than relying on a brittle ID.
    """

    # First try common PBN-related attributes.
    selectors = [
        "input[name*='pbn' i]",
        "input[id*='pbn' i]",
        "input[placeholder*='PBN' i]",
    ]

    for selector in selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)

            for element in elements:
                if element.is_displayed() and element.is_enabled():
                    return element

        except Exception:
            continue

    # Fallback: inspect visible text inputs.
    for element in get_visible_inputs(driver):
        try:
            input_type = (element.get_attribute("type") or "").lower()

            if input_type in ("text", ""):
                return element

        except StaleElementReferenceException:
            continue

    return None


def find_channel_button(driver):
    """
    Find the Revenue 'Get your Channel' button.
    """

    xpaths = [
        "//button[contains("
        "translate(normalize-space(.), "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
        "'abcdefghijklmnopqrstuvwxyz'), "
        "'get your channel'"
        ")]",

        "//input["
        "contains("
        "translate(@value, "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
        "'abcdefghijklmnopqrstuvwxyz'), "
        "'get your channel'"
        ")"
        "]",

        "//a[contains("
        "translate(normalize-space(.), "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
        "'abcdefghijklmnopqrstuvwxyz'), "
        "'get your channel'"
        ")]",
    ]

    for xpath in xpaths:
        try:
            elements = driver.find_elements(By.XPATH, xpath)

            for element in elements:
                if element.is_displayed() and element.is_enabled():
                    return element

        except Exception:
            continue

    return None


def page_text(driver):
    """
    Return visible page text.
    """

    try:
        return driver.find_element(By.TAG_NAME, "body").text
    except Exception:
        return ""


def normalise_text(text):
    """
    Normalise whitespace and case for reliable channel matching.
    """

    return " ".join(text.upper().split())


# ============================================================
# CHANNEL DETECTION
# ============================================================

def detect_channel(text):
    """
    Determine the Customs Channel returned by Revenue.

    Returns:
        'EXIT THE PORT'
        'GREEN'
        'ORANGE'
        'RED'
        'UNKNOWN'
    """

    normalised = normalise_text(text)

    # Most important check.
    if "EXIT THE PORT" in normalised:
        return "EXIT THE PORT"

    # Other possible Revenue channel wording.
    if "GREEN" in normalised:
        return "GREEN"

    if "ORANGE" in normalised:
        return "ORANGE"

    if "RED" in normalised:
        return "RED"

    return "UNKNOWN"


# ============================================================
# CUSTOMS CHANNEL LOOKUP
# ============================================================

def check_pbn_channel(driver, pbn):
    """
    Open Customs Channel Lookup, enter PBN and retrieve the channel.
    """

    for attempt in range(1, MAX_RETRIES + 1):

        print(f"  Attempt {attempt}/{MAX_RETRIES} for PBN {pbn}")

        try:
            # ------------------------------------------------
            # Open Revenue Customs Channel Lookup
            # ------------------------------------------------

            print(f"Opening Revenue Channel Lookup: {ROS_URL}")

            driver.get(ROS_URL)

            # Wait for page to load.
            WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
                lambda d: d.execute_script("return document.readyState")
                == "complete"
            )

            # Wait for a visible input.
            WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
                lambda d: find_pbn_input(d) is not None
            )

            print("✅ PBN input found.")

            # ------------------------------------------------
            # Enter PBN
            # ------------------------------------------------

            pbn_input = find_pbn_input(driver)

            if pbn_input is None:
                raise RuntimeError("Could not find visible PBN input.")

            try:
                pbn_input.click()
                pbn_input.clear()
                pbn_input.send_keys(pbn)
            except StaleElementReferenceException:
                # Re-find it if the page refreshed/re-rendered.
                pbn_input = find_pbn_input(driver)

                if pbn_input is None:
                    raise RuntimeError(
                        "PBN input disappeared while entering PBN."
                    )

                pbn_input.click()
                pbn_input.clear()
                pbn_input.send_keys(pbn)

            print(f"  PBN entered: {pbn}")

            # ------------------------------------------------
            # Find Get your Channel
            # ------------------------------------------------

            WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
                lambda d: find_channel_button(d) is not None
            )

            button = find_channel_button(driver)

            if button is None:
                raise RuntimeError(
                    "Could not find 'Get your Channel' button."
                )

            print("✅ Get your Channel button found.")

            # ------------------------------------------------
            # Click button
            # ------------------------------------------------

            try:
                button.click()
            except Exception:
                print("  Normal click failed - trying JavaScript click.")

                driver.execute_script(
                    "arguments[0].click();",
                    button
                )

            print("  Get your Channel clicked.")

            # ------------------------------------------------
            # Wait for result
            # ------------------------------------------------

            print("  Waiting for Customs Channel result...")

            start_time = time.time()
            result_text = ""

            while time.time() - start_time < RESULT_WAIT_TIMEOUT:

                time.sleep(0.5)

                result_text = page_text(driver)

                channel = detect_channel(result_text)

                if channel != "UNKNOWN":
                    print(f"  ✅ Channel detected: {channel}")
                    break

                # Also check the entire page source.
                # This helps if the result is rendered in a way that
                # is not included in normal body text.
                try:
                    source = driver.page_source
                    source_channel = detect_channel(source)

                    if source_channel != "UNKNOWN":
                        print(
                            f"  ✅ Channel detected in page source: "
                            f"{source_channel}"
                        )
                        result_text = source
                        break

                except Exception:
                    pass

            # ------------------------------------------------
            # Save screenshot regardless of result
            # ------------------------------------------------

            screenshot_file = f"ros_result_{pbn}.png"

            try:
                driver.save_screenshot(screenshot_file)
                print(
                    f"  📸 ROS result screenshot saved: "
                    f"{screenshot_file}"
                )
            except Exception as exc:
                print(f"  ⚠️ Could not save screenshot: {exc}")

            # Save HTML as well. This will be very useful if the
            # visual page and text extraction ever disagree.
            html_file = f"ros_result_{pbn}.html"

            try:
                with open(html_file, "w", encoding="utf-8") as file:
                    file.write(driver.page_source)

                print(
                    f"  📄 ROS result HTML saved: "
                    f"{html_file}"
                )

            except Exception as exc:
                print(f"  ⚠️ Could not save HTML: {exc}")

            # ------------------------------------------------
            # Final channel detection
            # ------------------------------------------------

            result_text = page_text(driver)
            channel = detect_channel(result_text)

            # If body text doesn't contain it, inspect source.
            if channel == "UNKNOWN":
                try:
                    channel = detect_channel(driver.page_source)
                except Exception:
                    pass

            print()
            print("---------- CUSTOMS CHANNEL RESPONSE ----------")
            print(result_text[:10000])
            print("-------- END CUSTOMS CHANNEL RESPONSE --------")
            print()

            print(f"CUSTOMS CHANNEL: {channel}")

            return channel

        except TimeoutException as exc:

            print(
                f"  ⚠️ Timeout on attempt {attempt}: {exc}"
            )

            debug_file = f"debug_{pbn}_attempt_{attempt}.png"

            try:
                driver.save_screenshot(debug_file)
                print(
                    f"  📸 Debug screenshot saved: "
                    f"{debug_file}"
                )
            except Exception:
                pass

        except WebDriverException as exc:

            print(
                f"  ⚠️ WebDriver error on attempt {attempt}: "
                f"{exc}"
            )

            debug_file = f"debug_{pbn}_attempt_{attempt}.png"

            try:
                driver.save_screenshot(debug_file)
            except Exception:
                pass

        except Exception as exc:

            print(
                f"  ⚠️ Error on attempt {attempt}: {exc}"
            )

            traceback.print_exc()

            debug_file = f"debug_{pbn}_attempt_{attempt}.png"

            try:
                driver.save_screenshot(debug_file)
            except Exception:
                pass

        # Retry delay
        if attempt < MAX_RETRIES:
            print("  Waiting before retry...")
            time.sleep(3)

    print(
        f"❌ All {MAX_RETRIES} attempts failed for PBN {pbn}."
    )

    return "UNKNOWN"


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 60)
    print("PBN CUSTOMS CHANNEL WATCHER STARTING")
    print("=" * 60)

    print(
        "Google Chat webhook: "
        + ("CONFIGURED" if GOOGLE_CHAT_WEBHOOK else "NOT CONFIGURED")
    )

    # --------------------------------------------------------
    # Load watchlist
    # --------------------------------------------------------

    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as file:
            watchlist = json.load(file)

    except FileNotFoundError:
        print(f"❌ {WATCHLIST_FILE} not found.")
        return

    except json.JSONDecodeError as exc:
        print(f"❌ Invalid JSON in {WATCHLIST_FILE}: {exc}")
        return

    if not isinstance(watchlist, list):
        print("❌ Watchlist must contain a JSON list.")
        return

    print(f"Loaded {len(watchlist)} watchlist item(s).")

    if not watchlist:
        print("Nothing to check.")
        return

    # --------------------------------------------------------
    # Start browser
    # --------------------------------------------------------

    driver = None

    try:
        driver = create_driver()

        remaining_watchlist = []

        # ----------------------------------------------------
        # Process each PBN
        # ----------------------------------------------------

        for item in watchlist:

            pbn = str(item.get("pbn", "")).strip()
            trailer = str(item.get("trailer", "")).strip()

            print()
            print("=" * 60)
            print(f"Checking PBN: {pbn}")
            print(f"Trailer: {trailer}")
            print("=" * 60)

            if not pbn:
                print("⚠️ Item has no PBN - keeping it on watchlist.")
                remaining_watchlist.append(item)
                continue

            try:

                channel = check_pbn_channel(driver, pbn)

                # ------------------------------------------------
                # CLEARANCE
                # ------------------------------------------------

                if channel == "EXIT THE PORT":

                    print()
                    print("🟢 CLEARANCE MATCH: TRUE")
                    print("🟢 EXIT THE PORT")
                    print(f"Trailer: {trailer}")
                    print(f"PBN: {pbn}")

                    message = (
                        "🟢 PBN CLEARANCE ALERT\n"
                        f"Trailer/Reg: {trailer}\n"
                        f"PBN: {pbn}\n"
                        "Status: EXIT THE PORT\n"
                        "Unit cleared and removed from active watchlist."
                    )

                    send_google_chat(message)

                    # IMPORTANT:
                    # Do NOT append this item to remaining_watchlist.
                    # This removes it from the active watchlist.

                else:

                    print()
                    print("CLEARANCE MATCH: FALSE")
                    print(f"CUSTOMS CHANNEL: {channel}")
                    print("STILL ACTIVE / NOT CLEARED")
                    print(f"Trailer: {trailer}")
                    print(f"PBN: {pbn}")

                    # Keep watching it.
                    remaining_watchlist.append(item)

            except Exception as exc:

                print()
                print(f"❌ Unexpected error checking {pbn}: {exc}")
                traceback.print_exc()

                # Never remove an item if the check failed.
                remaining_watchlist.append(item)

        # --------------------------------------------------------
        # Save updated watchlist
        # --------------------------------------------------------

        with open(
            WATCHLIST_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                remaining_watchlist,
                file,
                indent=2,
                ensure_ascii=False
            )

            file.write("\n")

        print()
        print("=" * 60)
        print("PBN CUSTOMS CHANNEL WATCHER FINISHED")
        print("=" * 60)
        print(f"Items originally checked: {len(watchlist)}")
        print(f"Items remaining: {len(remaining_watchlist)}")

    finally:

        if driver is not None:

            try:
                driver.quit()
                print("Browser closed.")
            except Exception:
                pass


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
