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

ROS_URL = "https://www.ros.ie/customs-roro-control-web/ros/freight/lookup"

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

        print(
            f"✅ Google Chat notification sent "
            f"for {trailer} ({pbn})."
        )

    except Exception as error:
        print(
            f"⚠️ Failed to send Google Chat notification: "
            f"{type(error).__name__}: {error}"
        )


# ============================================================
# BROWSER SETUP
# ============================================================

def find_browser():
    """
    Locate Google Chrome on the GitHub Actions runner.

    Google Chrome is preferred because the workflow installs
    Google Chrome Stable rather than Chromium.
    """

    possible_paths = [
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",

        # Fallbacks in case the runner ever provides Chromium.
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/snap/bin/chromium",
    ]

    for path in possible_paths:
        if path and os.path.exists(path):
            print(f"✅ Browser found at: {path}")
            return path

    print("⚠️ Google Chrome/Chromium binary could not be located.")
    print("Selenium will try to locate a browser automatically.")

    return None


def create_driver():
    """Create a fresh Selenium Chrome driver."""

    print("Starting Google Chrome...")

    options = webdriver.ChromeOptions()

    # Headless mode for GitHub Actions
    options.add_argument("--headless=new")

    # Required/recommended for GitHub-hosted Linux runners
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")

    # Prevent size/layout issues
    options.add_argument("--window-size=1920,1080")

    # Use a normal desktop browser user agent
    options.add_argument(
        "--user-agent="
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    # Stability options
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-sync")

    browser_path = find_browser()

    if browser_path:
        options.binary_location = browser_path

    try:
        driver = webdriver.Chrome(options=options)

        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)

        print("✅ Google Chrome started successfully.")

        return driver

    except Exception as error:

        print("❌ Failed to start Google Chrome.")

        print(
            f"Exception type: {type(error).__name__}"
        )

        print(
            f"Exception message: {error!r}"
        )

        traceback.print_exc()

        raise


# ============================================================
# ROS PAGE
# ============================================================

def wait_for_ros_page(driver):
    """
    Open the current Revenue ROS PBN status page and wait
    for the PBN input field to become available.
    """

    print(f"Opening ROS page: {ROS_URL}")

    driver.get(ROS_URL)

    wait = WebDriverWait(
        driver,
        RESULT_WAIT_TIMEOUT
    )

    input_box = wait.until(
        EC.visibility_of_element_located(
            (
                By.XPATH,
                "//input[not(@type='hidden')]"
            )
        )
    )

    print("✅ PBN input found.")

    return input_box


def find_check_button(driver):
    """
    Locate the current ROS 'Check Status' button.
    """

    wait = WebDriverWait(
        driver,
        RESULT_WAIT_TIMEOUT
    )

    button = wait.until(
        EC.element_to_be_clickable(
            (
                By.XPATH,
                "//button[contains("
                "translate(normalize-space(.), "
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                "'abcdefghijklmnopqrstuvwxyz'), "
                "'check status'"
                ")]"
            )
        )
    )

    print("✅ Check Status button found.")

    return button


# ============================================================
# PBN CHECK
# ============================================================

def check_pbn_status(driver, pbn_id):
    """
    Check one PBN on Revenue ROS.

    Returns the visible page text.
    """

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):

        print(
            f"  Attempt {attempt}/{MAX_RETRIES} "
            f"for PBN {pbn_id}"
        )

        try:

            # ------------------------------------------------
            # Open ROS
            # ------------------------------------------------

            input_box = wait_for_ros_page(driver)

            # ------------------------------------------------
            # Enter PBN
            # ------------------------------------------------

            input_box.clear()
            input_box.send_keys(pbn_id)

            print(f"  PBN entered: {pbn_id}")

            # ------------------------------------------------
            # Find and click Check Status
            # ------------------------------------------------

            submit_button = find_check_button(driver)

            driver.execute_script(
                "arguments[0].click();",
                submit_button
            )

            print("  Check Status clicked.")

            # ------------------------------------------------
            # Wait for ROS result
            # ------------------------------------------------

            wait = WebDriverWait(
                driver,
                RESULT_WAIT_TIMEOUT
            )

            def result_has_loaded(d):

                text = d.find_element(
                    By.TAG_NAME,
                    "body"
                ).text.strip()

                upper = text.upper()

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

                return any(
                    indicator in upper
                    for indicator in indicators
                )

            try:

                wait.until(result_has_loaded)

            except Exception:

                print(
                    "  ⚠️ Result indicator not detected "
                    "within 30 seconds."
                )

            # Give ROS/Angular a moment to finish rendering
            time.sleep(1)

            # ------------------------------------------------
            # Get final page text
            # ------------------------------------------------

            page_text = driver.find_element(
                By.TAG_NAME,
                "body"
            ).text.strip()

            if not page_text:
                raise RuntimeError(
                    "ROS returned an empty page."
                )

            # ------------------------------------------------
            # SAVE SCREENSHOT OF ACTUAL ROS RESULT
            # ------------------------------------------------

            safe_pbn = "".join(
                character
                for character in pbn_id
                if character.isalnum()
            )

            screenshot_file = (
                f"ros_result_{safe_pbn}.png"
            )

            try:

                driver.save_screenshot(
                    screenshot_file
                )

                print(
                    f"  📸 ROS result screenshot saved: "
                    f"{screenshot_file}"
                )

            except Exception as screenshot_error:

                print(
                    f"  ⚠️ Could not save ROS result screenshot: "
                    f"{screenshot_error!r}"
                )

            print("  ✅ ROS returned a result.")

            return page_text

        except Exception as error:

            last_error = error

            print(
                f"  ⚠️ Attempt {attempt} failed."
            )

            print(
                f"  Error type: {type(error).__name__}"
            )

            print(
                f"  Error: {error!r}"
            )

            # Save diagnostics
            save_debug_files(
                driver,
                pbn_id,
                attempt
            )

            if attempt < MAX_RETRIES:

                print(
                    "  Retrying in 5 seconds..."
                )

                time.sleep(5)

                try:
                    driver.quit()
                except Exception:
                    pass

                # Rebuild browser for retry
                driver = create_driver()

            else:

                print(
                    f"❌ All {MAX_RETRIES} attempts failed "
                    f"for PBN {pbn_id}."
                )

    raise last_error


# ============================================================
# DEBUGGING
# ============================================================

def save_debug_files(driver, pbn_id, attempt):
    """
    Save screenshot and HTML whenever a ROS check fails.
    """

    safe_pbn = "".join(
        character
        for character in pbn_id
        if character.isalnum()
    )

    screenshot_file = (
        f"debug_{safe_pbn}_attempt_{attempt}.png"
    )

    html_file = (
        f"debug_{safe_pbn}_attempt_{attempt}.html"
    )

    # --------------------------------------------------------
    # Screenshot
    # --------------------------------------------------------

    try:

        driver.save_screenshot(
            screenshot_file
        )

        print(
            f"  📸 Debug screenshot saved: "
            f"{screenshot_file}"
        )

    except Exception as error:

        print(
            f"  Could not save screenshot: "
            f"{error!r}"
        )

    # --------------------------------------------------------
    # HTML
    # --------------------------------------------------------

    try:

        with open(
            html_file,
            "w",
            encoding="utf-8"
        ) as file:

            file.write(
                driver.page_source
            )

        print(
            f"  📄 Debug HTML saved: "
            f"{html_file}"
        )

    except Exception as error:

        print(
            f"  Could not save HTML: "
            f"{error!r}"
        )


# ============================================================
# STATUS INTERPRETATION
# ============================================================

def is_cleared(page_text):
    """
    Determine whether the PBN has received an
    'Exit the Port' customs channel.

    We deliberately search for the complete phrase,
    rather than just the word EXIT.
    """

    text = page_text.upper()

    if "EXIT THE PORT" in text:
        print("CLEARANCE MATCH: TRUE")
        return True, "Exit the Port"

    print("CLEARANCE MATCH: FALSE")

    return False, None


def print_status_summary(page_text):
    """
    Print the ROS response to the GitHub Actions log.
    """

    print("")
    print("---------- ROS RESPONSE ----------")

    lines = [
        line.strip()
        for line in page_text.splitlines()
        if line.strip()
    ]

    for line in lines:
        print(line)

    print("-------- END ROS RESPONSE --------")
    print("")


# ============================================================
# MAIN
# ============================================================

def main():

    print("")
    print("============================================================")
    print("PBN WATCHER STARTING")
    print("============================================================")

    webhook_url = get_google_chat_webhook()

    print(
        "Google Chat webhook: "
        + ("CONFIGURED" if webhook_url else "MISSING")
    )

    # --------------------------------------------------------
    # Load watchlist
    # --------------------------------------------------------

    if not os.path.exists(WATCHLIST_FILE):

        print(
            f"❌ {WATCHLIST_FILE} not found."
        )

        return

    try:

        with open(
            WATCHLIST_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            watchlist = json.load(file)

    except Exception as error:

        print(
            f"❌ Could not read {WATCHLIST_FILE}: "
            f"{type(error).__name__}: {error}"
        )

        return

    if not watchlist:

        print(
            "Watchlist is empty. Nothing to check."
        )

        return

    print(
        f"Loaded {len(watchlist)} watchlist item(s)."
    )

    # --------------------------------------------------------
    # Start browser
    # --------------------------------------------------------

    driver = None
    remaining_watchlist = []

    try:

        driver = create_driver()

        # ----------------------------------------------------
        # Check each PBN
        # ----------------------------------------------------

        for item in watchlist:

            pbn = str(
                item.get("pbn", "")
            ).strip()

            trailer = str(
                item.get("trailer", "Unknown")
            ).strip()

            if not pbn:

                print(
                    "⚠️ Watchlist item has no PBN. "
                    "Keeping it on the watchlist."
                )

                remaining_watchlist.append(
                    item
                )

                continue

            print("")
            print("============================================================")
            print(f"Checking PBN: {pbn}")
            print(f"Trailer: {trailer}")
            print("============================================================")

            try:

                page_text = check_pbn_status(
                    driver,
                    pbn
                )

                print(
                    "Checking ROS result for clearance..."
                )

                print_status_summary(
                    page_text
                )

                cleared, status = is_cleared(
                    page_text
                )

                # ------------------------------------------------
                # CLEARED
                # ------------------------------------------------

                if cleared:

                    print("")
                    print(
                        f"🟢 CLEARANCE DETECTED "
                        f"for {trailer} ({pbn})!"
                    )

                    # Send Google Chat notification

                    if webhook_url:

                        send_google_chat_notification(
                            webhook_url,
                            trailer,
                            pbn,
                            status
                        )

                    else:

                        print(
                            "⚠️ Cleared, but Google Chat "
                            "webhook is not configured."
                        )

                    # IMPORTANT:
                    #
                    # DO NOT add this item to
                    # remaining_watchlist.
                    #
                    # Therefore the cleared PBN is removed
                    # from the active watchlist.

                # ------------------------------------------------
                # STILL ACTIVE
                # ------------------------------------------------

                else:

                    print("")
                    print(
                        "STILL ACTIVE / NOT CLEARED"
                    )

                    print(
                        f"Trailer: {trailer}"
                    )

                    print(
                        f"PBN: {pbn}"
                    )

                    # Keep active PBN on watchlist

                    remaining_watchlist.append(
                        item
                    )

            except Exception as error:

                print("")
                print(
                    f"❌ ERROR checking PBN {pbn}"
                )

                print(
                    f"Exception type: "
                    f"{type(error).__name__}"
                )

                print(
                    f"Exception message: "
                    f"{error!r}"
                )

                traceback.print_exc()

                # IMPORTANT:
                #
                # If the check fails, KEEP the item.
                #
                # We never want a technical error to
                # accidentally remove a PBN.

                remaining_watchlist.append(
                    item
                )

    except Exception as fatal_error:

        print("")
        print("============================================================")
        print("FATAL ERROR")
        print("============================================================")

        print(
            f"Type: {type(fatal_error).__name__}"
        )

        print(
            f"Message: {fatal_error!r}"
        )

        traceback.print_exc()

        # If the browser itself fails, preserve everything.

        remaining_watchlist = watchlist

    finally:

        if driver:

            try:

                driver.quit()

                print("Browser closed.")

            except Exception:
                pass

    # --------------------------------------------------------
    # Save updated watchlist
    # --------------------------------------------------------

    try:

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

        print("")
        print("============================================================")
        print("PBN WATCHER FINISHED")
        print("============================================================")

        print(
            f"Items originally checked: "
            f"{len(watchlist)}"
        )

        print(
            f"Items remaining: "
            f"{len(remaining_watchlist)}"
        )

        print("============================================================")

    except Exception as error:

        print(
            f"❌ Could not save watchlist: "
            f"{type(error).__name__}: {error}"
        )

        raise


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
