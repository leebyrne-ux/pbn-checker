```python
import os
import json
import time
import traceback
import shutil
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


def send_google_chat_notification(
    webhook_url,
    trailer,
    pbn,
    status_text
):
    """
    Send a clearance notification to Google Chat.
    """

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
            timeout=15
        )

        response.raise_for_status()

        print(
            f"✅ Google Chat notification sent "
            f"for {trailer} ({pbn})."
        )

    except Exception as error:
        print(
            "⚠️ Failed to send Google Chat notification: "
            f"{type(error).__name__}: {error}"
        )


# ============================================================
# CHROMIUM
# ============================================================

def find_chromium():
    """
    Find Chromium on the GitHub Actions runner.
    """

    possible_paths = [
        "/snap/bin/chromium",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
    ]

    for path in possible_paths:

        if path and os.path.exists(path):

            print(
                f"✅ Chromium found at: {path}"
            )

            return path

    print(
        "⚠️ Chromium binary could not be located."
    )

    return None


def create_driver():
    """
    Create a Selenium Chromium driver.

    IMPORTANT:
    We deliberately do NOT install or specify a separate
    chromedriver here.

    Selenium Manager will handle the driver.
    """

    print("")
    print("Starting Chromium...")

    options = webdriver.ChromeOptions()

    # GitHub Actions / Linux
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")

    # Browser window
    options.add_argument("--window-size=1920,1080")

    # Make browser look like a normal desktop browser
    options.add_argument(
        "--user-agent="
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    # Stability
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-sync")

    # Find Chromium
    chromium_path = find_chromium()

    if chromium_path:

        options.binary_location = chromium_path

    try:

        # Do NOT specify chromedriver.
        #
        # Selenium Manager handles the driver.

        driver = webdriver.Chrome(
            options=options
        )

        driver.set_page_load_timeout(
            PAGE_LOAD_TIMEOUT
        )

        print(
            "✅ Chromium started successfully."
        )

        return driver

    except Exception as error:

        print(
            "❌ Failed to start Chromium."
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

        raise


# ============================================================
# ROS PAGE
# ============================================================

def open_ros_page(driver):
    """
    Open the Revenue ROS PBN status page.
    """

    print(
        f"Opening ROS page: {ROS_URL}"
    )

    driver.get(ROS_URL)

    wait = WebDriverWait(
        driver,
        RESULT_WAIT_TIMEOUT
    )

    # The current ROS page contains a visible input.
    #
    # We intentionally don't rely on the old ID="pbn",
    # because that was part of the previous page implementation.

    input_box = wait.until(
        EC.visibility_of_element_located(
            (
                By.XPATH,
                "//input[not(@type='hidden')]"
            )
        )
    )

    print(
        "✅ PBN input found."
    )

    return input_box


def find_check_button(driver):
    """
    Find the current ROS Check Status button.
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
                "translate(normalize-space(.),"
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
                "'abcdefghijklmnopqrstuvwxyz'),"
                "'check status'"
                ")]"
            )
        )
    )

    print(
        "✅ Check Status button found."
    )

    return button


# ============================================================
# DEBUGGING
# ============================================================

def save_debug_files(
    driver,
    pbn_id,
    attempt
):
    """
    Save screenshot and HTML when a check fails.

    These files can be uploaded from the GitHub Action
    and allow us to see exactly what ROS returned.
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

    # Screenshot
    try:

        driver.save_screenshot(
            screenshot_file
        )

        print(
            f"📸 Debug screenshot saved: "
            f"{screenshot_file}"
        )

    except Exception as error:

        print(
            "⚠️ Could not save screenshot: "
            f"{error!r}"
        )

    # HTML
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
            f"📄 Debug HTML saved: "
            f"{html_file}"
        )

    except Exception as error:

        print(
            "⚠️ Could not save HTML: "
            f"{error!r}"
        )


# ============================================================
# CHECK ONE PBN
# ============================================================

def check_pbn_status(
    driver,
    pbn_id
):
    """
    Check a single PBN on the ROS website.

    Returns:
        page_text, driver

    The driver may be replaced if Selenium encounters
    a browser failure during a retry.
    """

    last_error = None

    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):

        print("")
        print(
            f"Checking PBN {pbn_id}"
        )

        print(
            f"Attempt {attempt}/{MAX_RETRIES}"
        )

        try:

            # --------------------------------------------
            # Open ROS
            # --------------------------------------------

            input_box = open_ros_page(
                driver
            )

            # --------------------------------------------
            # Enter PBN
            # --------------------------------------------

            input_box.clear()

            input_box.send_keys(
                pbn_id
            )

            print(
                "PBN entered."
            )

            # --------------------------------------------
            # Find button
            # --------------------------------------------

            submit_button = find_check_button(
                driver
            )

            # --------------------------------------------
            # Click
            # --------------------------------------------

            driver.execute_script(
                "arguments[0].click();",
                submit_button
            )

            print(
                "Check Status clicked."
            )

            # --------------------------------------------
            # Wait for result
            # --------------------------------------------

            wait = WebDriverWait(
                driver,
                RESULT_WAIT_TIMEOUT
            )

            def result_has_loaded(browser):

                try:

                    text = browser.find_element(
                        By.TAG_NAME,
                        "body"
                    ).text.strip()

                    upper = text.upper()

                    indicators = [
                        "EXIT THE PORT",
                        "CALL TO CUSTOMS",
                        "GOOD TO PROCEED",
                        "PROCEED",
                        "PBN STATUS",
                        "PBN ID",
                        "STATUS",
                    ]

                    return any(
                        indicator in upper
                        for indicator in indicators
                    )

                except Exception:

                    return False

            wait.until(
                result_has_loaded
            )

            # Allow Angular to finish rendering
            time.sleep(1)

            # --------------------------------------------
            # Read page
            # --------------------------------------------

            page_text = driver.find_element(
                By.TAG_NAME,
                "body"
            ).text.strip()

            if not page_text:

                raise RuntimeError(
                    "ROS returned an empty page."
                )

            print(
                "✅ ROS returned a result."
            )

            return page_text, driver

        except Exception as error:

            last_error = error

            print("")
            print(
                f"⚠️ Attempt {attempt} failed."
            )

            print(
                f"Error type: "
                f"{type(error).__name__}"
            )

            print(
                f"Error message: "
                f"{error!r}"
            )

            # Save diagnostics
            try:

                save_debug_files(
                    driver,
                    pbn_id,
                    attempt
                )

            except Exception:

                pass

            # Retry
            if attempt < MAX_RETRIES:

                print(
                    "Retrying in 5 seconds..."
                )

                time.sleep(5)

                # Recreate browser
                try:

                    driver.quit()

                except Exception:

                    pass

                driver = create_driver()

    # All attempts failed
    raise last_error


# ============================================================
# DETERMINE CLEARANCE
# ============================================================

def is_cleared(page_text):
    """
    Determine whether ROS says the unit can Exit the Port.

    IMPORTANT:
    We deliberately do NOT search simply for the word
    'EXIT', because that could cause false positives.
    """

    text = page_text.upper()

    if "EXIT THE PORT" in text:

        return True, "Exit the Port"

    return False, None


# ============================================================
# PRINT ROS RESPONSE
# ============================================================

def print_status_summary(page_text):
    """
    Print the ROS response to the GitHub Actions log.
    """

    print("")
    print(
        "---------- ROS RESPONSE ----------"
    )

    lines = [
        line.strip()
        for line in page_text.splitlines()
        if line.strip()
    ]

    for line in lines:

        print(line)

    print(
        "-------- END ROS RESPONSE --------"
    )

    print("")


# ============================================================
# MAIN
# ============================================================

def main():

    print("")
    print(
        "========================================"
    )

    print(
        "           ROS PBN WATCHER"
    )

    print(
        "========================================"
    )

    print("")

    # --------------------------------------------------------
    # Google Chat
    # --------------------------------------------------------

    webhook_url = get_google_chat_webhook()

    if webhook_url:

        print(
            "Google Chat webhook: CONFIGURED"
        )

    else:

        print(
            "Google Chat webhook: MISSING"
        )

    # --------------------------------------------------------
    # Watchlist
    # --------------------------------------------------------

    if not os.path.exists(
        WATCHLIST_FILE
    ):

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

            watchlist = json.load(
                file
            )

    except Exception as error:

        print(
            "❌ Could not read watchlist."
        )

        print(
            f"{type(error).__name__}: "
            f"{error}"
        )

        return

    if not watchlist:

        print(
            "Watchlist is empty. "
            "Nothing to check."
        )

        return

    print(
        f"Loaded {len(watchlist)} "
        f"item(s) from watchlist."
    )

    # --------------------------------------------------------
    # Browser
    # --------------------------------------------------------

    driver = None

    remaining_watchlist = []

    try:

        driver = create_driver()

        # ----------------------------------------------------
        # Check each watchlist item
        # ----------------------------------------------------

        for item in watchlist:

            pbn = str(
                item.get(
                    "pbn",
                    ""
                )
            ).strip()

            trailer = str(
                item.get(
                    "trailer",
                    "Unknown"
                )
            ).strip()

            # ------------------------------------------------
            # Missing PBN
            # ------------------------------------------------

            if not pbn:

                print("")
                print(
                    "⚠️ Watchlist item has no PBN."
                )

                print(
                    "Keeping it on the watchlist."
                )

                remaining_watchlist.append(
                    item
                )

                continue

            print("")
            print(
                "========================================"
            )

            print(
                f"Trailer: {trailer}"
            )

            print(
                f"PBN: {pbn}"
            )

            print(
                "========================================"
            )

            try:

                # --------------------------------------------
                # Check ROS
                # --------------------------------------------

                page_text, driver = check_pbn_status(
                    driver,
                    pbn
                )

                # --------------------------------------------
                # Print response
                # --------------------------------------------

                print_status_summary(
                    page_text
                )

                # --------------------------------------------
                # Determine clearance
                # --------------------------------------------

                cleared, status = is_cleared(
                    page_text
                )

                if cleared:

                    print("")
                    print(
                        f"🟢 CLEARANCE DETECTED!"
                    )

                    print(
                        f"Trailer: {trailer}"
                    )

                    print(
                        f"PBN: {pbn}"
                    )

                    print(
                        f"Status: {status}"
                    )

                    # ----------------------------------------
                    # Google Chat
                    # ----------------------------------------

                    if webhook_url:

                        send_google_chat_notification(
                            webhook_url,
                            trailer,
                            pbn,
                            status
                        )

                    else:

                        print(
                            "⚠️ Google Chat webhook "
                            "is not configured."
                        )

                    # ----------------------------------------
                    # IMPORTANT:
                    #
                    # Do NOT append this item to
                    # remaining_watchlist.
                    #
                    # This removes it from active watching.
                    # ----------------------------------------

                else:

                    print("")
                    print(
                        f"⏳ Still pending:"
                    )

                    print(
                        f"Trailer: {trailer}"
                    )

                    print(
                        f"PBN: {pbn}"
                    )

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

                # --------------------------------------------
                # VERY IMPORTANT:
                #
                # Never remove a PBN because of an error.
                # Keep it for the next run.
                # --------------------------------------------

                remaining_watchlist.append(
                    item
                )

    except Exception as fatal_error:

        print("")
        print(
            "❌ FATAL BROWSER ERROR"
        )

        print(
            f"Type: "
            f"{type(fatal_error).__name__}"
        )

        print(
            f"Message: "
            f"{fatal_error!r}"
        )

        traceback.print_exc()

        # Browser failed completely.
        # Preserve the entire watchlist.

        remaining_watchlist = watchlist

    finally:

        if driver:

            try:

                driver.quit()

                print(
                    "Browser closed."
                )

            except Exception:

                pass

    # --------------------------------------------------------
    # Save watchlist
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
        print(
            "========================================"
        )

        print(
            "WATCHLIST UPDATE"
        )

        print(
            "========================================"
        )

        print(
            f"Before: "
            f"{len(watchlist)} item(s)"
        )

        print(
            f"After:  "
            f"{len(remaining_watchlist)} item(s)"
        )

        removed = (
            len(watchlist)
            - len(remaining_watchlist)
        )

        print(
            f"Removed: "
            f"{removed} item(s)"
        )

        print(
            "========================================"
        )

    except Exception as error:

        print(
            "❌ Could not save watchlist."
        )

        print(
            f"{type(error).__name__}: "
            f"{error}"
        )

        raise


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
```

**Important:** this `watcher.py` is designed to go with the updated GitHub Actions workflow I gave you in the previous message — specifically, **do not install `chromium-chromedriver` separately**. Selenium should manage the driver.

Once you've replaced the file, run the Action again. The next log should tell us whether we've finally got past the Chromium problem and reached ROS.
