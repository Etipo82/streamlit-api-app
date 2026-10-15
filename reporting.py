"""
reporting.py  —  Standalone CXone API reporting app (Streamlit Cloud).
Customer-facing: credentials entered manually in sidebar.
Run with:  streamlit run reporting.py
"""

import streamlit as st
import requests
import jwt
import json
import base64
import urllib.parse
import pandas as pd
import io
import time
import pytz
from datetime import datetime, timedelta

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="CXone Reporting · NICE",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global dark theme ──────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Base ── */
[data-testid="stAppViewContainer"] { background:#0D1117; color:#E6EDF3; }
[data-testid="stSidebar"]          { background:#161B22; border-right:1px solid #30363D; }
[data-testid="stHeader"]           { background:transparent; }
section[data-testid="stSidebar"] * { color:#E6EDF3 !important; }

/* ── Metric cards ── */
div[data-testid="metric-container"] {
    background:#161B22; border:1px solid #30363D; border-radius:8px;
    padding:0.75rem 1rem; margin-bottom:0.5rem;
}
div[data-testid="metric-container"] label { color:#8B949E !important; font-size:0.78rem !important; }
div[data-testid="metric-container"] div[data-testid="stMetricValue"] {
    color:#E6EDF3 !important; font-size:1.6rem !important; font-weight:700;
}

/* ── Tables ── */
table { width:100%; border-collapse:collapse; font-size:0.82rem; }
thead tr { background:#161B22; }
th { color:#8B949E !important; font-weight:600; text-transform:uppercase;
     font-size:0.72rem; letter-spacing:0.05em; padding:0.55rem 0.75rem;
     border-bottom:1px solid #30363D; text-align:left; }
td { padding:0.45rem 0.75rem; border-bottom:1px solid #21262D; color:#E6EDF3; }
tr:hover td { background:#1C2128; }

/* ── Inputs ── */
input, textarea, select { background:#0D1117 !important; color:#E6EDF3 !important;
    border:1px solid #30363D !important; border-radius:6px !important; }
.stTextInput > label, .stDateInput > label, .stTimeInput > label,
.stSelectbox > label, .stNumberInput > label, .stCheckbox > label {
    color:#8B949E !important; font-size:0.8rem !important;
}

/* ── Buttons ── */
div.stButton > button {
    background:linear-gradient(135deg,#1F6FEB,#1158C7) !important;
    color:#fff !important; border:none !important; border-radius:6px !important;
    font-weight:600 !important; padding:0.45rem 1.1rem !important;
    transition:opacity .15s ease;
}
div.stButton > button:hover { opacity:0.88 !important; }

/* ── Download button ── */
div.stDownloadButton > button {
    background:linear-gradient(135deg,#238636,#196F2B) !important;
    color:#fff !important; border:none !important; border-radius:6px !important;
    font-weight:600 !important;
}

/* ── Alerts ── */
div[data-testid="stAlert"] { border-radius:6px !important; border-left:3px solid !important; }

/* ── Section header ── */
.sec-header {
    font-size:0.72rem; font-weight:700; text-transform:uppercase;
    letter-spacing:0.08em; color:#8B949E;
    border-bottom:1px solid #30363D; padding-bottom:0.35rem; margin-bottom:0.75rem;
}
.page-title {
    font-size:1.5rem; font-weight:700; color:#E6EDF3; margin:0;
}
.page-sub { font-size:0.85rem; color:#8B949E; margin-top:0.15rem; }

/* ── Progress bar ── */
.stProgress > div > div > div { background:#1F6FEB !important; }
</style>
""", unsafe_allow_html=True)

# ── Colour palette (mirrors api_page.py) ──────────────────────────────────────
C_ACC = "#00B5CC"
C_PRP = "#7C3AED"
C_OK  = "#3FB950"
C_WRN = "#D29922"
C_ERR = "#F85149"
C_GRY = "#30363D"

# ── Page header ───────────────────────────────────────────────────────────────
st.markdown("""
<div style="display:flex;align-items:center;gap:0.75rem;padding-bottom:0.75rem;
            border-bottom:1px solid #30363D;margin-bottom:1.25rem;">
    <span style="font-size:1.8rem">📋</span>
    <div>
        <div class="page-title">CXone Reporting</div>
        <div class="page-sub">Call lists · Completed contacts · Reporting jobs</div>
    </div>
    <span style="margin-left:auto;background:#1C2128;border:1px solid #30363D;
                 border-radius:20px;padding:0.2rem 0.75rem;font-size:0.7rem;
                 font-weight:700;color:#00B5CC;letter-spacing:0.06em;">LIVE</span>
</div>
""", unsafe_allow_html=True)


def _section(label: str):
    st.markdown(f'<div class="sec-header">{label}</div>', unsafe_allow_html=True)


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding:0.5rem 0 0.75rem;">
        <div style="font-size:0.9rem;font-weight:700;color:#E6EDF3;">⚡ CXone Portal</div>
        <div style="font-size:0.68rem;color:#8B949E;text-transform:uppercase;
                    letter-spacing:0.08em;">NICE CXone · Reporting</div>
    </div>
    <hr style="border-color:#30363D;margin:0 0 0.75rem;">
    """, unsafe_allow_html=True)

    # Account type
    issuer_options = {
        "Non-FedRamp": "cxone.niceincontact.com",
        "FedRamp":     "cxone-gov.niceincontact.com",
    }
    issuer_type = st.selectbox("Account Type", list(issuer_options.keys()), key="issuer_type")
    issuer = issuer_options[issuer_type]

    st.markdown('<hr style="border-color:#30363D;margin:0.5rem 0;">', unsafe_allow_html=True)

    # Credentials
    st.markdown('<div style="font-size:0.72rem;font-weight:700;color:#8B949E;'
                'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:0.5rem;">'
                '🔑 Credentials</div>', unsafe_allow_html=True)

    accessId         = st.text_input("Access ID",          key="access_id",     placeholder="username@domain")
    accessKeySecret  = st.text_input("Access Key Secret",  key="access_key_secret",  type="password")
    client_id        = st.text_input("Client ID",          key="client_id",     placeholder="app client id")
    client_secret    = st.text_input("Client Secret",      key="client_secret", type="password")

    st.markdown('<hr style="border-color:#30363D;margin:0.5rem 0;">', unsafe_allow_html=True)

    # View selector
    choice = st.selectbox(
        "Select Action",
        ["📞 Fetch Call Lists",
         "🗑️ Delete Deactivated Lists",
         "📊 Fetch Completed Contacts",
         "📋 Reporting Jobs"],
        key="choice",
    )

    # Debug
    st.markdown('<hr style="border-color:#30363D;margin:0.5rem 0;">', unsafe_allow_html=True)
    debug_mode = st.checkbox("🐛 Debug mode", key="debug_mode")


# ── Helpers ────────────────────────────────────────────────────────────────────
def debug_log(msg):
    if debug_mode:
        st.code(f"DEBUG: {msg}", language="text")


def iso_to_est(iso_time):
    if not iso_time:
        return None
    try:
        dt = datetime.strptime(iso_time, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=pytz.utc)
        return dt.astimezone(pytz.timezone("US/Eastern"))
    except Exception as e:
        debug_log(f"iso_to_est failed for '{iso_time}': {e}")
        return None


def _csv_btn(df: pd.DataFrame, filename: str, key: str):
    st.download_button(
        f"⬇ Download {filename}",
        data=df.to_csv(index=False),
        file_name=filename,
        mime="text/csv",
        key=key,
    )


# ── Authentication ─────────────────────────────────────────────────────────────
def get_auth_headers():
    if not all([accessId, accessKeySecret, client_id, client_secret]):
        return None, None, None
    try:
        encoded_creds = base64.b64encode(
            f"{client_id}:{urllib.parse.quote(client_secret)}".encode()
        ).decode()
        resp = requests.post(
            f"https://{issuer}/auth/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {encoded_creds}",
            },
            data={"grant_type": "password", "username": accessId, "password": accessKeySecret},
            timeout=15,
        )
        debug_log(f"Auth → {resp.status_code}")
        if resp.status_code != 200:
            st.sidebar.error(f"Auth failed: {resp.status_code}")
            return None, None, None

        access_token = resp.json().get("access_token")
        decoded      = jwt.decode(access_token, options={"verify_signature": False})
        tenant_id    = decoded.get("tenantId")

        discovery    = requests.get(
            f"https://{issuer}/.well-known/cxone-configuration?tenantId={tenant_id}",
            timeout=10,
        ).json()
        api_endpoint = discovery["api_endpoint"]
        endpoint     = api_endpoint + "/incontactAPI/services/v31.0"

        return {"Authorization": f"Bearer {access_token}"}, endpoint, tenant_id

    except Exception as e:
        st.sidebar.error(f"Auth error: {e}")
        return None, None, None


# ── Live dashboard (always shown when auth is valid) ──────────────────────────
def _show_live_dashboard(authHeaders, endpoint):
    _section("🟢 Live Activity")
    try:
        skills_resp = requests.get(f"{endpoint}/skills/activity", headers=authHeaders, timeout=10)
        active_resp = requests.get(
            f"{endpoint}/contacts/active?fields=skillName,stateName",
            headers=authHeaders, timeout=10
        )
        if skills_resp.status_code != 200:
            st.warning("Could not load live skills data.")
            return

        skills = skills_resp.json().get("skillActivity", [])
        if not skills:
            st.info("No active skill data at this time.")
            return

        df_sk = pd.DataFrame(skills)
        for col in ["queueCount", "agentsAvailable", "agentsWorking"]:
            df_sk[col] = pd.to_numeric(df_sk.get(col, 0), errors="coerce").fillna(0)

        total_active   = active_resp.json().get("totalRecords", 0) if active_resp.status_code == 200 else "N/A"
        in_queue       = int(df_sk["queueCount"].sum())
        available      = int(df_sk["agentsAvailable"].sum())
        working        = int(df_sk["agentsWorking"].sum())

        # Queue time
        est = pytz.timezone("US/Eastern")
        now_est = datetime.now(est)
        longest = avg_q = "N/A"
        if "earliestQueueTime" in df_sk.columns:
            def _q_mins(t):
                try:
                    dt = datetime.strptime(t, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=pytz.utc)
                    return (now_est - dt.astimezone(est)).total_seconds() / 60
                except Exception:
                    return None
            df_sk["_qmin"] = df_sk["earliestQueueTime"].apply(_q_mins)
            valid = df_sk["_qmin"].dropna()
            if not valid.empty:
                longest = f"{valid.max():.1f} min"
                avg_q   = f"{valid.mean():.1f} min"

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Active Contacts", total_active)
        c2.metric("In Queue",        in_queue)
        c3.metric("Available",       available)
        c4.metric("Working",         working)
        c5.metric("Longest Queue",   longest)
        c6.metric("Avg Queue",       avg_q)

        st.markdown(
            f'<div style="font-size:0.72rem;color:#8B949E;margin-top:0.25rem;">'
            f'Last refreshed: {now_est.strftime("%b %d, %Y %I:%M %p ET")}</div>',
            unsafe_allow_html=True,
        )

    except Exception as e:
        st.warning(f"Live dashboard unavailable: {e}")


# ── View: Fetch Call Lists ─────────────────────────────────────────────────────
def _view_call_lists(authHeaders, endpoint):
    _section("📞 Call Lists")
    st.caption("Fetch all call lists for this business unit. Deactivated lists are highlighted.")

    if st.button("▶ Fetch Call Lists", type="primary", key="btn_fetch_cl"):
        with st.spinner("Fetching call lists…"):
            resp = requests.get(f"{endpoint}/lists/call-lists", headers=authHeaders, timeout=15)
        if resp.status_code != 200:
            st.error(f"API error: {resp.status_code}")
            return

        data   = resp.json()
        lists  = data.get("callingLists", [])
        if not lists:
            st.info("No call lists found.")
            return

        df = pd.DataFrame(lists)
        total      = len(df)
        active     = int((df.get("status", pd.Series()) == "Active").sum())    if "status" in df.columns else "N/A"
        deact      = int((df.get("status", pd.Series()) == "Deactivated").sum()) if "status" in df.columns else "N/A"

        c1, c2, c3 = st.columns(3)
        c1.metric("Total Lists",       total)
        c2.metric("Active",            active)
        c3.metric("Deactivated",       deact)

        st.markdown("---")
        _section("All Call Lists")
        st.table(df.astype(str))

        _csv_btn(df, "call_lists.csv", "dl_cl_all")

        # Deactivated-only download
        if "status" in df.columns:
            df_deact = df[df["status"] == "Deactivated"]
            if not df_deact.empty:
                st.markdown("---")
                _section(f"⚠️ Deactivated Lists ({len(df_deact)})")
                st.caption("Download this file and upload it to the Delete tab to remove these lists.")
                st.table(df_deact[["listId"] + [c for c in df_deact.columns if c != "listId"]].head(50).astype(str))
                _csv_btn(df_deact[["listId"]], "deactivated_list_ids.csv", "dl_cl_deact")


# ── View: Delete Deactivated Lists ────────────────────────────────────────────
def _view_delete_lists(authHeaders, endpoint):
    _section("🗑️ Delete Deactivated Lists")
    st.caption(
        "Upload a CSV with a **listId** column (use the download from Fetch Call Lists). "
        "Each list will be permanently deleted with `forceInactive=true&forceDelete=true`."
    )
    st.warning("⚠️ This action is **irreversible**. Double-check the file before proceeding.")

    uploaded = st.file_uploader("Upload list ID CSV", type=["csv"], key="del_upload")
    if not uploaded:
        return

    df_ids = pd.read_csv(uploaded)
    if "listId" not in df_ids.columns:
        st.error("CSV must contain a `listId` column.")
        return

    list_ids = df_ids["listId"].dropna().astype(int).tolist()
    st.info(f"**{len(list_ids)}** list ID(s) loaded from file.")
    st.table(pd.DataFrame({"listId": list_ids[:20]}).astype(str))
    if len(list_ids) > 20:
        st.caption(f"Showing first 20 of {len(list_ids)}.")

    if st.button(f"🗑️ Delete {len(list_ids)} Lists", type="primary", key="btn_del"):
        deleted, failed = 0, 0
        progress = st.progress(0)
        status   = st.empty()
        results  = []

        for idx, list_id in enumerate(list_ids):
            url    = f"{endpoint}/lists/call-lists/{list_id}?forceInactive=true&forceDelete=true"
            resp   = requests.delete(url, headers=authHeaders, timeout=10)
            ok     = resp.status_code == 200
            if ok:
                deleted += 1
            else:
                failed += 1
            results.append({"listId": list_id, "status": "Deleted" if ok else f"Failed ({resp.status_code})"})
            progress.progress((idx + 1) / len(list_ids))
            status.text(f"Processing {idx + 1}/{len(list_ids)} — ID {list_id}")
            debug_log(f"DELETE {list_id} → {resp.status_code}")

        progress.empty()
        status.empty()

        if deleted:
            st.success(f"✅ Successfully deleted **{deleted}** list(s).")
        if failed:
            st.error(f"❌ Failed to delete **{failed}** list(s).")

        st.table(pd.DataFrame(results).astype(str))
        _csv_btn(pd.DataFrame(results), "delete_results.csv", "dl_del_res")


# ── View: Fetch Completed Contacts ────────────────────────────────────────────
def _view_completed_contacts(authHeaders, endpoint):
    _section("📊 Fetch Completed Contacts")
    st.caption("Pull a date-range extract of completed contacts and download as CSV.")

    c1, c2, c3, c4 = st.columns(4)
    start_date = c1.date_input("Start Date", (datetime.now() - timedelta(days=1)).date(), key="cc_sd")
    start_time = c2.time_input("Start Time", datetime.strptime("00:00", "%H:%M").time(), key="cc_st")
    end_date   = c3.date_input("End Date",   datetime.now().date(),                      key="cc_ed")
    end_time   = c4.time_input("End Time",   datetime.strptime("23:59", "%H:%M").time(), key="cc_et")

    col_a, col_b = st.columns(2)
    fetch_all = col_a.checkbox("Fetch all pages (may be slow for large date ranges)", key="cc_all")
    top       = col_b.number_input("Records per request", min_value=1000, max_value=10000, value=10000, step=1000, key="cc_top")

    if not st.button("▶ Fetch Completed Contacts", type="primary", key="btn_cc"):
        return

    s_dt = f"{start_date.strftime('%m/%d/%Y')} {start_time.strftime('%H:%M')}"
    e_dt = f"{end_date.strftime('%m/%d/%Y')} {end_time.strftime('%H:%M')}"

    all_records = []
    skip        = 0
    page        = 1
    url         = f"{endpoint}/contacts/completed"
    progress    = st.progress(0)
    status      = st.empty()

    with st.spinner("Fetching contacts…"):
        while True:
            params = {"startDate": s_dt, "endDate": e_dt, "top": int(top), "skip": skip}
            debug_log(f"GET {url} params={params}")
            resp = requests.get(url, headers=authHeaders, params=params, timeout=30)
            debug_log(f"→ {resp.status_code}")

            if resp.status_code != 200:
                st.error(f"API error on page {page}: {resp.status_code}")
                break

            contacts = resp.json().get("completedContacts", [])
            if not contacts:
                break

            all_records.extend(contacts)
            status.text(f"Page {page} — {len(all_records):,} records fetched…")
            progress.progress(min(len(all_records) / max(len(all_records) + int(top), 1), 0.95))

            if not fetch_all:
                break
            skip += int(top)
            page += 1
            time.sleep(0.5)

    progress.progress(1.0)
    progress.empty()
    status.empty()

    if not all_records:
        st.warning("No records found for this date range and criteria.")
        return

    df = pd.DataFrame(all_records)

    # ── KPIs ──────────────────────────────────────────────────────────────────
    st.markdown("---")
    _section("📈 Summary")

    total = len(df)
    abandoned = int(df["abandoned"].sum()) if "abandoned" in df.columns else "N/A"
    inbound   = int((df["isOutbound"] == False).sum()) if "isOutbound" in df.columns else "N/A"  # noqa: E712

    def _safe_mean(col, divisor=60):
        if col not in df.columns:
            return "N/A"
        val = pd.to_numeric(df[col], errors="coerce").mean()
        return f"{val/divisor:.1f} min" if pd.notna(val) else "N/A"

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total Contacts",  f"{total:,}")
    k2.metric("Inbound",         f"{inbound:,}" if isinstance(inbound, int) else inbound)
    k3.metric("Abandoned",       f"{abandoned:,}" if isinstance(abandoned, int) else abandoned)
    k4.metric("Avg Handle Time", _safe_mean("totalDurationSeconds"))
    k5.metric("Avg Queue Time",  _safe_mean("inQueueSeconds"))

    # ── Preview table ─────────────────────────────────────────────────────────
    st.markdown("---")
    _section(f"Preview (first 50 of {total:,} rows)")
    preview_cols = [c for c in [
        "contactId","contactStartDate","skillName","teamName","fromAddress",
        "endReason","totalDurationSeconds","inQueueSeconds","abandoned","isOutbound",
    ] if c in df.columns]
    st.table(df[preview_cols].head(50).astype(str))

    # ── Download ──────────────────────────────────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    _csv_btn(df, f"completed_contacts_{ts}.csv", "dl_cc")
    st.success(f"✅ **{total:,}** completed contacts ready for download.")


# ── View: Reporting Jobs ──────────────────────────────────────────────────────
def _view_reporting_jobs(authHeaders, endpoint):
    _section("📋 Reporting Jobs")
    st.caption(
        "Enter a Report ID to start a job. The app polls until the report is finished "
        "then provides a download link."
    )

    col_a, col_b = st.columns(2)
    report_id       = col_a.text_input("Report ID", key="rj_id",    placeholder="e.g. 12345")
    additional_param = col_b.text_input("Additional Parameter (optional)", key="rj_param", value="value")

    if not st.button("▶ Run Report", type="primary", key="btn_rj") or not report_id.strip():
        if not report_id.strip() and st.session_state.get("btn_rj"):
            st.warning("Please enter a Report ID.")
        return

    start_url = (
        f"{endpoint}/report-jobs/{report_id.strip()}"
        "?fileType=CSV&includeHeaders=true&appendDate=true&overwrite=true"
    )
    payload = {"additionalParam": additional_param}
    debug_log(f"POST {start_url}  payload={payload}")

    with st.spinner("Starting report job…"):
        start_resp = requests.post(start_url, headers=authHeaders, json=payload, timeout=15)
    debug_log(f"Start → {start_resp.status_code}")

    if start_resp.status_code != 202:
        st.error(f"Failed to start job. Status: {start_resp.status_code}  {start_resp.text[:200]}")
        return

    job_id = start_resp.json().get("jobId")
    if not job_id:
        st.warning("No job ID returned.")
        return

    st.success(f"Job started — **Job ID:** `{job_id}`")

    # ── Poll for completion ────────────────────────────────────────────────────
    status_url = f"{endpoint}/report-jobs/{job_id}"
    max_polls  = 20
    poll_secs  = 30
    file_url   = ""
    progress   = st.progress(0)
    status_box = st.empty()

    for attempt in range(1, max_polls + 1):
        debug_log(f"Poll {attempt}/{max_polls} → {status_url}")
        poll_resp = requests.get(status_url, headers=authHeaders, timeout=15)
        debug_log(f"Poll → {poll_resp.status_code}")

        if poll_resp.status_code != 200:
            st.error(f"Status check failed: {poll_resp.status_code}")
            break

        job_data = poll_resp.json().get("jobResult", {})
        state    = job_data.get("state", "Unknown")
        status_box.info(f"Report status: **{state}**  (check {attempt}/{max_polls})")
        progress.progress(attempt / max_polls)

        if state == "Finished":
            file_url = job_data.get("resultFileURL", "")
            break

        if state in ("Failed", "Error"):
            st.error(f"Report job failed with state: {state}")
            break

        time.sleep(poll_secs)

    progress.empty()
    status_box.empty()

    if not file_url:
        if attempt >= max_polls:
            st.warning("Timed out waiting for the report. Try again or check the Report Manager.")
        return

    # ── Download the result file ──────────────────────────────────────────────
    st.success("✅ Report is ready!")
    with st.spinner("Downloading report file…"):
        file_resp = requests.get(file_url, headers=authHeaders, timeout=30)
    debug_log(f"File download → {file_resp.status_code}")

    if file_resp.status_code != 200:
        st.error(f"Failed to download file: {file_resp.status_code}")
        return

    try:
        file_json    = file_resp.json()
        encoded_data = file_json["files"]["file"]
        file_name    = file_json["files"]["fileName"]
        decoded_data = base64.b64decode(encoded_data)

        st.download_button(
            f"⬇ Download {file_name}",
            data=decoded_data,
            file_name=file_name,
            key="dl_rj",
        )
    except Exception as e:
        st.error(f"Error parsing report file: {e}")
        debug_log(f"File parse error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# Main flow
# ══════════════════════════════════════════════════════════════════════════════

if not all([accessId, accessKeySecret, client_id, client_secret]):
    st.info("👈  Enter your CXone credentials in the sidebar to get started.")
    st.stop()

# Authenticate once per session (or when creds change)
cred_key = f"{accessId}|{client_id}|{issuer}"
if st.session_state.get("_auth_key") != cred_key:
    with st.spinner("Authenticating…"):
        authHeaders, endpoint, tenant_id = get_auth_headers()
    if authHeaders:
        st.session_state["_auth_key"]     = cred_key
        st.session_state["_authHeaders"]  = authHeaders
        st.session_state["_endpoint"]     = endpoint
        st.session_state["_tenant_id"]    = tenant_id
        st.sidebar.success(f"✅ Connected  ·  Tenant: {tenant_id}")
    else:
        st.session_state.pop("_auth_key", None)
        st.stop()
else:
    authHeaders = st.session_state["_authHeaders"]
    endpoint    = st.session_state["_endpoint"]
    tenant_id   = st.session_state.get("_tenant_id", "")
    st.sidebar.success(f"✅ Connected  ·  Tenant: {tenant_id}")

# ── Live dashboard (always shown) ──────────────────────────────────────────────
_show_live_dashboard(authHeaders, endpoint)

st.markdown("---")

# ── Route to selected view ─────────────────────────────────────────────────────
if   choice == "📞 Fetch Call Lists":
    _view_call_lists(authHeaders, endpoint)
elif choice == "🗑️ Delete Deactivated Lists":
    _view_delete_lists(authHeaders, endpoint)
elif choice == "📊 Fetch Completed Contacts":
    _view_completed_contacts(authHeaders, endpoint)
elif choice == "📋 Reporting Jobs":
    _view_reporting_jobs(authHeaders, endpoint)
