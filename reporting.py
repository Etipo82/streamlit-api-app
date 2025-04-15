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
from streamlit_extras.metric_cards import style_metric_cards
import pytz



st.set_page_config(page_title="My Webpage", page_icon=":calendar:", layout="wide")

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

def iso_to_est(iso_time):
    if iso_time is None:
        return None
    try:
        dt = datetime.strptime(iso_time, '%Y-%m-%dT%H:%M:%S.%fZ')
        dt = dt.replace(tzinfo=pytz.utc)
        dt_eastern = dt.astimezone(pytz.timezone('US/Eastern'))
        return dt_eastern
    except Exception as e:
        debug_log(f"Failed to parse ISO time '{iso_time}': {e}")
        return None

# Sidebar for authentication
with st.sidebar:
    st.write("Credentials")
    accessId = st.text_input("Enter your Access ID:", key="access_id")
    accessKeySecret = st.text_input("Enter your Access Key Secret:", type="password", key="access_key_secret")
    client_id = st.text_input("Enter your Client ID:", key="client_id")
    client_secret = st.text_input("Enter your Client Secret:", type="password", key="client_secret")
    
    choice = st.selectbox("Choose an API call:", [ 
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

def calculate_queue_times(df):
    current_time_est = datetime.now(pytz.timezone('US/Eastern'))

    df['earliestQueueTime'] = df['earliestQueueTime'].apply(lambda x: current_time_est if x == "N/A" or pd.isna(x) else iso_to_est(x))

    # Ensure datetime type before using .dt accessor
    if not pd.api.types.is_datetime64_any_dtype(df['earliestQueueTime']):
        debug_log("earliestQueueTime column is not datetime64; attempting conversion.")
        df['earliestQueueTime'] = pd.to_datetime(df['earliestQueueTime'], errors='coerce')

    df['queueDuration'] = (current_time_est - df['earliestQueueTime']).dt.total_seconds() / 60.0
    longest_queue_time = df['queueDuration'].max()
    average_queue_time = df['queueDuration'].mean()
    return longest_queue_time, average_queue_time

def calculate_percentage_change(last_value, current_value):
    if last_value > 0:
        return (current_value - last_value) / last_value
    return 0

def fetch_total_records():
    url = f"https://{issuer}/incontactAPI/services/v31.0/contacts/active?fields=skillName%2C%20stateName"
    response = requests.get(url, headers=authHeaders)
    try:
        return response.json().get('totalRecords', 0)
    except Exception:
        return 0

def display_summary_metrics_with_delta(current_summary, total_records):
    st.subheader('Live Dashboard')

    if 'last_summary' not in st.session_state:
        st.session_state['last_summary'] = current_summary.copy()
    if 'last_total_records' not in st.session_state:
        st.session_state['last_total_records'] = total_records

    delta_total_records = total_records - st.session_state['last_total_records']
    st.session_state['last_total_records'] = total_records

    st.write("Displaying data at:", datetime.now())

    metrics = ['queueCount', 'agentsAvailable', 'agentsWorking', 'longestQueueTime', 'averageQueueTime']
    metrics_display = metrics + ['Total Records']
    columns = st.columns(len(metrics_display))

    for i, metric in enumerate(metrics_display):
        with columns[i]:
            if metric == 'Total Records':
                st.metric(label="Active Contacts", value=f"{total_records}", delta=f"{delta_total_records}")
            else:
                percentage_change = calculate_percentage_change(
                    st.session_state['last_summary'].get(metric, 0),
                    current_summary.get(metric, 0)
                )
                delta_value = current_summary.get(metric, 0) - st.session_state['last_summary'].get(metric, 0)
                st.metric(label=f"Total {metric}", value=f"{current_summary.get(metric, 0):.2f}", delta=f"{delta_value:.2f}")

                if abs(percentage_change) >= 0.05:
                    warningMessage = f"Alert: {metric} has changed by {percentage_change * 100:.2f}% since the last check."
                    debug_log(warningMessage)

    st.session_state['last_summary'] = current_summary.copy()

def fetch_live_dashboard_data():
    url = f"https://{issuer}/incontactAPI/services/v31.0/skills/activity"
    try:
        response = requests.get(url, headers=authHeaders)
        if response.status_code == 200:
            skills_data = response.json().get('skillActivity', [])
            if skills_data:
                df = pd.DataFrame(skills_data)
                longest_queue_time, average_queue_time = calculate_queue_times(df)
                current_summary = df[['queueCount', 'agentsAvailable', 'agentsWorking']].sum()
                current_summary['longestQueueTime'] = longest_queue_time
                current_summary['averageQueueTime'] = average_queue_time
                total_records = fetch_total_records()
                display_summary_metrics_with_delta(current_summary, total_records)
                style_metric_cards(background_color="#000000", border_left_color="#686664", border_color="#000000", box_shadow="#F71938")
        else:
            st.warning("Could not retrieve dashboard data.")
    except Exception as e:
        st.warning(f"Live dashboard unavailable: {e}")

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

    report_id_input = st.text_input("Enter Report ID:", key="auto_report_id")
    additional_param = st.text_input("Enter Additional Parameter (Optional):", value="value", key="auto_report_param")

    if report_id_input:
        # Step 1: Start the report job
        payload = {"additionalParam": additional_param}
        start_url = f"{endpoint}/report-jobs/{report_id_input}?fileType=CSV&includeHeaders=true&appendDate=true&overwrite=true"
        debug_log(f"Starting report job with URL: {start_url} and payload: {payload}")
        start_response = requests.post(start_url, headers=authHeaders, json=payload)
        debug_log(f"Start Job Response Status: {start_response.status_code}")

        if start_response.status_code == 202:
            job_id = start_response.json().get("jobId")
            if job_id:
                st.success(f"Job started successfully. Job ID: {job_id}")
                status_url = f"{endpoint}/report-jobs/{job_id}"
                with st.spinner("Waiting for report to be generated..."):
                    status = ""
                    file_url = ""
                    max_retries = 20  # roughly 10 minutes if each wait is 30s
                    retries = 0
                    while status != "Finished" and retries < max_retries:
                        debug_log(f"Checking status from: {status_url}")
                        status_response = requests.get(status_url, headers=authHeaders)
                        debug_log(f"Status Check Response: {status_response.status_code}")
                        if status_response.status_code == 200:
                            job_data = status_response.json().get("jobResult", {})
                            status = job_data.get("state", "")
                            debug_log(f"Current State: {status}")
                            st.info(f"Report Status: {status}")
                            if status == "Finished":
                                file_url = job_data.get("resultFileURL", "")
                                st.success("Report is ready!")
                                break
                        else:
                            st.warning(f"Failed to fetch report status. Status code: {status_response.status_code}")
                            break
                        retries += 1
                        time.sleep(30)

                    if file_url:
                        try:
                            debug_log(f"Fetching file from: {file_url}")
                            file_response = requests.get(file_url, headers=authHeaders)
                            debug_log(f"Download File Status: {file_response.status_code}")
                            if file_response.status_code == 200:
                                file_json = file_response.json()
                                encoded_data = file_json['files']['file']
                                file_name = file_json['files']['fileName']
                                decoded_data = base64.b64decode(encoded_data)
                                st.download_button("Download File", decoded_data, file_name)
                            else:
                                st.error(f"Failed to download the file. Status code: {file_response.status_code}")
                        except Exception as e:
                            debug_log(f"Download Error: {e}")
                            st.error(f"Error downloading report: {e}")
                    elif retries >= max_retries:
                        st.warning("Timed out waiting for the report to finish.")
                    else:
                        st.error("Failed to retrieve file URL.")
            else:
                st.warning("Job ID was not returned.")
        else:
            st.error(f"Failed to start job. Status code: {start_response.status_code}")

authHeaders = get_auth_headers()

# Fetch current live metrics and always show dashboard at top
if 'authHeaders' in globals() and 'issuer' in globals():
    fetch_live_dashboard_data()

if authHeaders:
    if choice == "Reporting Jobs":
        reporting(authHeaders, f"https://{issuer}/incontactAPI/services/v31.0")
    elif choice == "Delete Deactivated Lists":
        uploaded_file = st.file_uploader("Upload CSV file of deactivated list IDs to delete", type=["csv"])
        if uploaded_file:
            if st.button("Delete Deactivated Lists"):
                delete_deactivated_lists_from_csv(uploaded_file)
    if choice == "Download MP4":
        pass
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
