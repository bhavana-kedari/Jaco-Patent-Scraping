import os
import json
import time
import re
import pandas as pd
from io import StringIO
import requests
import gspread
from gspread_dataframe import set_with_dataframe
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException

# -----------------------------
# Google Sheets setup
# -----------------------------
gsheets_json = os.environ['GSHEETS_KEY_JSON']
gc = gspread.service_account_from_dict(json.loads(gsheets_json))

spreadsheet = gc.open("Patent Scrapes")  # Replace with your sheet name
input_sheet = spreadsheet.worksheet("User Input")
search_url = input_sheet.acell('B3').value
print(f"Search URL from B3: {search_url}")

# -----------------------------
# Download CSV in memory
# -----------------------------
# This assumes the Google Patents download CSV URL is known
# Replace the download button step with direct CSV URL if possible
csv_url = search_url.replace("/?", "/export/csv?")  # converts to CSV export URL
response = requests.get(csv_url)
if response.status_code != 200:
    raise Exception("Failed to download CSV from Google Patents")
csv_content = StringIO(response.text)

# Load CSV into pandas
df = pd.read_csv(csv_content, header=1)
if 'representative figure link' in df.columns:
    df = df.drop(columns='representative figure link')
df['abstract'] = ''
df['claim1'] = ''
df['abstract'] = df['abstract'].fillna('')
df['claim1'] = df['claim1'].fillna('')

# -----------------------------
# XPaths for scraping
# -----------------------------
abstract_xpath = '/html/body/search-app/search-result/search-ui/div/div/div/div/div/result-container/patent-result/div/div/div/div[1]/div[1]/section[1]/patent-text'
claim_xpath = '/html/body/search-app/search-result/search-ui/div/div/div/div/div/result-container/patent-result/div/div/div/div[2]/div[2]/section/patent-text/div'

# -----------------------------
# Prepare Google Sheet "Results"
# -----------------------------
try:
    results_sheet = spreadsheet.worksheet("Results")
except gspread.WorksheetNotFound:
    results_sheet = spreadsheet.add_worksheet(title="Results", rows="1000", cols="20")

# Write initial empty dataframe if sheet is empty
if results_sheet.row_count <= 1:
    set_with_dataframe(results_sheet, df)

# -----------------------------
# Selenium scraping setup
# -----------------------------
chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
driver = webdriver.Chrome(options=chrome_options)

# -----------------------------
# Scraping loop
# -----------------------------
pending_rows = df[(df['abstract'].str.strip() == '') | (df['claim1'].str.strip() == '')]

for i in pending_rows.index:
    url = df.at[i, 'result link']
    try:
        driver.get(url)
        time.sleep(2)

        # Abstract
        try:
            abstract = driver.find_element(By.XPATH, abstract_xpath).text
        except NoSuchElementException:
            abstract = ''

        # Claim 1
        try:
            claim1 = driver.find_element(By.XPATH, claim_xpath).text
        except NoSuchElementException:
            claim1 = ''

        # Update dataframe
        df.at[i, 'abstract'] = abstract
        df.at[i, 'claim1'] = claim1

        # Push to Google Sheet incrementally
        set_with_dataframe(results_sheet, df)

        print(f"Processed row {i+1}/{len(df)} | URL: {url}")

    except Exception as e:
        print(f"Error at row {i}: {e}")

driver.quit()
print("Scraping complete and Google Sheet updated.")
