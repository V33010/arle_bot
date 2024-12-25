# reset the database , this drops all tables and deletes any information stored
import tomllib

from db.arle import Database
from validators.config import ConfigValidator


def reset_database():
    with open('config.toml', 'rb') as t:
        data = tomllib.load(t)
    config: ConfigValidator = ConfigValidator.model_validate(data)
    db = Database(config)
    tables = [
        'users',
        'accounts',
        'skins',
        'account_skins',
        'crosshairs',
        'account_crosshairs',
    ]
    for table in tables:
        db.drop_table(table)
        print(f'dropped table {table}')
