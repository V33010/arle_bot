import json
import os
import requests

# from downloadscript import download_image

os.system("cls")
# print("\033[H\033[J")

filepath = "skinchromas.json"

with open(filepath, "r") as file:
    data = json.load(file)

current_directory = os.getcwd()


def clean_display_name(display_name):
    return "".join(c for c in display_name if c.isalnum())


def download_image(url, save_path):
    try:
        # Send a GET request to the URL
        response = requests.get(url)
        response.raise_for_status()  # Raise an exception for HTTP errors

        # Write the content to a file
        with open(save_path, "wb") as file:
            file.write(response.content)
        print(f"Image successfully downloaded: {save_path}")
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")


gun_map = {
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

# ################################################################################
assets = data["data"]
for asset in assets:
    assetPath = asset["assetPath"].split("/")
    weapon_type = assetPath[3]
    gun_category = ""
    gun_type = ""
    display_name = asset["displayName"]
    cleaned_display_name = clean_display_name(display_name)
    internal_name = ""
    url = ""
    savepath = ""
    try:
        if asset["fullRender"] is not None:
            url = asset["fullRender"]
        else:
            url = asset["displayIcon"]
    except Exception as e:
        print(f"Error in url: {e}")
    if weapon_type == "Guns":
        gun_category = assetPath[4]
        gun_type = gun_map[assetPath[5]]
        internal_name = assetPath[6] + cleaned_display_name

    elif weapon_type == "Melee":
        gun_category = "Melee"
        gun_type = "Melee"
        internal_name = assetPath[4]

    else:
        print("NEW WEAPON TYPE FOUND")

    savepath = rf"{gun_category}\{gun_type}\{internal_name}"
    fullpath = os.path.join(current_directory, savepath)
    os.makedirs(fullpath, exist_ok=True)
    json_file_name = internal_name
    json_file_path = os.path.join(fullpath, f"{json_file_name}.json")
    image_file_name = internal_name
    image_file_path = os.path.join(fullpath, f"{image_file_name}.png")
    download_image(url, image_file_path)
    with open(json_file_path, "w") as file:
        json.dump(asset, file, indent=4)
