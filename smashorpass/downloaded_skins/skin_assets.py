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
# asset = data["data"][2000]
# assetPath = asset["assetPath"].split("/")
# weapon_type = assetPath[3]
# gun_category = ""
# gun_type = ""
# display_name = asset["displayName"]
# internal_name = ""
# url = ""
# try:
#     url = asset["fullRender"]
# except KeyError:
#     url = asset["displayIcon"]
# print(display_name)
# print(url)
# if weapon_type == "Guns":
#     gun_category = assetPath[4]
#     gun_type = gun_map[assetPath[5]]
#     internal_name = assetPath[6]
#     print(f"gun_type: {gun_type}")
#     print(f"gun_category: {gun_category}")
#     print(f"internal_name: {internal_name}")
#     pass
# elif weapon_type == "Melee":
#     gun_category = "Melee"
#     gun_type = assetPath[4]
#     internal_name = assetPath[4]
#
# if not url.endswith("."):
#     print("sussy")
#
# savepath = rf"{gun_category}\{gun_type}"
# fullpath = os.path.join(current_directory, savepath)
# os.makedirs(fullpath, exist_ok=True)
# json_file_name = internal_name
# json_file_path = os.path.join(fullpath, f"{json_file_name}.json")
# image_file_name = internal_name
# image_file_path = os.path.join(fullpath, f"{image_file_name}.png")
# download_image(url, image_file_path)
# with open(json_file_path, "w") as file:
#     json.dump(asset, file, indent=4)
# print(json_file_path)
# print(fullpath)
# print(savepath)
# print(asset)
# print(assetPath)
# print(weapon_type)
# print(f'Total skinchromas: {len(data["data"])}')
# ################################################################################
assets = data["data"]
for asset in assets:
    assetPath = asset["assetPath"].split("/")
    weapon_type = assetPath[3]
    gun_category = ""
    gun_type = ""
    display_name = asset["displayName"]
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
        internal_name = assetPath[6]

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
