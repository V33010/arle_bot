import random

import libsql_experimental as libsql

from utils.db import map_row_to_skin_chromas
from utils.logger import log
from validators.config import ConfigValidator
from validators.skin import SkinChromas


class Database:
    def __init__(self, config: ConfigValidator):
        if config.arle.dev_mode:
            self.db_url = config.database.dev.database_url
            self.db_name = config.database.dev.name
            self.conn: libsql.libsql_experimental.Connection = libsql.connect(self.db_name)
        else:
            self.db_url = config.database.prod.database_url
            self.auth_token = config.database.prod.database_auth_token
            self.db_name = config.database.prod.name
            self.conn: libsql.libsql_experimental.Connection = libsql.connect(
                self.db_name,
                sync_url=self.db_url,
                auth_token=self.auth_token,
                sync_interval=60,
            )
        log.success('connected to db successfully')

    # write raw sql to db
    def write(self, sql: str, params: tuple = None):
        if params:
            log.debug(f'writing {sql} to db with params = {params}')
            self.conn.execute(sql, parameters=params)
        else:
            log.debug(f'writing {sql} to db')
            self.conn.execute(sql)
        self.conn.commit()

    def drop_table(self, table_name: str):
        sql = f'drop table if exists {table_name};'
        log.debug(f'writing {sql} to db')
        self.conn.execute(sql)
        self.conn.commit()

    def fetch_random_skin(self) -> SkinChromas:
        skin_id = random.randint(1, 2023)
        result = self.conn.execute(f'select * from skins where id={skin_id}')
        row = result.fetchall()
        skin = map_row_to_skin_chromas(row)
        self.update_occurance(skin.uuid)
        skin.total_occurance_rate += 1
        return skin

    # increases the total_occurance_rate counter in the db , this is called automatically when a skin is fetched
    def update_occurance(self, uuid: str):
        sql = f"update skins set total_occurrence_rate = total_occurrence_rate + 1 where uuid = '{uuid}'"
        self.conn.execute(sql)
        self.conn.commit()

    # increments the pickrate counter for a skin , should be called when a skin is smashed
    def increment_pickrate(self, uuid: str):
        sql = f"update skins set pickrate = pickrate + 1 where uuid = '{uuid}'"
        self.conn.execute(sql)
        self.conn.commit()
