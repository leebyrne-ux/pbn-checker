import os
import json
import streamlit as st
from datetime import datetime
from github import Github

st.set_page_config(page_title="PBN Checker", page_icon="🚚", layout="centered")

FILE = "watchlist.json"

def get_repo():
    tok = st.secrets.get("GITHUB_TOKEN")
    name = st.secrets.get("REPO_NAME")
    if tok and name:
        try:
            return Github(tok).get_repo(name)
        except Exception as e:
            st.error(f"GitHub Error: {e}")
    return None

def load_data():
    repo = get_repo()
    if repo:
        try:
            res = repo.get_contents(FILE, ref="main")
            raw = res.decoded_content.decode("utf-8")
            data = json.loads(raw)
            with open(FILE, "w") as f:
                json.dump(data, f, indent=2)
            return data
        except Exception:
            pass
    if os.path.exists(FILE):
        try:
            with open(FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_data(data):
    with open(FILE, "w") as f:
        json.dump(data, f, indent=2)
    repo = get_repo()
    if repo:
        try:
            res = repo.get_contents(FILE, ref="main")
            body = json.dumps(data, indent=2)
            repo.update_file(
                path=FILE,
                message="Update watchlist",
                content=body,
                sha=res.sha,
                branch="main"
            )
            st.toast("Saved to GitHub!", icon="🚀")
        except Exception as e:
            st.error(f"Sync error: {e}")

st.title("Customs PBN Batch Checker")
st.caption(f"Time: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

items = load_data()

st.subheader("Add PBNs to Watchlist")

with st.form("add_form", clear_on_submit=True):
    txt = st.text_area("Paste PBNs and Trailers", placeholder="RX23VN92\nGTC415 RX23VN92", height=120)
    btn = st.form_submit_button("Add to Watchlist")

if btn and txt.strip():
    added = 0
    t_stamp = datetime.now().strftime("%H:%M:%S")
    existing = {x.get("pbn") for x in items}
    
    for line in txt.strip().split("\n"):
        parts = line.replace(",", " ").split()
        if len(parts) == 1:
            pbn_id = parts[0].strip().upper()
            if pbn_id not in existing:
                items.append({"pbn": pbn_id, "trailer": "Unknown", "added_at": t_stamp})
                added += 1
        elif len(parts) >= 2:
            tr_id = parts[0].strip().upper()
            pbn_id = parts[1].strip().upper()
            if pbn_id not in existing:
                items.append({"trailer": tr_id, "pbn": pbn_id, "added_at": t_stamp})
                added += 1
                
    if added > 0:
        save_data(items)
        st.rerun()
    else:
        st.info("Items already on watchlist.")

st.divider()
st.subheader("Active Watchlist")

if not items:
    st.info("Watchlist is empty.")
else:
    for idx, item in enumerate(items):
        tr = item.get("trailer", "Unknown")
        pb = item.get("pbn", "N/A")
        ts = item.get("added_at", "N/A")
        
        c1, c2 = st.columns([5, 1])
        with c1:
            st.info(f"Trailer: {tr} | PBN: {pb} | Added: {ts}")
        with c2:
            if st.button("Delete", key=f"del_{idx}"):
                items.pop(idx)
                save_data(items)
                st.rerun()

if st.button("Sync / Refresh"):
    st.rerun()
