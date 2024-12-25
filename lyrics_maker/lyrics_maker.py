# from mutagen.id3 import ID3, TIT2, USLT
# import requests
# from bs4 import BeautifulSoup
# import os
# from dotenv import load_dotenv

# load_dotenv()

# genius_access_token_og = os.getenv("genius_token")


# ############################################################################################################

# import requests
# from bs4 import BeautifulSoup
# import os
# from dotenv import load_dotenv
# from mutagen.id3 import ID3

# load_dotenv()

# genius_access_token_og = os.getenv("genius_token")

# def get_title(file_path):
#     """Extracts the title from the MP3 file's ID3 tags."""
#     audio = ID3(file_path)
#     title_tag = audio.get('TIT2')
#     if title_tag:
#         return title_tag.text[0]
#     return None

# def get_lyrics_from_genius(title, genius_access_token):
#     """Fetches lyrics from Genius based on the song title."""
#     headers = {'Authorization': f'Bearer {genius_access_token}'}
#     search_url = 'https://api.genius.com/search'
#     params = {'q': title}
#     response = requests.get(search_url, headers=headers, params=params)
#     search_results = response.json()

#     hits = search_results['response']['hits']
#     if hits:
#         print(f"Search results for '{title}':")
#         song_info = hits[0]['result']
#         lyrics_path = song_info['path']
#         lyrics_url = f'https://genius.com{lyrics_path}'
#         print(lyrics_url)
#         lyrics_page = requests.get(lyrics_url)

#         # Parse the lyrics from the lyrics_page
#         soup = BeautifulSoup(lyrics_page.text, 'html.parser')
#         lyrics_div = soup.find('div', {'data-lyrics-container': 'true'})

#         if lyrics_div:
#             # return lyrics_div
#             # Extract text and replace <br> with new lines
#             # Ensure no extra whitespace is trimmed
#             lyrics_html = str(lyrics_div)
#             soup_lyrics = BeautifulSoup(lyrics_html, 'html.parser')
#             lyrics = soup_lyrics.get_text(separator='\n').strip()
#             return lyrics
#         else:
#             return "Lyrics container not found."
#     return "No lyrics found."

# def update_lyrics(file_path, genius_access_token):
#     """Updates the lyrics for the given MP3 file."""
#     title = get_title(file_path)
#     if not title:
#         print("Title not found in MP3 file.")
#         return

#     lyrics = get_lyrics_from_genius(title, genius_access_token)
#     if lyrics:
#         print(lyrics)
#     else:
#         print("No lyrics found.")

# # Example usage
# genius_access_token = genius_access_token_og
# file_path = r"C:\Vivek\coding\bot_f\downloads\2ndlibrown.mp3"  # Use raw string or forward slashes
# update_lyrics(file_path, genius_access_token)


import os
import re

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from mutagen.id3 import ID3, USLT

load_dotenv()

genius_access_token_og = os.getenv('genius_token')


def get_title(file_path):
    """Extracts the title from the MP3 file's ID3 tags."""
    audio = ID3(file_path)
    title_tag = audio.get('TIT2')
    if title_tag:
        return title_tag.text[0]
    return None


def get_lyrics_from_genius(title, genius_access_token):
    """Fetches lyrics from Genius based on the song title."""
    headers = {'Authorization': f'Bearer {genius_access_token}'}
    search_url = 'https://api.genius.com/search'
    params = {'q': title}
    response = requests.get(search_url, headers=headers, params=params)
    search_results = response.json()

    hits = search_results['response']['hits']
    if hits:
        print(f"Search results for '{title}':")
        song_info = hits[0]['result']
        lyrics_path = song_info['path']
        lyrics_url = f'https://genius.com{lyrics_path}'
        print(lyrics_url)
        lyrics_page = requests.get(lyrics_url)

        # Parse the lyrics from the lyrics_page
        soup = BeautifulSoup(lyrics_page.text, 'html.parser')
        lyrics_div = soup.find('div', {'data-lyrics-container': 'true'})

        if lyrics_div:
            print(lyrics_div)
            print()

            # Extract text and replace <br> with new lines
            lyrics_html = str(lyrics_div)
            soup_lyrics = BeautifulSoup(lyrics_html, 'html.parser')
            lyrics = soup_lyrics.get_text(separator='\n').strip()
            return lyrics
        else:
            return 'Lyrics container not found.'
    return 'No lyrics found.'


def title_cleanup(title):
    print(title)
    """Cleans up and formats the song title for querying Genius."""
    # Trim leading and trailing whitespace
    cleaned_title = title.strip()

    # Remove file extension
    cleaned_title = re.sub(r'\.mp3$', '', cleaned_title)

    if '(' in cleaned_title:
        cleaned_title = cleaned_title.split('(')[0]

    if '[' in cleaned_title:
        cleaned_title = cleaned_title.split('[')[0]

    # replace "'" with ""
    cleaned_title = cleaned_title.replace("'", '')

    if '-' in cleaned_title:
        _0, _1 = cleaned_title.split('-')

        cleaned_title = _1 + ' ' + _0

    # Remove text in parentheses and brackets (e.g., (Lyrics), [feat. ...])
    cleaned_title = re.sub(r'\s*\(.*?\)\s*', ' ', cleaned_title)
    cleaned_title = re.sub(r'\s*\[.*?\]\s*', ' ', cleaned_title)

    # Remove artist names, features, and metadata by identifying common patterns
    # Remove any segment with '-' or '｜' which often separates metadata
    cleaned_title = re.sub(r'\s*[-|]\s*[^-|\s]*$', '', cleaned_title)

    # Remove special characters while keeping common punctuation
    cleaned_title = re.sub(r'[^\w\s]', ' ', cleaned_title)

    # Replace multiple spaces with a single space
    cleaned_title = ' '.join(cleaned_title.split())

    # Optional: Convert to lowercase for consistency
    # cleaned_title = cleaned_title.lower()

    # Print cleaned title for debugging
    print(cleaned_title)

    return cleaned_title


def update_lyrics(file_path, genius_access_token):
    """Updates the lyrics for the given MP3 file."""
    title = get_title(file_path)
    title = title_cleanup(title)

    if not title:
        print('Title not found in MP3 file.')
        return

    lyrics = get_lyrics_from_genius(title, genius_access_token)
    print(lyrics)
    if lyrics == 'No lyrics found.':
        lyrics = False
    if lyrics:
        print('Lyrics found. Updating MP3 file...')
        audio = ID3(file_path)

        # Remove existing lyrics tag if present
        if 'USLT' in audio:
            del audio['USLT']

        # Add new lyrics tag
        audio.add(USLT(encoding=3, language='eng', text=lyrics))
        audio.save()
        print('Lyrics updated successfully.')
    else:
        print('No lyrics found.')


# Example usage
genius_access_token = genius_access_token_og
file_path = r'C:\Vivek\coding\bot_f\downloads\alanwergan.mp3'
update_lyrics(file_path, genius_access_token)
