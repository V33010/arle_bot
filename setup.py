import typer
from setups.skins import skin_setup
from setups.db.tables import setup_tables
from setups.db.skins import populate_skins_table
from setups.db.reset import reset_database
from rich.traceback import install

install()

app = typer.Typer()


@app.command()
def skins(setup_skins: bool = True):
    if skins:
        skin_setup.run_setup()


@app.command()
def db(schema: bool = False, skins: bool = False, reset: bool = False):
    if schema:
        setup_tables()
    if skins:
        setup_tables()
        populate_skins_table()
    if reset:
        reset_database()


if __name__ == "__main__":
    app()
