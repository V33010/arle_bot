from mutagen.id3 import ID3, USLT
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


def get_lyrics_from_genius(title, genius_access_token):
    """Fetches lyrics from Genius based on the song title using the lyricsgenius library."""
    genius = lyricsgenius.Genius(genius_access_token)
    song = genius.search_song(title)

    if song:
        return song.lyrics
    return "No lyrics found."


def title_cleanup(title):
    """Cleans up and formats the song title for querying Genius."""
    cleaned_title = title.strip()
    cleaned_title = re.sub(r"\.mp3$", "", cleaned_title)

    cleaned_title = cleaned_title.lower()

    cleaned_title = cleaned_title.replace("official", "")
    cleaned_title = cleaned_title.replace("video", "")
    cleaned_title = cleaned_title.replace("lyric", "")
    cleaned_title = cleaned_title.replace("music", "")
    cleaned_title = cleaned_title.replace("feat", "")

    if "(" in cleaned_title:
        cleaned_title = cleaned_title.split("(")[0]

    if "[" in cleaned_title:
        cleaned_title = cleaned_title.split("[")[0]

    cleaned_title = cleaned_title.replace("'", "")

    if "-" in cleaned_title:
        _0, _1 = cleaned_title.split("-")
        cleaned_title = _1 + " " + _0

    print(cleaned_title)

    if "+" in cleaned_title:
        cleaned_title = cleaned_title.split("+")[0]

    cleaned_title = re.sub(r"\s*\(.*?\)\s*", " ", cleaned_title)
    cleaned_title = re.sub(r"\s*\[.*?\]\s*", " ", cleaned_title)
    cleaned_title = re.sub(r"\s*[-|]\s*[^-|\s]*$", "", cleaned_title)
    cleaned_title = re.sub(r"[^\w\s]", " ", cleaned_title)
    cleaned_title = " ".join(cleaned_title.split())

    # if title is too long, shorten it

    cleaned_title = cleaned_title.split()
    if len(cleaned_title) > 5:
        cleaned_title = cleaned_title[:5]
        cleaned_title = " ".join(cleaned_title)

    print(cleaned_title)
    return cleaned_title


def update_lyrics(file_path, genius_access_token):
    """Updates the lyrics for the given MP3 file."""
    title = get_title(file_path)
    title = title_cleanup(title)

    if not title:
        print("Title not found in MP3 file.")
        return

    lyrics = get_lyrics_from_genius(title, genius_access_token)
    if lyrics == "No lyrics found.":
        lyrics = False
    if lyrics:
        # print(lyrics[:1000])
        print()
        print("Lyrics found. Updating MP3 file...")
        audio = ID3(file_path)

        # Remove existing lyrics tag if present
        if "USLT" in audio:
            del audio["USLT"]

        # Add new lyrics tag
        audio.add(USLT(encoding=3, language="eng", text=lyrics))
        audio.save()
        print("Lyrics updated successfully.")
    else:
        print("No lyrics found.")


# Example usage
file_path = r"C:\Vivek\coding\bot_f\downloads\badshebabu.mp3"
update_lyrics(file_path, genius_access_token)
