from mutagen.id3 import ID3
from mutagen.id3._frames import USLT
import lyricsgenius
import os
from dotenv import load_dotenv
import re

load_dotenv()

# Get the Genius API token from environment variables
genius_access_token = os.getenv("genius_token")


def get_title(file_path):
    """Extracts the title from the MP3 file's ID3 tags."""
    audio = ID3(file_path)
    title_tag = audio.get("TIT2")
    if title_tag:
        return title_tag.text[0]
    return None


def title_cleanup(title):
    """Cleans up and formats the song title for querying Genius."""  # sample #############################################################@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
    cleaned_title = title.strip()
    cleaned_title = re.sub(r"\.mp3$", "", cleaned_title)

    cleaned_title = cleaned_title.lower()

    cleaned_title = cleaned_title.replace("official", "")
    cleaned_title = cleaned_title.replace("video", "")
    cleaned_title = cleaned_title.replace("lyric", "")
    cleaned_title = cleaned_title.replace("music", "")
    cleaned_title = cleaned_title.replace("feat", "")
    cleaned_title = cleaned_title.replace(" ft ", "")
    cleaned_title = cleaned_title.replace(" ft. ", "")
    cleaned_title = cleaned_title.strip()
    cleaned_title = cleaned_title.strip("-")

    if "(" in cleaned_title:
        cleaned_title = cleaned_title.split("(")[0]

    if "[" in cleaned_title:
        cleaned_title = cleaned_title.split("[")[0]

    cleaned_title = cleaned_title.replace("'", "")

    if " - " in cleaned_title:
        _0, _1 = cleaned_title.split(" - ")
        cleaned_title = _1 + " " + _0

    # print(cleaned_title)

    if "+" in cleaned_title:
        cleaned_title = cleaned_title.split("+")[0]

    cleaned_title = re.sub(r"\s*\(.*?\)\s*", " ", cleaned_title)
    cleaned_title = re.sub(r"\s*\[.*?\]\s*", " ", cleaned_title)
    cleaned_title = re.sub(r"\s*[-|]\s*[^-|\s]*$", "", cleaned_title)
    cleaned_title = re.sub(r"[^\w\s]", " ", cleaned_title)
    cleaned_title = " ".join(cleaned_title.split())

    print(f"cleaned_title: {cleaned_title}")

    # if title is too long, shorten it
    cleaned_title = cleaned_title.split()
    if len(cleaned_title) > 5:
        cleaned_title = cleaned_title[:5]
        print(cleaned_title)
        # cleaned_title = ' '.join(cleaned_title)
        # print(cleaned_title)

    print("first print")
    print(cleaned_title)
    print(type(cleaned_title))
    print(len(cleaned_title))
    if len(cleaned_title) == 0:
        return None

    # convert list to string
    cleaned_title = " ".join(cleaned_title)

    print(cleaned_title)
    return cleaned_title


def get_lyrics_from_genius(title, genius_access_token):
    """Fetches lyrics from Genius based on the song title using the lyricsgenius library."""
    genius = lyricsgenius.Genius(genius_access_token)
    print(title)
    cleaned_title = title_cleanup(title)
    if cleaned_title is None:
        return "No lyrics found."
    print(f"Searching for lyrics on genuis for '{cleaned_title}'...")
    song = genius.search_song(cleaned_title)

    if song:
        return song.lyrics
    return "No lyrics found."


def update_lyrics(file_path, genius_access_token):
    """Updates the lyrics for the given MP3 file."""
    title = get_title(file_path)
    if not title:
        print(f"Title not found in MP3 file: {file_path}")
        return

    lyrics = get_lyrics_from_genius(title, genius_access_token)
    if lyrics and lyrics != "No lyrics found.":
        print(f"Lyrics found for {title}. Updating MP3 file...")
        audio = ID3(file_path)

        # Remove existing lyrics tag if present
        if "USLT" in audio:
            del audio["USLT"]

        # Add new lyrics tag
        audio.add(USLT(encoding=3, language="eng", text=lyrics))
        audio.save()
        print(f"Lyrics updated successfully for {title}.")
    else:
        print(f"No lyrics found for {title}.")


def update_lyrics_for_folder(folder_path, genius_access_token):
    """Updates lyrics for all MP3 files in the given folder."""
    list_of_files_with_valueError = []
    # find total number of files in the folder
    total_files = 0
    for file_name in os.listdir(folder_path):
        if file_name.lower().endswith(".mp3"):
            total_files += 1

    current_file = 0

    for file_name in os.listdir(folder_path):
        # pretty print
        print("\n\n")

        if file_name.lower().endswith(".mp3"):
            current_file += 1
            print(f"Processing file {current_file}/{total_files}...")

            file_path = os.path.join(folder_path, file_name)
            print(f"Processing file: {file_path}")
            try:
                update_lyrics(file_path, genius_access_token)
            except ValueError:
                print(f"ValueError: {file_path}")
                list_of_files_with_valueError.append(file_path)
                continue

    print(len(list_of_files_with_valueError))
    print(list_of_files_with_valueError)


# Example usage
folder_path = r"C:\Vivek\coding\arleBot\testsongs"  # Use raw string or forward slashes
update_lyrics_for_folder(folder_path, genius_access_token)
