import os

import requests
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

load_dotenv()


def get_title(file_path):
    """Extracts the title from the MP3 file's ID3 tags."""
    from mutagen.id3 import ID3

    audio = ID3(file_path)
    title_tag = audio.get('TIT2')
    if title_tag:
        return title_tag.text[0]
    return None


def get_lyrics_page_url(title, genius_access_token):
    """Fetches the lyrics page URL from Genius based on the song title."""
    headers = {'Authorization': f'Bearer {genius_access_token}'}
    search_url = 'https://api.genius.com/search'
    params = {'q': title}
    response = requests.get(search_url, headers=headers, params=params)
    search_results = response.json()

    hits = search_results['response']['hits']
    if hits:
        song_info = hits[0]['result']
        lyrics_path = song_info['path']
        return f'https://genius.com{lyrics_path}'
    return None


def fetch_lyrics_page(url):
    """Fetches the HTML content of the lyrics page using Selenium."""
    options = Options()
    options.headless = True
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        driver.get(url)

        # Wait for the page to load
        driver.implicitly_wait(10)

        # Save the HTML content of the page
        with open('page.txt', 'w', encoding='utf-8') as file:
            file.write(driver.page_source)

        print('HTML content of the lyrics page has been saved to page.txt.')

    except Exception as e:
        print(f'An error occurred: {e}')

    finally:
        driver.quit()


# # Example usage
# genius_access_token = os.getenv("genius_token")
# print(genius_access_token)
# file_path = r"C:\Vivek\coding\bot_f\downloads\2ndlibrown.mp3"  # Update with the actual path to your MP3 file
# title = get_title(file_path)
# if title:
#     lyrics_url = get_lyrics_page_url(title, genius_access_token)
#     if lyrics_url:
#         fetch_lyrics_page(lyrics_url)
#     else:
#         print("Lyrics page URL not found.")
# else:
#     print("Title not found in MP3 file.")


####

# from selenium import webdriver
# from selenium.webdriver.chrome.service import Service
# from selenium.webdriver.common.by import By
# from selenium.webdriver.chrome.options import Options
# from selenium.webdriver.support.ui import WebDriverWait
# from selenium.webdriver.support import expected_conditions as EC
# import time


# def fetch_lyrics_page(title, genius_access_token):
#     """Fetches the lyrics page and stores the HTML content in a text file."""
#     search_url = get_lyrics_page_url(
#         title, genius_access_token
#     )  # Get the lyrics URL using the earlier method
#     if not search_url:
#         print("Lyrics URL not found.")
#         return
#
#     # Set up Chrome options for private browsing
#     chrome_options = Options()
#     chrome_options.add_argument("--incognito")
#
#     # Set up the Chrome WebDriver
#     service = Service("path/to/chromedriver")
#     driver = webdriver.Chrome(service=service, options=chrome_options)
#
#     try:
#         driver.get(search_url)
#
#         # Wait until the lyrics container is present
#         WebDriverWait(driver, 10).until(
#             EC.presence_of_element_located(
#                 (By.CSS_SELECTOR, 'div[data-lyrics-container="true"]')
#             )
#         )
#
#         # Get the page source
#         page_source = driver.page_source
#
#         # Write the page source to a file
#         with open("page.txt", "w", encoding="utf-8") as file:
#             file.write(page_source)
#
#         print("Page saved to 'page.txt'.")
#
#     finally:
#         driver.quit()


# Example usage
genius_access_token = os.getenv('genius_token')
title = '2nd life ashes'
fetch_lyrics_page(title, genius_access_token)
