import json
from PIL import Image, PngImagePlugin  # noqa: F401
import os
import helper
from helper import clean_display_name, download_image, gun_map

if not os.path.exists("skinchromas.json"):
    helper.download_skinchromas()
else:
    print("skinchromas.json already exists.")
    
filepath = "skinchromas.json"

with open(filepath, "r") as file:
    data = json.load(file)

current_directory = os.getcwd()

gun_map = gun_map()
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
        print("New weapon type found!")

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


#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
