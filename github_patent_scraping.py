import os
import json
import time
import glob
import shutil
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
search_url = input_sheet.acell('B3').value
print(f"Search URL from B3: {search_url}")

# -----------------------------
# Selenium setup
# -----------------------------
download_dir = os.path.abspath("downloads")
os.makedirs(download_dir, exist_ok=True)

chrome_options = Options()
chrome_options.add_argument("--headless=new")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
prefs = {
    "download.default_directory": download_dir,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "safebrowsing.enabled": True
}
chrome_options.add_experimental_option("prefs", prefs)

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

# -----------------------------
# Open search page and click CSV download
# -----------------------------
driver.get(search_url)
time.sleep(3)
print("Page title:", driver.title)
print("Current URL:", driver.current_url)

csv_file = None
try:
    download_button = driver.find_element(By.XPATH, '//*[@id="count"]/div[1]/span[2]')
    download_button.click()
    print("Clicked download button, waiting for CSV...")

    # wait for file to appear
    timeout = 30
    for _ in range(timeout):
        files = glob.glob(f"{download_dir}/*.csv")
        if files:
            csv_file = files[0]
            break
        time.sleep(1)

    if csv_file:
        print(f"CSV downloaded: {csv_file}")
    else:
        print("CSV file not found after waiting")
        raise Exception("CSV download failed")

except NoSuchElementException:
    print("Download button not found. Cannot download CSV automatically.")
    driver.quit()
    raise Exception("No download button on page")

driver.quit()

# -----------------------------
# Load CSV into pandas
# -----------------------------
df = pd.read_csv(csv_file, header=1)
if 'representative figure link' in df.columns:
    df = df.drop(columns='representative figure link')

df['abstract'] = df.get('abstract', '')
df['claim1'] = df.get('claim1', '')

# -----------------------------
# Prepare Google Sheet "Results"
# -----------------------------
try:
    results_sheet = spreadsheet.worksheet("Results")
except gspread.WorksheetNotFound:
    results_sheet = spreadsheet.add_worksheet(title="Results", rows="1000", cols="20")

if results_sheet.row_count <= 1:
    set_with_dataframe(results_sheet, df)

# -----------------------------
# Selenium scraping for abstract & claim1
# -----------------------------
chrome_options = Options()
chrome_options.add_argument("--headless=new")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

abstract_xpath = '/html/body/search-app/search-result/search-ui/div/div/div/div/div/result-container/patent-result/div/div/div/div[1]/div[1]/section[1]/patent-text'
claim_xpath = '/html/body/search-app/search-result/search-ui/div/div/div/div/div/result-container/patent-result/div/div/div/div[2]/div[2]/section/patent-text/div'

pending_rows = df[(df['abstract'].str.strip() == '') | (df['claim1'].str.strip() == '')]

for i in pending_rows.index:
    url = df.at[i, 'result link']
    try:
        driver.get(url)
        time.sleep(2)
        print(f"Processing row {i+1}/{len(df)} | URL: {url} | Page title: {driver.title}")

        try:
            abstract = driver.find_element(By.XPATH, abstract_xpath).text
        except NoSuchElementException:
            abstract = ''
            print(f"Abstract not found for row {i}")

        try:
            claim1 = driver.find_element(By.XPATH, claim_xpath).text
        except NoSuchElementException:
            claim1 = ''
            print(f"Claim 1 not found for row {i}")

        df.at[i, 'abstract'] = abstract
        df.at[i, 'claim1'] = claim1

        # Incrementally update Google Sheet
        set_with_dataframe(results_sheet, df)

    except Exception as e:
        print(f"Error at row {i}: {e}")

driver.quit()
print("Scraping complete and Google Sheet updated.")
