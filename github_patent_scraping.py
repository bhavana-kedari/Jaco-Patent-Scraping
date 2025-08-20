import os
import json
import time
import glob
import shutil
import tempfile
import pandas as pd
from io import StringIO
import gspread
from gspread_dataframe import set_with_dataframe
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# -----------------------------
# Google Sheets setup
# -----------------------------
gsheets_json = os.environ['GSHEET_KEY_JSON']
gc = gspread.service_account_from_dict(json.loads(gsheets_json))

spreadsheet = gc.open("Patent Scrapes")
input_sheet = spreadsheet.worksheet("User Input")
search_url = input_sheet.acell('B12').value
print(f"Search URL from B12: {search_url}")

# -----------------------------
# Check existing Results sheet
# -----------------------------
try:
    results_sheet = spreadsheet.worksheet("Results")
    df_results = pd.DataFrame(results_sheet.get_all_records())
except gspread.WorksheetNotFound:
    results_sheet = spreadsheet.add_worksheet(title="Results", rows="1000", cols="20")
    df_results = pd.DataFrame()

# -----------------------------
# Selenium options setup
# -----------------------------
chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")

# Download directory for CSV
download_dir = os.path.abspath("downloads")
os.makedirs(download_dir, exist_ok=True)
prefs = {
    "download.default_directory": download_dir,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "safebrowsing.enabled": True
}
chrome_options.add_experimental_option("prefs", prefs)

# -----------------------------
# CSV Download (only if Results sheet is empty)
# -----------------------------
if df_results.empty:
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    driver.get(search_url)
    time.sleep(3)
    print("Page title:", driver.title)

    try:
        download_button = driver.find_element(By.XPATH, '//*[@id="count"]/div[1]/span[2]')
        download_button.click()
        print("Clicked download button, waiting for CSV...")

        # Wait for CSV to appear in downloads folder
        timeout = 30
        csv_file = None
        for _ in range(timeout):
            files = glob.glob(f"{download_dir}/*.csv")
            if files:
                csv_file = files[0]
                break
            time.sleep(1)

        if csv_file:
            df = pd.read_csv(csv_file, header=1)
            # Ensure abstract and claim1 columns exist
            if 'abstract' not in df.columns:
                df['abstract'] = ''
            if 'claim1' not in df.columns:
                df['claim1'] = ''
            print(f"CSV loaded with {len(df)} rows")
        else:
            raise Exception("CSV download failed")

    except NoSuchElementException:
        raise Exception("No download button found")
    finally:
        driver.quit()
else:
    print("Resuming from existing Results sheet")
    df = df_results

# -----------------------------
# Selenium scraping for abstract & claim1
# -----------------------------
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

# Primary and fallback XPaths
abstract_xpaths = [
    '/html/body/search-app/search-result/search-ui/div/div/div/div/div/result-container/patent-result/div/div/div/div[1]/div[1]/section[1]/patent-text/div/section/abstract/div',
    '/html/body/search-app/search-result/search-ui/div/div/div/div/div/result-container/patent-result/div/div/div/div[1]/div[1]/section[1]/patent-text/div/section/abstract'
]

claim_xpaths = [
    '/html/body/search-app/search-result/search-ui/div/div/div/div/div/result-container/patent-result/div/div/div/div[2]/div[2]/section/patent-text/div/section/div/div[1]',
    '/html/body/search-app/search-result/search-ui/div/div/div/div/div/result-container/patent-result/div/div/div/div[2]/div[2]/section/patent-text/div'
]

# Only process rows with empty abstract or claim1
pending_rows = df[(df['abstract'].str.strip() == '') | (df['claim1'].str.strip() == '')]

for i in pending_rows.index:
    url = df.at[i, 'result link']
    if not url.strip():
        continue  # skip if no URL
    try:
        driver.get(url)
        time.sleep(2)
        print(f"Processing row {i+1}/{len(df)} | URL: {url}")

        # Abstract
        abstract = ''
        for xpath in abstract_xpaths:
            try:
                text = driver.find_element(By.XPATH, xpath).text
                if text.strip():
                    abstract = text
                    break
            except NoSuchElementException:
                continue

        # Claim1
        claim1 = ''
        for xpath in claim_xpaths:
            try:
                text = driver.find_element(By.XPATH, xpath).text
                if text.strip():
                    claim1 = text
                    break
            except NoSuchElementException:
                continue

        df.at[i, 'abstract'] = abstract
        df.at[i, 'claim1'] = claim1

        # Push to Google Sheet incrementally
        set_with_dataframe(results_sheet, df)

    except Exception as e:
        print(f"Error at row {i}: {e}")

driver.quit()
print("Scraping complete and Google Sheet updated.")

