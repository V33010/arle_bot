import json

filepath = "skinchromas.json"

with open(filepath, "r") as file:
    data = json.load(file)

print(data["data"][0])

print(f'Total skinchromas: {len(data["data"])}')
