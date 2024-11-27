import os
import json
from PIL import Image, PngImagePlugin

# Define the seven folders to work with
folders_to_process = [
    "HvyMachineGuns",
    "Melee",
    "Rifles",
    "Shotguns",
    "Sidearms",
    "SniperRifles",
    "SubMachineGuns",
]


def embed_json_in_png(json_path, png_path, output_path):
    """Embed JSON content into the metadata of a PNG file."""
    with open(json_path, "r") as json_file:
        json_data = json.load(json_file)  # Load JSON content

    with Image.open(png_path) as img:
        meta = PngImagePlugin.PngInfo()
        meta.add_text("JSON_Metadata", json.dumps(json_data))  # Add JSON metadata
        img.save(output_path, "png", pnginfo=meta)  # Save new PNG


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
        print(f"Created: {output_path}")
    else:
        print(f"Skipped {subsubfolder_path}: Missing JSON or PNG file.")


def process_main_folders(base_path, folders):
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
                            process_subsubfolder(subsubfolder_path)


if __name__ == "__main__":
    print("Main")
    # Get the current working directory
    # cwd = os.getcwd()
    #
    # # Process the specified folders
    # process_main_folders(cwd, folders_to_process)
