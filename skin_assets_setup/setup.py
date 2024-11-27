import shutil
import json
import os
import helper
from helper import clean_display_name, download_image, embed_json_in_png


def obtain_images(filepath):  # filepath to the "skinchromas.json"
    with open(filepath, "r") as file:
        data = json.load(file)

    current_directory = os.getcwd()
    error_urls = []

    gun_map = helper.gun_map()
    assets = data["data"]
    total_assets = len(assets)
    count = 0
    actual = 0
    for asset in assets:
        count += 1
        print(f"Downloading image: [{count}/{total_assets}]", end="\r")
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
            internal_name = cleaned_display_name
        else:
            print("New weapon type found!")

        # savepath = rf"{gun_category}\{gun_type}\{internal_name}"
        savepath = os.path.join(gun_category,gun_type,internal_name)
        fullpath = os.path.join(current_directory, savepath)
        os.makedirs(fullpath, exist_ok=True)
        json_file_name = internal_name
        json_file_path = os.path.join(fullpath, f"{json_file_name}.json")
        image_file_name = internal_name
        image_file_path = os.path.join(fullpath, f"{image_file_name}.png")
        try:
            download_image(url, image_file_path)
            actual += 1
        except Exception as e:
            error_urls.append(url)
        with open(json_file_path, "w") as file:
            json.dump(asset, file, indent=4)

    print(error_urls)
    return actual


def process_subsubfolder(subsubfolder_path):
    """Process a subsubfolder to embed JSON into PNG."""
    # List all items in the subsubfolder
    items = os.listdir(subsubfolder_path)
    json_file = None
    png_file = None

    # Identify the JSON and PNG files
    for item in items:
        if item.endswith(".json"):
            json_file = os.path.join(subsubfolder_path, item)
        elif item.endswith(".png"):
            png_file = os.path.join(subsubfolder_path, item)

    # Ensure both JSON and PNG files are present
    if json_file and png_file:
        # Create the output PNG path
        input_file_name = os.path.splitext(os.path.basename(png_file))[0]
        output_file_name = f"output_{input_file_name}.png"
        output_path = os.path.join(subsubfolder_path, output_file_name)

        # Embed JSON into PNG
        embed_json_in_png(json_file, png_file, output_path)
        # print(f"Created: {output_path}")
    else:
        print(f"Skipped {subsubfolder_path}: Missing JSON or PNG file.")


def process_main_folders(base_path, folders, total_assets):
    count = 0

    """Process the specified folders and their contents."""
    for folder in folders:
        folder_path = os.path.join(base_path, folder)
        if os.path.isdir(folder_path):
            # Traverse subfolders
            for subfolder in os.listdir(folder_path):
                subfolder_path = os.path.join(folder_path, subfolder)
                if os.path.isdir(subfolder_path):
                    # Traverse subsubfolders
                    for subsubfolder in os.listdir(subfolder_path):
                        subsubfolder_path = os.path.join(subfolder_path, subsubfolder)
                        if os.path.isdir(subsubfolder_path):
                            count += 1
                            print(
                                f"Processing output PNGs: [{count}/{total_assets}]",
                                end="\r",
                            )
                            process_subsubfolder(subsubfolder_path)


# Define the destination folder
destination_folder = "allskins_full"

# Create destination folder if it doesn't exist
if not os.path.exists(destination_folder):
    os.makedirs(destination_folder)


def copy_output_pngs(subsubfolder_path):
    """Copy PNG files starting with 'output' from subsubfolder to the destination folder."""
    # List all items in the subsubfolder
    items = os.listdir(subsubfolder_path)

    for item in items:
        # Only consider PNG files that start with 'output'
        if item.endswith(".png") and item.startswith("output"):
            source_file = os.path.join(subsubfolder_path, item)
            destination_file = os.path.join(destination_folder, item)

            # Copy the file to the destination folder
            shutil.copy(source_file, destination_file)
            # print(f"Copied: {source_file} to {destination_file}")


def process_subsubfolder_copypasta(subsubfolder_path):
    """Process a subsubfolder to find and copy output PNGs."""
    # Check if the folder exists and is a directory
    if os.path.isdir(subsubfolder_path):
        copy_output_pngs(subsubfolder_path)


def process_main_folders_copypasta(base_path, folders, total_assets):
    count = 0
    """Process the specified main folders and their subfolders."""
    for folder in folders:
        folder_path = os.path.join(base_path, folder)
        if os.path.isdir(folder_path):
            # Traverse subfolders
            for subfolder in os.listdir(folder_path):
                subfolder_path = os.path.join(folder_path, subfolder)
                if os.path.isdir(subfolder_path):
                    # Traverse subsubfolders
                    for subsubfolder in os.listdir(subfolder_path):
                        subsubfolder_path = os.path.join(subfolder_path, subsubfolder)
                        if os.path.isdir(subsubfolder_path):
                            count += 1
                            print(f"Copying: [{count}/{total_assets}]", end="\r")
                            process_subsubfolder_copypasta(subsubfolder_path)


if __name__ == "__main__":
    cwd = os.getcwd()
    if not os.path.exists("skinchromas.json"):
        print(f"skinchromas.json does not exist.\nDownloading...")
        helper.download_skinchromas()
    else:
        print("skinchromas.json already exists.")
    filepath = "skinchromas.json"
    print(f"Starting download...")
    total_assets = obtain_images(filepath)

    print("Obtaining folders...")
    folders_to_process = helper.folders_to_process_list()
    # Process the specified folders
    print("Starting to process output PNGs...")
    process_main_folders(cwd, folders_to_process, total_assets)
    print("Copying items...")
    process_main_folders_copypasta(cwd, folders_to_process, total_assets)
