import os
import json
import time
import streamlit as st

from datetime import datetime
from github import Github

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ============================================================
# SETTINGS
# ============================================================

st.set_page_config(
    page_title="Team PBN Checker",
    page_icon="🚛",
    layout="centered"
)

ROS_URL = "https://www.ros.ie/customs-roro-control-web/ros/freight/lookup"
WATCHLIST_FILE = "watchlist.json"


# ============================================================
# GITHUB FUNCTIONS
# ============================================================

def get_repo():
    """Connect to the GitHub repository using Streamlit secrets."""

    token = st.secrets.get("GITHUB_TOKEN")
    repo_name = st.secrets.get("REPO_NAME")

    if not token or not repo_name:
        return None

    try:
        github = Github(token)
        return github.get_repo(repo_name)
    except Exception as e:
        st.error(f"GitHub connection error: {e}")
        return None


def load_watchlist():
    """
    Load watchlist from GitHub.
    Falls back to local watchlist.json if GitHub is unavailable.
    """

    repo = get_repo()

    if repo:
        try:
            file_data = repo.get_contents(
                WATCHLIST_FILE,
                ref="main"
            )

            raw = file_data.decoded_content.decode("utf-8")
            data = json.loads(raw)

            # Keep local copy updated too
            with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            return data

        except Exception:
            pass

    # Local fallback
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    return []


def save_watchlist(data):
    """
    Save watchlist locally and synchronise it to GitHub.
    """

    # Always save a local copy
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    repo = get_repo()

    if not repo:
        st.warning(
            "Watchlist saved locally, but GitHub could not be reached."
        )
        return False

    try:
        file_data = repo.get_contents(
            WATCHLIST_FILE,
            ref="main"
        )

        body = json.dumps(data, indent=2)

        repo.update_file(
            path=WATCHLIST_FILE,
            message="Update watchlist",
            content=body,
            sha=file_data.sha,
            branch="main"
        )

        st.toast("Watchlist saved to GitHub!", icon="🚀")
        return True

    except Exception as e:
        st.error(f"GitHub sync error: {e}")
        return False


# ============================================================
# SELENIUM / REVENUE FUNCTIONS
# ============================================================

def create_driver():
    """
    Create a headless Chrome browser.
    This follows the same setup as the working version of the app.
    """

    options = webdriver.ChromeOptions()

    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    # Helps Chrome run in hosted environments
    options.add_argument("--disable-blink-features=AutomationControlled")

    driver = webdriver.Chrome(options=options)

    return driver


def get_visible_inputs(driver):
    """Return visible/enabled input elements."""

    inputs = driver.find_elements(By.TAG_NAME, "input")

    visible_inputs = []

    for element in inputs:
        try:
            if element.is_displayed() and element.is_enabled():
                visible_inputs.append(element)
        except Exception:
            continue

    return visible_inputs


def find_pbn_input(driver):
    """
    Find the visible PBN input.

    Revenue's current page contains multiple inputs, so we don't
    blindly assume input[0] is always the correct one.
    """

    # First try inputs whose attributes mention PBN
    inputs = driver.find_elements(By.TAG_NAME, "input")

    for element in inputs:
        try:
            if not element.is_displayed() or not element.is_enabled():
                continue

            attributes = " ".join([
                element.get_attribute("id") or "",
                element.get_attribute("name") or "",
                element.get_attribute("placeholder") or "",
                element.get_attribute("aria-label") or ""
            ]).upper()

            if "PBN" in attributes:
                return element

        except Exception:
            continue

    # Fallback: first visible/enabled input.
    # This preserves the behaviour of the previously working script.
    visible_inputs = get_visible_inputs(driver)

    if visible_inputs:
        return visible_inputs[0]

    return None


def click_get_channel(driver):
    """
    Find and click Revenue's 'Get your Channel' button.
    """

    wait = WebDriverWait(driver, 10)

    # Try button text first
    try:
        button = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[contains("
                    "translate(normalize-space(.),"
                    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
                    "'abcdefghijklmnopqrstuvwxyz'),"
                    "'get your channel'"
                    ")]"
                )
            )
        )

        button.click()
        return True

    except Exception:
        pass

    # Some versions of the site may render the control as an input
    try:
        button = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//input[contains("
                    "translate(@value,"
                    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
                    "'abcdefghijklmnopqrstuvwxyz'),"
                    "'get your channel'"
                    ")]"
                )
            )
        )

        button.click()
        return True

    except Exception:
        return False


def extract_trailer_number(page_text):
    """
    Attempt to extract the vehicle registration / trailer number
    from the returned Revenue page.

    Revenue page wording can vary, so several patterns are checked.
    """

    lines = [
        line.strip()
        for line in page_text.splitlines()
        if line.strip()
    ]

    for index, line in enumerate(lines):

        upper = line.upper()

        # Example:
        # Trailer Number: GTC415
        if "TRAILER NUMBER" in upper:
            if ":" in line:
                value = line.split(":", 1)[1].strip()

                if value:
                    return value

            if index + 1 < len(lines):
                next_line = lines[index + 1].strip()

                if next_line:
                    return next_line

        # Example:
        # Vehicle Registration: 241-D-12345
        if "VEHICLE REGISTRATION" in upper:
            if ":" in line:
                value = line.split(":", 1)[1].strip()

                if value:
                    return value

            if index + 1 < len(lines):
                next_line = lines[index + 1].strip()

                if next_line:
                    return next_line

    return "Unknown"


def determine_status(page_text):
    """
    Determine the Revenue channel result.

    Important:
    We deliberately look for the complete phrases rather than
    simply searching for 'EXIT', which could produce false matches.
    """

    text = page_text.upper()

    if "INVALID PBN" in text:
        return "❌ INVALID PBN"

    if "CALL TO CUSTOMS" in text:
        return "🛑 CALL TO CUSTOMS"

    if "ORANGE" in text:
        return "🛑 CALL TO CUSTOMS"

    if "EXIT THE PORT" in text:
        return "✅ EXIT THE PORT"

    if "NOT READY" in text:
        return "⏳ CHANNEL NOT READY"

    return "❓ CHECK MANUALLY"


def check_pbn(driver, pbn):
    """
    Check one PBN against Revenue Customs Channel Lookup.
    """

    driver.get(ROS_URL)

    wait = WebDriverWait(driver, 15)

    # Wait for the page to load enough to expose the PBN input
    wait.until(
        lambda d: len(get_visible_inputs(d)) > 0
    )

    time.sleep(1)

    pbn_input = find_pbn_input(driver)

    if pbn_input is None:
        return {
            "PBN ID": pbn,
            "Trailer": "N/A",
            "Status": "❌ Error finding PBN input"
        }

    # Clear and enter PBN
    pbn_input.clear()
    pbn_input.send_keys(pbn)

    # Click the actual Revenue button
    clicked = click_get_channel(driver)

    if not clicked:
        # Fallback to ENTER, which was used successfully
        # in the original working script.
        pbn_input.send_keys("\n")

    # Give Revenue time to return the result
    time.sleep(2)

    try:
        body = driver.find_element(By.TAG_NAME, "body")
        page_text = body.text
    except Exception:
        page_text = ""

    trailer_number = extract_trailer_number(page_text)
    status = determine_status(page_text)

    return {
        "PBN ID": pbn,
        "Trailer": trailer_number,
        "Status": status
    }


# ============================================================
# PAGE HEADER
# ============================================================

st.title("🚛 Customs PBN Batch Checker")

st.write(
    "Paste your PBN list below, check them against Revenue, "
    "and choose which CALL TO CUSTOMS entries should be watched."
)

st.caption(
    f"Revenue Customs Channel Lookup • "
    f"{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
)


# ============================================================
# SESSION STATE
# ============================================================

if "results" not in st.session_state:
    st.session_state.results = []

if "check_complete" not in st.session_state:
    st.session_state.check_complete = False


# ============================================================
# PBN CHECKER
# ============================================================

st.subheader("1. Check PBNs")

raw_pbns = st.text_area(
    "Paste PBNs Here",
    height=200,
    placeholder=(
        "FK44CM93\n"
        "AV99EC76\n"
        "CU23AW49"
    )
).strip()


if st.button(
    "🔎 Check PBNs",
    type="primary",
    use_container_width=True
):

    pbn_list = [
        p.strip().upper()
        for p in raw_pbns.splitlines()
        if p.strip()
    ]

    # Remove duplicate PBNs while preserving order
    pbn_list = list(dict.fromkeys(pbn_list))

    if not pbn_list:
        st.warning("Please paste at least one PBN.")

    else:

        results = []

        progress_bar = st.progress(0)
        status_text = st.empty()

        driver = None

        try:

            status_text.text("Starting Revenue browser...")

            driver = create_driver()

            for idx, pbn in enumerate(pbn_list):

                status_text.text(
                    f"Checking PBN {idx + 1} of "
                    f"{len(pbn_list)}: {pbn}"
                )

                try:

                    result = check_pbn(
                        driver,
                        pbn
                    )

                except Exception as e:

                    result = {
                        "PBN ID": pbn,
                        "Trailer": "N/A",
                        "Status": (
                            f"❌ FAILED: "
                            f"{str(e)[:80]}"
                        )
                    }

                results.append(result)

                progress_bar.progress(
                    (idx + 1) / len(pbn_list)
                )

            st.session_state.results = results
            st.session_state.check_complete = True

            status_text.empty()
            progress_bar.empty()

            st.success(
                f"All {len(results)} PBN checks complete!"
            )

        except Exception as e:

            st.session_state.results = []
            st.session_state.check_complete = False

            progress_bar.empty()
            status_text.empty()

            st.error(
                "Failed to start automated browser engine: "
                f"{str(e)}"
            )

        finally:

            if driver is not None:

                try:
                    driver.quit()
                except Exception:
                    pass


# ============================================================
# RESULTS
# ============================================================

if st.session_state.results:

    st.divider()

    st.subheader("2. Check Results")

    results = st.session_state.results

    # Summary counts
    call_to_customs = [
        r for r in results
        if r["Status"] == "🛑 CALL TO CUSTOMS"
    ]

    cleared = [
        r for r in results
        if r["Status"] == "✅ EXIT THE PORT"
    ]

    invalid = [
        r for r in results
        if r["Status"] == "❌ INVALID PBN"
    ]

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "Checked",
            len(results)
        )

    with col2:
        st.metric(
            "Call to Customs",
            len(call_to_customs)
        )

    with col3:
        st.metric(
            "Exit the Port",
            len(cleared)
        )

    with col4:
        st.metric(
            "Invalid",
            len(invalid)
        )

    # Display full results
    st.dataframe(
        results,
        use_container_width=True,
        hide_index=True
    )

    # ========================================================
    # WATCHLIST SELECTION
    # ========================================================

    if call_to_customs:

        st.subheader("3. Add CALL TO CUSTOMS PBNs to Watchlist")

        st.info(
            "Select the PBNs you want the 15-minute GitHub watcher "
            "to monitor. Nothing is added automatically."
        )

        selections = {}

        for result in call_to_customs:

            pbn = result["PBN ID"]
            trailer = result.get("Trailer", "Unknown")

            label = f"{pbn}"

            if trailer and trailer != "Unknown":
                label += f" — {trailer}"

            selections[pbn] = st.checkbox(
                label,
                key=f"watch_{pbn}"
            )

        if st.button(
            "👁️ Add Selected to Watchlist",
            type="primary",
            use_container_width=True
        ):

            selected = [
                result
                for result in call_to_customs
                if selections.get(result["PBN ID"], False)
            ]

            if not selected:

                st.warning(
                    "Please select at least one PBN."
                )

            else:

                # Reload the latest version from GitHub before modifying it.
                # This avoids relying on an old copy in Streamlit's session.
                current_watchlist = load_watchlist()

                existing_pbns = {
                    str(item.get("pbn", "")).upper()
                    for item in current_watchlist
                }

                added = 0
                already_there = 0

                timestamp = datetime.now().strftime(
                    "%d/%m/%Y %H:%M:%S"
                )

                for result in selected:

                    pbn = result["PBN ID"].upper()
                    trailer = result.get(
                        "Trailer",
                        "Unknown"
                    )

                    if pbn in existing_pbns:

                        already_there += 1
                        continue

                    current_watchlist.append(
                        {
                            "pbn": pbn,
                            "trailer": trailer,
                            "added_at": timestamp
                        }
                    )

                    existing_pbns.add(pbn)
                    added += 1

                if added > 0:

                    if save_watchlist(
                        current_watchlist
                    ):

                        st.success(
                            f"Added {added} PBN(s) to the watchlist."
                        )

                        if already_there:
                            st.info(
                                f"{already_there} selected PBN(s) "
                                "were already being watched."
                            )

                        # Clear selections by rerunning
                        st.rerun()

                elif already_there:

                    st.info(
                        "All selected PBNs are already "
                        "on the watchlist."
                    )


# ============================================================
# ACTIVE WATCHLIST
# ============================================================

st.divider()

st.subheader("👁️ Active Watchlist")

items = load_watchlist()

if not items:

    st.info(
        "Watchlist is empty."
    )

else:

    st.caption(
        f"{len(items)} PBN(s) currently being monitored by "
        "the GitHub watcher."
    )

    for idx, item in enumerate(items):

        trailer = item.get(
            "trailer",
            "Unknown"
        )

        pbn = item.get(
            "pbn",
            "N/A"
        )

        added_at = item.get(
            "added_at",
            "N/A"
        )

        col1, col2 = st.columns([5, 1])

        with col1:

            st.info(
                f"Trailer/Reg: {trailer}  |  "
                f"PBN: {pbn}  |  "
                f"Added: {added_at}"
            )

        with col2:

            if st.button(
                "Delete",
                key=f"delete_{idx}",
                use_container_width=True
            ):

                # Reload latest GitHub copy before deleting
                latest_items = load_watchlist()

                # Remove matching PBN
                latest_items = [
                    x for x in latest_items
                    if str(x.get("pbn", "")).upper()
                    != str(pbn).upper()
                ]

                save_watchlist(
                    latest_items
                )

                st.rerun()


# ============================================================
# REFRESH
# ============================================================

st.divider()

if st.button(
    "🔄 Sync / Refresh Watchlist",
    use_container_width=True
):

    st.rerun()


# ============================================================
# FOOTER
# ============================================================

st.caption(
    "Revenue checks use the Customs Channel Lookup. "
    "The GitHub Actions watcher is responsible for "
    "continuing to monitor PBNs placed on the watchlist."
)
