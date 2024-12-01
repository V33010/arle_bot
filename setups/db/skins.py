import requests
import tomllib
from db.arle import Database
from validators.skin import SkinChromas
from validators.config import ConfigValidator


def populate_skins_table():
    with open("config.toml", "rb") as f:
        data = tomllib.load(f)
    config: ConfigValidator = ConfigValidator.model_validate(data)
    db = Database(config)

    endpoint = "https://valorant-api.com/v1/weapons/skinchromas"
    response = requests.get(endpoint)
    if response.status_code == 200:
        data = response.json()["data"]
        for skin in data:
            valSkin: SkinChromas = SkinChromas(**skin)
            sql = "insert into skins (displayName,uuid,displayIcon,fullRender,swatch,streamedVideo,assetPath) values (?,?,?,?,?,?,?)"
            params = (
                valSkin.displayName,
                valSkin.uuid,
                str(valSkin.displayIcon) if valSkin.displayIcon else "NULL",
                str(valSkin.fullRender) if valSkin.fullRender else "NULL",
                str(valSkin.swatch) if valSkin.swatch else "NULL",
                str(valSkin.streamedVideo) if valSkin.streamedVideo else "NULL",
                valSkin.assetPath,
            )
            # print(sql)
            db.write(sql, params)
