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
import schedule
import time
from datetime import datetime



# st.set_page_config(page_title="My Webpage", page_icon=":calendar:", layout="wide")

st.title("API Tenant Management")

issuer_options = {"Non-FedRamp": "cxone.niceincontact.com", "FedRamp": "cxone-gov.niceincontact.com"}
issuer_type = st.sidebar.selectbox("Select Account Type:", ["Non-FedRamp", "FedRamp"], key="issuer_type")
issuer = issuer_options[issuer_type]

# Debugging toggle
debug_mode = st.sidebar.checkbox("Enable Debugging", key="debug_mode")

# Initialize variables to prevent NameErrors
authHeaders = None
endpoint = None

def show_login_message():
    """Display a message prompting the user to enter credentials."""
    st.info("Please enter your credentials in the sidebar to proceed.")

# Sidebar for authentication
with st.sidebar:
    st.write("Credentials")
    accessId = st.text_input("Enter your Access ID:", key="access_id_sidebar_main")
    accessKeySecret = st.text_input("Enter your Access Key Secret:", type="password", key="access_key_secret_sidebar_main")
    client_id = st.text_input("Enter your Client ID:", key="client_id_sidebar_main")
    client_secret = st.text_input("Enter your Client Secret:", type="password", key="client_secret_sidebar_main")
    
    choice = st.selectbox("Choose an API call:", [
        "Download MP4", 
        "Fetch Call Lists", 
        "Delete Deactivated Lists", 
        "Fetch Completed Contacts", 
        "Reporting Jobs", 
        "Scheduling"
    ])

if not all([accessId, accessKeySecret, client_id, client_secret]):
    show_login_message()
else:
    try:
        en_client_secret = urllib.parse.quote(client_secret)
        concatenate = f'{client_id}:{en_client_secret}'
        encoded_concatenate = base64.b64encode(concatenate.encode()).decode()
        token_endpoint = f'https://{issuer}/auth/token'
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {encoded_concatenate}",
        }
        data = {
            "grant_type": "password",
            "username": accessId,
            "password": accessKeySecret,
        }

        response = requests.post(token_endpoint, headers=headers, data=data)

        if response.status_code == 200:
            json_data = response.json()
            access_token = json_data.get("access_token")
            decoded_access_token = jwt.decode(access_token, options={"verify_signature": False})
            tenant_id = decoded_access_token.get("tenantId")

            cx_discovery = f'https://{issuer}/.well-known/cxone-configuration?tenantId={tenant_id}'
            cxDiscoveryResponse = requests.get(cx_discovery)
            cxDiscoveryResp = json.loads(cxDiscoveryResponse.text)
            api_endpoint = cxDiscoveryResp["api_endpoint"]
            endpoint = f"{api_endpoint}/incontactAPI/services/v31.0"
            authHeaders = {"Authorization": f"bearer {access_token}"}

            st.success(f"Connected to {api_endpoint}")
        else:
            st.error(f"Error: {response.status_code}")

    except Exception as e:
        st.error(f"An error occurred: {e}")

# Function to fetch completed contacts with debugging
def fetch_completed_contacts(start_date, start_time, end_date, end_time, fetch_all, top):
    all_records = []
    skip = 0
    
    while True:
        completed_contacts_url = f"{endpoint}/contacts/completed?startDate={start_date}%20{start_time}&endDate={end_date}%20{end_time}&top={top}&skip={skip}"
        if debug_mode:
            st.write(f"DEBUG: Fetching completed contacts from URL: {completed_contacts_url}")
        response = requests.get(completed_contacts_url, headers=authHeaders)
        if debug_mode:
            st.write(f"DEBUG: Response Status Code: {response.status_code}")
        
        if response.status_code == 200:
            json_response = response.json()
            if debug_mode:
                st.write(f"DEBUG: Response Content: {json.dumps(json_response, indent=2)}")
            completed_contacts = json_response.get("completedContacts", [])
            
            if not completed_contacts:
                break  # No more data to fetch
            
            all_records.extend(completed_contacts)
            if not fetch_all:
                break  # Stop fetching if not set to fetch all data
            
            skip += top  # Move to the next batch
            time.sleep(1)  # Prevent API rate limits
        else:
            st.error(f"Failed to fetch completed contacts. Status code: {response.status_code}")
            return []
    
    if all_records:
        df = pd.DataFrame(all_records)
        for column in df.select_dtypes(include=['float64']).columns:
            df[column] = df[column].astype(str)
        df.fillna("", inplace=True)  # Replace NaN with empty strings
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        st.download_button("Download Completed Contacts CSV", data=csv_buffer.getvalue(), file_name="completed_contacts.csv", mime="text/csv")
    else:
        st.warning("No valid records found in API response.")


def download_mp4_from_callid(callid):
    # Define API endpoint
    url = f"https://na1.nice-incontact.com/media-playback/v1/contacts?acd-call-id={callid}&media-type=all&exclude-waveforms=true&isDownload=false"
    payload = {}
    response = requests.get(url, headers=authHeaders, data=payload)

    if response.status_code == 200:
        interactions = response.json().get('interactions', [])
        if interactions:
            fileToPlayUrl = interactions[0].get('data', {}).get('fileToPlayUrl', '')
            mp4_response = requests.get(fileToPlayUrl)
            mp4_content = mp4_response.content
            filename = f"{callid}.mp4"
            return mp4_content, filename
        else:
            st.error(f"Failed to get data for callid: {callid}")
            return None, None
    else:
        st.error(f"Failed to get data for callid: {callid}")
        return None, None


def download_mp4_from_file(uploaded_file, file_type="csv"):
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'a', zipfile.ZIP_DEFLATED) as zip_file:
        if file_type == "csv":
            df = pd.read_csv(uploaded_file, header=None, names=['callid'])
        else:
            df = pd.read_excel(uploaded_file, header=None, names=['callid'])
        limited_df = df.head(MAX_CALLIDS)
        for callid in limited_df['callid']:
            mp4_content, filename = download_mp4_from_callid(callid)
            if not mp4_content or not filename:
                st.warning(f"Couldn't fetch MP4 for Call ID: {callid}")
            else:
                zip_file.writestr(filename, mp4_content)
    zip_buffer.seek(0)
    return zip_buffer


MAX_CALLIDS = 50


def fetch_call_list():
    call_list_endpoint = f"{endpoint}/lists/call-lists"
    response = requests.get(call_list_endpoint, headers=authHeaders)
    if response.status_code == 200:
        return response.json()
    else:
        st.error(f"Failed to retrieve call list data. Status code: {response.status_code}")
        return None


def download_deactivated_call_lists():
    data = fetch_call_list()
    if data:
        # Filtered list with only 'listId' for deactivated call lists
        deactivated_lists = [{"listId": item["listId"]} for item in data.get("callingLists", []) if item.get("status") == "Deactivated"]
        if deactivated_lists:
            df = pd.DataFrame(deactivated_lists)
            date_str = datetime.now().strftime("%Y-%m-%d")
            csv_filename = f"deactivated_call_lists_{date_str}.csv"
            csv_buffer = io.StringIO()
            df.to_csv(csv_buffer, index=False)
            csv_data = csv_buffer.getvalue()
            st.download_button("Download Deactivated Call Lists CSV", data=csv_data, file_name=csv_filename, mime="text/csv")
        else:
            st.warning("No deactivated call lists found.")

        # Full list with all columns from the API response
        full_list = data.get("callingLists", [])
        if full_list:
            full_df = pd.DataFrame(full_list)
            full_csv_filename = f"full_call_lists_{date_str}.csv"
            full_csv_buffer = io.StringIO()
            full_df.to_csv(full_csv_buffer, index=False)
            full_csv_data = full_csv_buffer.getvalue()
            st.download_button("Download Full Call Lists CSV", data=full_csv_data, file_name=full_csv_filename, mime="text/csv")
    else:
        st.error("No data available to create the CSV files.")


def delete_deactivated_lists_from_csv(uploaded_file):
    if uploaded_file is not None:
        df = pd.read_csv(uploaded_file)
        list_ids = df["listId"].tolist()

        # Load any previously processed IDs if resuming
        processed_ids = set()
        try:
            with open("processed_ids_log.txt", "r") as f:
                processed_ids = set(int(line.strip()) for line in f)
        except FileNotFoundError:
            pass  # No previous log exists, proceed with an empty set

        total_ids = len(list_ids)
        deleted_count = 0
        failed_count = 0

        # Streamlit progress bar
        progress_bar = st.progress(0)
        status_text = st.empty()

        for idx, list_id in enumerate(list_ids):
            # Skip IDs that have already been processed
            if list_id in processed_ids:
                continue

            # Include forceInactive and forceDelete query parameters
            delete_url = f"{endpoint}/lists/call-lists/{list_id}?forceInactive=true&forceDelete=true"
            response = requests.delete(delete_url, headers=authHeaders)
            
            # Update the progress bar and display status
            progress = (idx + 1) / total_ids
            progress_bar.progress(progress)
            status_text.text(f"Processing {idx + 1}/{total_ids}: List ID {list_id}")

            # Handle various response codes
            if response.status_code == 200:
                deleted_count += 1
                st.info(f"Successfully deleted list ID: {list_id}")
            elif response.status_code == 400:
                st.warning(f"Invalid parameter for list ID: {list_id}")
                failed_count += 1
            elif response.status_code == 401:
                st.error("Invalid or expired token. Please refresh your token.")
                break
            elif response.status_code == 403:
                st.error(f"Forbidden. Check Security Profile permissions for list ID: {list_id}")
                failed_count += 1
            elif response.status_code == 404:
                st.warning(f"Invalid list ID: {list_id}")
                failed_count += 1
            elif response.status_code == 409:
                st.warning(f"List cannot be modified for list ID: {list_id}")
                failed_count += 1
            else:
                st.warning(f"Failed to delete list with ID: {list_id}. Status code: {response.status_code}")
                failed_count += 1

            # Log the successfully processed list ID
            with open("processed_ids_log.txt", "a") as f:
                f.write(f"{list_id}\n")

        # Final summary of the deletion process
        st.success(f"Completed processing. Deleted {deleted_count} lists.")
        if failed_count > 0:
            st.error(f"Failed to delete {failed_count} lists.")

        # Remove the log file if all IDs are processed
        if deleted_count + failed_count == total_ids:
            os.remove("processed_ids_log.txt")


# Function to handle report jobs
def reporting(authHeaders, endpoint):
    st.title("Reporting API Services")

    def report_id():
        """Fetch and display report details by Job ID with debugging."""
        job_id = st.text_input("Enter Job ID:", key="report_job_id")
        if st.button("Check Status"):
            if job_id:
                url = f"{endpoint}/report-jobs/{job_id}"
                st.write(f"DEBUG: Checking report ID status at URL: {url}")
                response = requests.get(url, headers=authHeaders)
                st.write(f"DEBUG: Response Status Code: {response.status_code}")
                if response.status_code == 200:
                    data = response.json().get("jobResult", {})
                    st.markdown(f"**Report Job ID:** {data.get('jobId', 'N/A')}")
                    st.markdown(f"**Report Name:** {data.get('reportName', 'N/A')}")
                    st.markdown(f"**File Name:** {data.get('fileName', 'N/A')}")
                    st.markdown(f"**File URL:** {data.get('resultFileURL', 'N/A')}")
                    st.markdown(f"**State:** {data.get('state', 'N/A')}")
                else:
                    st.error(f"Failed to fetch report details. Status code: {response.status_code}")
                    st.write(f"DEBUG: Response Content: {response.text}")
            else:
                st.error("Please enter a valid Job ID.")

    def start_job():
        """Start a new report job and display the Job ID with debugging."""
        report_id = st.text_input("Enter Report ID:", key="start_report_id")
        additional_param = st.text_input("Enter Additional Parameter (Optional):", value="value", key="start_report_param")
        payload = {"additionalParam": additional_param}

        if st.button("Start Job"):
            if not report_id:
                st.error("Report ID is required to start a job.")
                return

            url = f"{endpoint}/report-jobs/{report_id}?fileType=CSV&includeHeaders=true&appendDate=true&overwrite=true"
            st.write(f"DEBUG: Starting job with URL: {url}")
            response = requests.post(url, headers=authHeaders, json=payload)
            st.write(f"DEBUG: Response Status Code: {response.status_code}")

            if response.status_code == 202:
                try:
                    response_data = response.json()
                    job_id = response_data.get("jobId", None)
                    if job_id:
                        st.success(f"Job started successfully with Job ID: {job_id}")
                    else:
                        st.warning("Job started successfully, but no Job ID was returned.")
                except ValueError:
                    st.error("Failed to parse response JSON.")
                    st.write(f"DEBUG: Response Content: {response.text}")
            else:
                st.error(f"Failed to start job. Status code: {response.status_code}")
                st.write(f"DEBUG: Response Content: {response.text}")

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
            response = requests.get(report_url, headers=authHeaders)
            if response.status_code == 200:
                json_data = response.json()
                encoded_data = json_data['files']['file']
                file_name = json_data['files']['fileName']
                decoded_data = base64.b64decode(encoded_data)
                st.download_button("Download File", decoded_data, file_name)
            else:
                st.error(f"Failed to download the file. Status code: {response.status_code}")
        except Exception as e:
            st.error(f"Error downloading report: {e}")


def report_scheduler(authHeaders, endpoint):
    st.title("Report Scheduler")

    report_filename_early = "completed_contacts_12AM-2AM.csv"
    report_filename_morning = "completed_contacts_12AM-8AM.csv"

    def fetch_completed_contacts(start_time, end_time, filename):
        """Fetch and save the completed contacts report automatically."""
        try:
            today_date = datetime.now().strftime("%m/%d/%Y")
            top = 10000  # Max number of records to fetch

            url = f"{endpoint}/contacts/completed?startDate={today_date}%20{start_time}&endDate={today_date}%20{end_time}&top={top}"
            st.write(f"DEBUG: Fetching completed contacts report from URL: {url}")
            response = requests.get(url, headers=authHeaders)
            st.write(f"DEBUG: Response Status Code: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                df = pd.DataFrame(data.get("completedContacts", []))
                if not df.empty:
                    df.to_csv(filename, index=False)
                    st.success(f"Completed Contacts Report ({start_time}-{end_time}) saved successfully.")
                else:
                    st.warning(f"No data found in the report ({start_time}-{end_time}).")
            else:
                st.error(f"Failed to fetch report. Status code: {response.status_code}")
                st.write(f"DEBUG: Response Content: {response.text}")
        except Exception as e:
            st.error(f"Error fetching completed contacts: {e}")

    def schedule_reports():
        """Schedule the reports to run at 2:15 AM and 8:15 AM."""
        schedule.every().day.at("02:15").do(fetch_completed_contacts, "00:00", "02:00", report_filename_early)
        schedule.every().day.at("08:15").do(fetch_completed_contacts, "00:00", "08:00", report_filename_morning)

        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute

    def report_get():
        """Provide download buttons for the latest scheduled completed contacts report."""
        if os.path.exists(report_filename_early):
            with open(report_filename_early, "rb") as file:
                st.download_button("Download 12AM - 2AM Report", file, report_filename_early, "text/csv")

        if os.path.exists(report_filename_morning):
            with open(report_filename_morning, "rb") as file:
                st.download_button("Download 12AM - 8AM Report", file, report_filename_morning, "text/csv")
    
    st.sidebar.success("Successfully connected!")
    st.subheader("Automated Completed Contacts Report")

    # Manual Execution
    if st.button("Run 12AM - 2AM Report Now"):
        fetch_completed_contacts("00:00", "02:00", report_filename_early)

    if st.button("Run 12AM - 8AM Report Now"):
        fetch_completed_contacts("00:00", "08:00", report_filename_morning)

    st.subheader("Download Reports")
    report_get()

    # Start the background scheduler (only needed once)
    import threading
    threading.Thread(target=schedule_reports, daemon=True).start()

    
# Ensure API calls only run if authentication is successful
if authHeaders and endpoint:
    if choice == "Download MP4":
        callid = st.text_input("Enter the Call ID:")
        if st.button('Submit'):
            mp4_content, filename = download_mp4_from_callid(callid)
            if mp4_content and filename:
                st.download_button(label=f"Download {filename}", data=mp4_content, file_name=filename, mime="video/mp4")

    elif choice == "Fetch Call Lists":
        if st.button('Fetch Call Lists'):
            download_deactivated_call_lists()

    elif choice == "Delete Deactivated Lists":
        uploaded_file = st.file_uploader("Upload CSV file of deactivated list IDs to delete", type=["csv"])
        if uploaded_file:
            if st.button("Delete Deactivated Lists"):
                delete_deactivated_lists_from_csv(uploaded_file)

    elif choice == "Fetch Completed Contacts":
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            start_date = st.date_input("Start Date")
        with col2:
            start_time = st.time_input("Start Time")
        with col3:
            end_date = st.date_input("End Date")
        with col4:
            end_time = st.time_input("End Time")

        fetch_all = st.checkbox("Fetch All Records")
        top = st.number_input("Max Records Per Request (1000-10000):", min_value=1000, max_value=10000, value=10000)

        if st.button("Fetch Completed Contacts"):
            fetch_completed_contacts(start_date.strftime("%m/%d/%Y"), start_time.strftime("%H:%M"), end_date.strftime("%m/%d/%Y"), end_time.strftime("%H:%M"), fetch_all, top)

    elif choice == "Reporting Jobs":
        reporting(authHeaders, endpoint)  # Call function directly

    elif choice == "Scheduling":
        report_scheduler(authHeaders, endpoint)  # Call function directly

else:
    st.warning("Please enter credentials in the sidebar before proceeding.")


