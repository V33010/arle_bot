from PIL import Image

with Image.open(r"allskins_full/output_809.png") as img:
    metadata = img.info
    if "JSON_Metadata" in metadata:
        print("Extracted JSON Metadata:")
        print(metadata["JSON_Metadata"])
