import tomllib

from db.arle import Database
from setups.db.schema import (
    c_acc_crosshair_tbl,
    c_acc_skins_tbl,
    c_acc_tbl,
    c_crosshairs_tbl,
    c_skins_tbl,
    c_users_tbl,
)
from validators.config import ConfigValidator


def setup_tables():
    with open('config.toml', 'rb') as t:
        data = tomllib.load(t)
    config: ConfigValidator = ConfigValidator.model_validate(data)
    db = Database(config)

    db.write(c_users_tbl)
    db.write(c_acc_tbl)
    db.write(c_skins_tbl)
    db.write(c_acc_skins_tbl)
    db.write(c_crosshairs_tbl)
    db.write(c_acc_crosshair_tbl)


if __name__ == '__main__':
    setup_tables()
