import requests


def populate_weapons_table():
    endpoint = "https://valorant-api.com/v1/weapons/skinchromas"
    response = requests.get(endpoint)
    if response.status_code == 200:
        data = response.json()["data"]
        print(len(data))
