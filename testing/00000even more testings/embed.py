from PIL import Image, PngImagePlugin
import json

# JSON data to embed
metadata = {
    "uuid": "5d5b1d55-4047-a5c6-b1d2-23a940d55fb0",
    "displayName": "Task Force 809 Knife",
    "displayIcon": "https://media.valorant-api.com/weaponskinchromas/5d5b1d55-4047-a5c6-b1d2-23a940d55fb0/displayicon.png",
    "fullRender": "https://media.valorant-api.com/weaponskinchromas/5d5b1d55-4047-a5c6-b1d2-23a940d55fb0/fullrender.png",
    "swatch": None,
    "streamedVideo": None,
    "assetPath": "ShooterGame/Content/Equippables/Melee/809/Chromas/Standard/Melee_809_Standard_PrimaryAsset",
}

# Convert the JSON data to a string
json_str = json.dumps(metadata)

# Open an existing PNG file
with Image.open(r"809.png") as img:
    # Add metadata to the PNG
    meta = PngImagePlugin.PngInfo()
    meta.add_text("JSON_Metadata", json_str)

    # Save the PNG with metadata
    img.save("output.png", "png", pnginfo=meta)

print("JSON metadata embedded into output.png.")
