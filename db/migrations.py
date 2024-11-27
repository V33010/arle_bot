from validators.config import ConfigValidator
import tomllib
from db.arle import Database
from db.schema import (
    c_users_tbl,
    c_acc_tbl,
    c_skins_tbl,
    c_acc_skins_tbl,
    c_crosshairs_tbl,
    c_acc_crosshair_tbl,
)


def run_migrations():
    with open("config.toml", "rb") as t:
        data = tomllib.load(t)
    config: ConfigValidator = ConfigValidator.model_validate(data)
    db = Database(config)

    db.write(c_users_tbl)
    db.write(c_acc_tbl)
    db.write(c_skins_tbl)
    db.write(c_acc_skins_tbl)
    db.write(c_crosshairs_tbl)
    db.write(c_acc_crosshair_tbl)


run_migrations()
