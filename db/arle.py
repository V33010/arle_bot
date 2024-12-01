from validators.config import ConfigValidator
import libsql_experimental as libsql


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

    # write raw sql to db
    def write(self, sql: str, params: tuple = None):
        if params:
            self.conn.execute(sql, parameters=params)
        else:
            self.conn.execute(sql)
        self.conn.commit()

    def drop_table(self, table_name: str):
        sql = f"drop table if exists {table_name};"
        self.conn.execute(sql)
        self.conn.commit()
