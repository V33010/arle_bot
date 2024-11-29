import typer
from setups.skins import skin_setup
from db.migrations import run_migrations

app = typer.Typer()


@app.command()
def skins(setup_skins: bool = True):
    if skins:
        skin_setup.run_setup()


@app.command()
def migrations(setup_db: bool = True):
    if setup_db:
        run_migrations()


if __name__ == "__main__":
    app()
