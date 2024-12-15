from validators.config import ConfigValidator
from utils.db import map_row_to_skin_chromas
import libsql_experimental as libsql
from validators.skin import SkinChromas
import random
from utils.logger import log


class Database:
    def __init__(self, config: ConfigValidator):
        if config.arle.dev_mode:
            self.db_url = config.database.dev.database_url
            self.db_name = config.database.dev.name
            self.conn: libsql.libsql_experimental.Connection = libsql.connect(
                self.db_name
            )
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
        log.success("connected to db successfully")

    # write raw sql to db
    def write(self, sql: str, params: tuple = None):
        if params:
            log.debug(f"writing {sql} to db with params = {params}")
            self.conn.execute(sql, parameters=params)
        else:
            log.debug(f"writing {sql} to db")
            self.conn.execute(sql)
        self.conn.commit()

    def drop_table(self, table_name: str):
        sql = f"drop table if exists {table_name};"
        log.debug(f"writing {sql} to db")
        self.conn.execute(sql)
        self.conn.commit()

    def fetch_random_skin(self) -> SkinChromas:
        skin_id = random.randint(1, 2023)
        result = self.conn.execute(f"select * from skins where id={skin_id}")
        rows = result.fetchall()
        return map_row_to_skin_chromas(rows)
