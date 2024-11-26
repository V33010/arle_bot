import json

import requests


def clean_display_name(display_name):
    return "".join(c for c in display_name if c.isalnum())


def download_image(url, save_path):
    try:
        response = requests.get(url)
        response.raise_for_status()
        with open(save_path, "wb") as file:
            file.write(response.content)

        print(f"Image successfully saved: {save_path}")
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


def download_skinchromas():
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
        with open("skinchromas.json", "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)

        print("Data saved to skinchromas.json")

    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
    return
