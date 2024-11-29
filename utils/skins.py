import json
import os

import requests
from PIL import Image, PngImagePlugin


def clean_display_name(display_name):
    return "".join(c for c in display_name if c.isalnum())


def download_image(url, save_path):
    try:
        response = requests.get(url)
        response.raise_for_status()
        with open(save_path, "wb") as file:
            file.write(response.content)

        # print(f"Image successfully saved: {save_path}", end="\r")
    except requests.exceptions.RequestException as e:
        print(f"Error occured: {e}")


def gun_map():
    map = {
        "HMG": "Odin",
        "LMG": "Ares",
        "AK": "Vandal",
        "Burst": "Bulldog",
        "Carbine": "Phantom",
        "AutoShotgun": "Judge",
        "PumpShotgun": "Bucky",
        "AutoPistol": "Frenzy",
        "BasePistol": "Classic",
        "Luger": "Ghost",
        "Revolver": "Sheriff",
        "Slim": "Shorty",
        "Boltsniper": "Operator",
        "DMR": "Guardian",
        "Doublesniper": "Outlaw",
        "Leversniper": "Marshal",
        "MP5": "Spectre",
        "Vector": "Stinger",
    }
    return map


def download_skinchromas(file_path: str):
    # API URL
    url = "https://valorant-api.com/v1/weapons/skinchromas"

    # Parameters (optional if you want to specify a language)
    params = {"language": "en-US"}

    try:
        # Send GET request
        response = requests.get(url, params=params)
        response.raise_for_status()  # Check for HTTP errors

        # Parse JSON data
        data = response.json()

        # Save to a file
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)

        print("Data saved to skin_assets/skinchromas.json")

    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
    return


def embed_json_in_png(json_path, png_path, output_path):
    """Embed JSON content into the metadata of a PNG file."""
    with open(json_path, "r") as json_file:
        json_data = json.load(json_file)  # Load JSON content

    with Image.open(png_path) as img:
        meta = PngImagePlugin.PngInfo()
        meta.add_text("JSON_Metadata", json.dumps(json_data))  # Add JSON metadata
        img.save(output_path, "png", pnginfo=meta)  # Save new PNG


def folders_to_process_list():
    folders_to_process = [
        "HvyMachineGuns",
        "Melee",
        "Rifles",
        "Shotguns",
        "Sidearms",
        "SniperRifles",
        "SubMachineGuns",
    ]
    return folders_to_process


def extract_json_embed():
    with Image.open(r"allskins_full/output_809.png") as img:
        metadata = img.info
        if "JSON_Metadata" in metadata:
            print("Extracted JSON Metadata:")
            print(metadata["JSON_Metadata"])
