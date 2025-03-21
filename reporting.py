import streamlit as st
import requests
import jwt
import json
import base64
import urllib
import pandas as pd
import zipfile
import io
import os
import time
from datetime import datetime

# Set page title
st.title("API Tenant Management")

# Define issuer options
issuer_options = {"Non-FedRamp": "cxone.niceincontact.com", "FedRamp": "cxone-gov.niceincontact.com"}
issuer_type = st.sidebar.selectbox("Select Account Type:", ["Non-FedRamp", "FedRamp"], key="issuer_type")
issuer = issuer_options[issuer_type]

# Debugging toggle
debug_mode = st.sidebar.checkbox("Enable Debugging", key="debug_mode")

def debug_log(message):
    """Print debug messages when debugging is enabled."""
    if debug_mode:
        st.write(f"DEBUG: {message}")

# Sidebar for authentication
with st.sidebar:
    st.write("Credentials")
    accessId = st.text_input("Enter your Access ID:", key="access_id")
    accessKeySecret = st.text_input("Enter your Access Key Secret:", type="password", key="access_key_secret")
    client_id = st.text_input("Enter your Client ID:", key="client_id")
    client_secret = st.text_input("Enter your Client Secret:", type="password", key="client_secret")
    
    choice = st.selectbox("Choose an API call:", [
        "Download MP4", 
        "Fetch Call Lists", 
        "Delete Deactivated Lists", 
        "Fetch Completed Contacts", 
        "Reporting Jobs"
    ])

def get_auth_headers():
    """Fetch and return authentication headers."""
    if not all([accessId, accessKeySecret, client_id, client_secret]):
        st.sidebar.warning("Please enter credentials.")
        return None
    try:
        encoded_creds = base64.b64encode(f"{client_id}:{urllib.parse.quote(client_secret)}".encode()).decode()
        response = requests.post(
            f"https://{issuer}/auth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {encoded_creds}"},
            data={"grant_type": "password", "username": accessId, "password": accessKeySecret},
        )
        debug_log(f"Auth request sent to {issuer}/auth/token")
        if response.status_code == 200:
            token = response.json().get("access_token")
            debug_log(f"Token received: {token}")
            return {"Authorization": f"Bearer {token}"}
        else:
            st.error(f"Authentication failed: {response.status_code}")
    except Exception as e:
        st.error(f"Error fetching token: {e}")
    return None

@st.cache_data(ttl=300)
def fetch_call_list():
    """Retrieve call list data."""
    url = f"https://{issuer}/incontactAPI/services/v31.0/lists/call-lists"
    response = requests.get(url, headers=authHeaders)
    return response.json() if response.status_code == 200 else None

def fetch_completed_contacts(start_date, start_time, end_date, end_time, fetch_all, top):
    """Retrieve completed contacts from API."""
    skip = 0
    all_records = []
    url = f"https://{issuer}/incontactAPI/services/v31.0/contacts/completed"
    while True:
        params = {
            "startDate": f"{start_date} {start_time}",
            "endDate": f"{end_date} {end_time}",
            "top": top,
            "skip": skip,
        }
        debug_log(f"Fetching completed contacts from: {url} with params: {params}")
        response = requests.get(url, headers=authHeaders, params=params)
        debug_log(f"Response Status: {response.status_code}")
        if response.status_code != 200:
            debug_log(f"Error response content: {response.text}")
            break
        try:
            response_json = response.json()
            contacts = response_json.get("completedContacts", [])
            if not contacts:
                break
            all_records.extend(contacts)
            debug_log(f"Fetched {len(contacts)} contacts, Total so far: {len(all_records)}")
            if not fetch_all:
                break
            skip += top
            time.sleep(1)
        except json.JSONDecodeError:
            debug_log("Failed to decode JSON response")
            break
    if all_records:
        df = pd.DataFrame(all_records)
        debug_log(f"Final record count: {len(df)}")
        st.download_button("Download Completed Contacts CSV", data=df.to_csv(index=False), file_name="completed_contacts.csv", mime="text/csv")
    else:
        st.warning("No valid records found.")
        debug_log("No records retrieved from API.")

def download_mp4_from_callid(callid):
    """Download MP4 file from given call ID."""
    url = f"https://{issuer}/media-playback/v1/contacts"
    params = {"acd-call-id": callid, "media-type": "all", "exclude-waveforms": "true", "isDownload": "false"}
    response = requests.get(url, headers=authHeaders, params=params)
    if response.status_code == 200:
        interactions = response.json().get("interactions", [])
        if interactions:
            file_url = interactions[0].get("data", {}).get("fileToPlayUrl", "")
            if file_url:
                mp4_response = requests.get(file_url)
                return mp4_response.content, f"{callid}.mp4"
    st.error(f"Failed to fetch MP4 for Call ID: {callid}")
    return None, None

def download_deactivated_call_lists():
    """Download deactivated call lists as CSV."""
    data = fetch_call_list()
    if data:
        deactivated_lists = [{"listId": item["listId"]} for item in data.get("callingLists", []) if item.get("status") == "Deactivated"]
        if deactivated_lists:
            df = pd.DataFrame(deactivated_lists)
            csv_buffer = io.StringIO()
            df.to_csv(csv_buffer, index=False)
            st.download_button("Download Deactivated Call Lists CSV", data=csv_buffer.getvalue(), file_name="deactivated_call_lists.csv", mime="text/csv")
    else:
        st.error("No data available to create the CSV file.")

def delete_deactivated_lists_from_csv(uploaded_file):
    """Delete deactivated lists using a CSV file."""
    if uploaded_file is not None:
        df = pd.read_csv(uploaded_file)
        list_ids = df["listId"].tolist()
        deleted_count = 0
        failed_count = 0
        
        progress_bar = st.progress(0)
        status_text = st.empty()

        for idx, list_id in enumerate(list_ids):
            delete_url = f"https://{issuer}/incontactAPI/services/v31.0/lists/call-lists/{list_id}?forceInactive=true&forceDelete=true"
            debug_log(f"Sending DELETE request to: {delete_url}")
            response = requests.delete(delete_url, headers=authHeaders)
            debug_log(f"Response Status: {response.status_code}")
            
            progress = (idx + 1) / len(list_ids)
            progress_bar.progress(progress)
            status_text.text(f"Processing {idx + 1}/{len(list_ids)}: List ID {list_id}")

            if response.status_code == 200:
                deleted_count += 1
                st.info(f"Successfully deleted list ID: {list_id}")
            else:
                failed_count += 1
                st.warning(f"Failed to delete list with ID: {list_id}. Status code: {response.status_code}")

        st.success(f"Completed processing. Deleted {deleted_count} lists.")
        if failed_count > 0:
            st.error(f"Failed to delete {failed_count} lists.")

def reporting(authHeaders, endpoint):
    """Handle reporting API services."""
    st.title("Reporting API Services")

    def report_id():
        job_id = st.text_input("Enter Job ID:", key="report_job_id")
        if st.button("Check Status"):
            if job_id:
                url = f"{endpoint}/report-jobs/{job_id}"
                debug_log(f"Fetching report status from: {url}")
                response = requests.get(url, headers=authHeaders)
                debug_log(f"Response Status: {response.status_code}")
                if response.status_code == 200:
                    try:
                        data = response.json().get("jobResult", {})
                        debug_log(f"Report Data: {data}")
                        st.markdown(f"**Report Job ID:** {data.get('jobId', 'N/A')}")
                        st.markdown(f"**Report Name:** {data.get('reportName', 'N/A')}")
                        st.markdown(f"**File Name:** {data.get('fileName', 'N/A')}")
                        st.markdown(f"**File URL:** {data.get('resultFileURL', 'N/A')}")
                        st.markdown(f"**State:** {data.get('state', 'N/A')}")
                    except json.JSONDecodeError:
                        debug_log("Failed to parse JSON response")
                else:
                    st.error(f"Failed to fetch report details. Status code: {response.status_code}")

    def start_job():
        report_id = st.text_input("Enter Report ID:", key="start_report_id")
        additional_param = st.text_input("Enter Additional Parameter (Optional):", value="value", key="start_report_param")
        payload = {"additionalParam": additional_param}

        if st.button("Start Job"):
            if not report_id:
                st.error("Report ID is required to start a job.")
                return

            url = f"{endpoint}/report-jobs/{report_id}?fileType=CSV&includeHeaders=true&appendDate=true&overwrite=true"
            debug_log(f"Starting report job with URL: {url} and payload: {payload}")
            response = requests.post(url, headers=authHeaders, json=payload)
            debug_log(f"Response Status: {response.status_code}")

            if response.status_code == 202:
                try:
                    response_data = response.json()
                    job_id = response_data.get("jobId", None)
                    debug_log(f"Job Started Successfully. Job ID: {job_id}")
                    if job_id:
                        st.success(f"Job started successfully with Job ID: {job_id}")
                    else:
                        st.warning("Job started successfully, but no Job ID was returned.")
                except json.JSONDecodeError:
                    debug_log("Failed to parse JSON response")
            else:
                st.error(f"Failed to start job. Status code: {response.status_code}")
    
    st.sidebar.success("Successfully connected!")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("View Report by ID")
        report_id()
    with col2:
        st.subheader("Start a Report Job")
        start_job()

    # Add the input box for the report file URL
    st.subheader("Download Report File")
    report_url = st.text_input("Enter Report File URL:", key="report_file_url")
    if st.button("Download Report"):
        try:
            debug_log(f"Downloading report file from URL: {report_url}")
            response = requests.get(report_url, headers=authHeaders)
            debug_log(f"Response Status: {response.status_code}")
            if response.status_code == 200:
                json_data = response.json()
                encoded_data = json_data['files']['file']
                file_name = json_data['files']['fileName']
                decoded_data = base64.b64decode(encoded_data)
                st.download_button("Download File", decoded_data, file_name)
            else:
                st.error(f"Failed to download the file. Status code: {response.status_code}")
        except Exception as e:
            debug_log(f"Error downloading report: {e}")
            st.error(f"Error downloading report: {e}")

authHeaders = get_auth_headers()

if authHeaders:
    if choice == "Reporting Jobs":
        reporting(authHeaders, f"https://{issuer}/incontactAPI/services/v31.0")
    elif choice == "Delete Deactivated Lists":
        uploaded_file = st.file_uploader("Upload CSV file of deactivated list IDs to delete", type=["csv"])
        if uploaded_file:
            if st.button("Delete Deactivated Lists"):
                delete_deactivated_lists_from_csv(uploaded_file)
    if choice == "Download MP4":
        callid = st.text_input("Enter the Call ID:")
        if st.button('Submit'):
            mp4_content, filename = download_mp4_from_callid(callid)
            if mp4_content and filename:
                st.download_button(label=f"Download {filename}", data=mp4_content, file_name=filename, mime="video/mp4")
    elif choice == "Fetch Call Lists":
        if st.button('Fetch Call Lists'):
            download_deactivated_call_lists()
    elif choice == "Fetch Completed Contacts":
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            start_date = st.date_input("Start Date").strftime("%m/%d/%Y")
        with col2:
            start_time = st.time_input("Start Time").strftime("%H:%M")
        with col3:
            end_date = st.date_input("End Date").strftime("%m/%d/%Y")
        with col4:
            end_time = st.time_input("End Time").strftime("%H:%M")
        fetch_all = st.checkbox("Fetch All Records")
        top = st.number_input("Max Records Per Request (1000-10000):", min_value=1000, max_value=10000, value=10000)
        if st.button("Fetch Completed Contacts"):
            fetch_completed_contacts(start_date, start_time, end_date, end_time, fetch_all, top)
else:
    st.warning("Please enter credentials in the sidebar before proceeding.")
