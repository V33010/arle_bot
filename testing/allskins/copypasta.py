import os
import shutil

# Define the seven folders to process
folders_to_process = [
    "HvyMachineGuns",
    "Melee",
    "Rifles",
    "Shotguns",
    "Sidearms",
    "SniperRifles",
    "SubMachineGuns",
]

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
            print(f"Copied: {source_file} to {destination_file}")


def process_subsubfolder(subsubfolder_path):
    """Process a subsubfolder to find and copy output PNGs."""
    # Check if the folder exists and is a directory
    if os.path.isdir(subsubfolder_path):
        copy_output_pngs(subsubfolder_path)


def process_main_folders(base_path, folders):
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
                            process_subsubfolder(subsubfolder_path)


if __name__ == "__main__":
    # Get the current working directory
    cwd = os.getcwd()

    # Process the specified folders
    process_main_folders(cwd, folders_to_process)

    print("File copying complete!")

