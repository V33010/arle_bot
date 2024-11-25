import requests
import os
import json

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

filepath = "skinchromas.json"

with open(filepath, "r") as file:
    data = json.load(file)

current_directory = os.getcwd()


def clean_display_name(display_name):
    return "".join(c for c in display_name if c.isalnum())


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
