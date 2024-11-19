from PIL import Image

# Replace 'output_example.png' with your PNG file
png_file = r"HvyMachineGuns\Odin\RGB\output_RGB.png"

# Open the PNG and check metadata
with Image.open(png_file) as img:
    metadata = img.info.get("JSON_Metadata", None)

if metadata:
    print("JSON Metadata:")
    print(metadata)
else:
    print("No JSON metadata found.")
