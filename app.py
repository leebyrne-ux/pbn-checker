
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
    """Connect to GitHub using Streamlit secrets."""

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


def load_data():
    """
    Load the watchlist from GitHub.
    Fall back to the local file if GitHub is unavailable.
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

            if not isinstance(data, list):
                raise ValueError("Watchlist must be a JSON list.")

            with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            return data

        except Exception:
            pass

    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            return data if isinstance(data, list) else []

        except Exception:
            return []

    return []


def save_data(data):
    """Save the watchlist locally and synchronise it to GitHub."""

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

        repo.update_file(
            path=WATCHLIST_FILE,
            message="Update watchlist",
            content=json.dumps(data, indent=2),
            sha=file_data.sha,
            branch="main"
        )

        st.toast("Watchlist saved to GitHub!", icon="🚀")
        return True

    except Exception as e:
        st.error(f"GitHub sync error: {e}")
        return False


def auto_add_customs_calls(results):
    """
    Automatically add PBNs returning CALL TO CUSTOMS
    to the live GitHub watchlist.

    Existing PBNs are not duplicated.
    """

    customs_results = [
        result for result in results
        if result.get("Status") == "🛑 CALL TO CUSTOMS"
    ]

    outcomes = {}

    if not customs_results:
        return outcomes

    repo = get_repo()

    if not repo:
        for result in customs_results:
            pbn = str(result.get("PBN ID", "")).strip().upper()
            outcomes[pbn] = "⚠️ GitHub unavailable — not added"

        return outcomes

    try:
        file_data = repo.get_contents(
            WATCHLIST_FILE,
            ref="main"
        )

        watchlist = json.loads(
            file_data.decoded_content.decode("utf-8")
        )

        if not isinstance(watchlist, list):
            raise ValueError("Watchlist must be a JSON list.")

    except Exception as e:
        st.error(f"Could not read GitHub watchlist: {e}")

        for result in customs_results:
            pbn = str(result.get("PBN ID", "")).strip().upper()
            outcomes[pbn] = "⚠️ Could not read watchlist"

        return outcomes

    existing_pbns = {
        str(item.get("pbn", "")).strip().upper()
        for item in watchlist
        if isinstance(item, dict)
    }

    additions = []

    for result in customs_results:
        pbn = str(result.get("PBN ID", "")).strip().upper()
        trailer = (
            str(result.get("Trailer", "Unknown")).strip()
            or "Unknown"
        )

        if not pbn:
            outcomes[pbn] = "⚠️ Missing PBN — not added"

        elif pbn in existing_pbns:
            outcomes[pbn] = "👁️ Already on watchlist"

        else:
            additions.append({
                "pbn": pbn,
                "trailer": trailer,
                "added_at": datetime.now().strftime(
                    "%d/%m/%Y %H:%M:%S"
                )
            })

            existing_pbns.add(pbn)

            outcomes[pbn] = (
                "🟠 Called to customs — Added to watchlist"
            )

    if additions:
        updated_watchlist = watchlist + additions

        try:
            repo.update_file(
                path=WATCHLIST_FILE,
                message="Automatically add customs-called PBNs",
                content=json.dumps(updated_watchlist, indent=2),
                sha=file_data.sha,
                branch="main"
            )

            # Update the local copy after GitHub confirms the save.
            with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
                json.dump(updated_watchlist, f, indent=2)

        except Exception as e:
            st.error(
                f"GitHub could not save the watchlist update: {e}"
            )

            for item in additions:
                outcomes[item["pbn"]] = (
                    "⚠️ Save failed — check GitHub watchlist"
                )

    return outcomes


# ============================================================
# SELENIUM / REVENUE FUNCTIONS
# ============================================================

def create_driver():
    """Create a headless Chrome browser."""

    options = webdriver.ChromeOptions()

    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    options.add_argument(
        "--disable-blink-features=AutomationControlled"
    )

    return webdriver.Chrome(options=options)


def get_visible_inputs(driver):
    """Return visible and enabled input elements."""

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
    """Find the visible PBN input on Revenue's page."""

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

    visible_inputs = get_visible_inputs(driver)

    if visible_inputs:
        return visible_inputs[0]

    return None


def click_get_channel(driver):
    """Find and click Revenue's Get your Channel button."""

    wait = WebDriverWait(driver, 10)

    try:
        button = wait.until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//button[contains("
                "translate(normalize-space(.),"
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
                "'abcdefghijklmnopqrstuvwxyz'),"
                "'get your channel'"
                ")]"
            ))
        )

        button.click()
        return True

    except Exception:
        pass

    try:
        button = wait.until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//input[contains("
                "translate(@value,"
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
                "'abcdefghijklmnopqrstuvwxyz'),"
                "'get your channel'"
                ")]"
            ))
        )

        button.click()
        return True

    except Exception:
        return False


def extract_trailer_number(page_text):
    """Attempt to extract the trailer or vehicle registration."""

    lines = [
        line.strip()
        for line in page_text.splitlines()
        if line.strip()
    ]

    for index, line in enumerate(lines):
        upper = line.upper()

        if (
            "TRAILER NUMBER" in upper
            or "VEHICLE REGISTRATION" in upper
        ):

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
    """Determine the Revenue Customs Channel result."""

    text = page_text.upper()

    if "INVALID PBN" in text:
        return "❌ INVALID PBN"

    if "CALL TO CUSTOMS" in text or "ORANGE" in text:
        return "🛑 CALL TO CUSTOMS"

    if "EXIT THE PORT" in text:
        return "✅ EXIT THE PORT"

    if "NOT READY" in text:
        return "⏳ CHANNEL NOT READY"

    return "❓ CHECK MANUALLY"


def check_pbn(driver, pbn):
    """Check one PBN against Revenue's Customs Channel Lookup."""

    driver.get(ROS_URL)

    wait = WebDriverWait(driver, 15)

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

    pbn_input.clear()
    pbn_input.send_keys(pbn)

    clicked = click_get_channel(driver)

    if not clicked:
        pbn_input.send_keys("\n")

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
    "and automatically add CALL TO CUSTOMS entries to the watchlist."
)

st.caption(
    "Revenue Customs Channel Lookup • "
    f"{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
)


# ============================================================
# SESSION STATE
# ============================================================

if "results" not in st.session_state:
    st.session_state.results = []

if "watchlist_outcomes" not in st.session_state:
    st.session_state.watchlist_outcomes = {}


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

    # Remove duplicate PBNs from the input.
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
                    result = check_pbn(driver, pbn)

                except Exception as e:
                    result = {
                        "PBN ID": pbn,
                        "Trailer": "N/A",
                        "Status": f"❌ FAILED: {str(e)[:80]}"
                    }

                results.append(result)

                progress_bar.progress(
                    (idx + 1) / len(pbn_list)
                )

            # Automatically add customs-called PBNs.
            outcomes = auto_add_customs_calls(results)

            # Add the watchlist outcome to each results row.
            for result in results:
                pbn = str(
                    result.get("PBN ID", "")
                ).strip().upper()

                result["Watchlist"] = outcomes.get(pbn, "—")

            st.session_state.watchlist_outcomes = outcomes
            st.session_state.results = results

            status_text.empty()
            progress_bar.empty()

            st.success(
                f"All {len(results)} PBN checks complete!"
            )

            added_count = sum(
                1 for outcome in outcomes.values()
                if outcome == (
                    "🟠 Called to customs — Added to watchlist"
                )
            )

            if added_count:
                st.success(
                    f"{added_count} PBN(s) automatically "
                    "added to the watchlist."
                )

        except Exception as e:
            st.session_state.results = []

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

    call_to_customs = [
        r for r in results
        if r.get("Status") == "🛑 CALL TO CUSTOMS"
    ]

    cleared = [
        r for r in results
        if r.get("Status") == "✅ EXIT THE PORT"
    ]

    invalid = [
        r for r in results
        if r.get("Status") == "❌ INVALID PBN"
    ]

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Checked", len(results))

    with col2:
        st.metric("Call to Customs", len(call_to_customs))

    with col3:
        st.metric("Exit the Port", len(cleared))

    with col4:
        st.metric("Invalid", len(invalid))

    st.dataframe(
        results,
        use_container_width=True,
        hide_index=True
    )


# ============================================================
# ACTIVE WATCHLIST
# ============================================================

st.divider()
st.subheader("👁️ Active Watchlist")

items = load_data()

if not items:
    st.info("Watchlist is empty.")

else:
    st.caption(
        f"{len(items)} PBN(s) currently being monitored "
        "by the GitHub watcher."
    )

    for idx, item in enumerate(items):
        trailer = item.get("trailer", "Unknown")
        pbn = item.get("pbn", "N/A")
        added_at = item.get("added_at", "N/A")

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
                latest_items = load_data()

                latest_items = [
                    item for item in latest_items
                    if str(item.get("pbn", "")).upper()
                    != str(pbn).upper()
                ]

                if save_data(latest_items):
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
