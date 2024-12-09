from timeit import default_timer as timer
import discord
from pydantic import ValidationError
import tomllib
from validators.config import ConfigValidator
from rich.traceback import install
from utils.logger import log


def main():
    install()  # install rich colourful tracebacks
    log.info("Starting up arlebot")
    start = timer()
    log.debug("Starting timer")
    with open("config.toml", "rb") as f:
        data = tomllib.load(f)

    try:
        arle_config: ConfigValidator = ConfigValidator.model_validate(data)
        log.success("Validated config successfully")
        log.debug(f"Config file \n{arle_config.model_dump_json()}")
    except ValidationError as v:
        log.error("invalid config file , cannot start up")
        log.error(v)
        log.warning("shutting down . . .")
        log.debug("Goodbye :(")
        exit(1)

    intents = discord.Intents().all()
    intents.message_content = True
    intents.members = True

    bot = discord.Bot(intents=intents)

    @bot.event
    async def on_ready():
        end = timer()
        log.info(f"{bot.user} is ready and online in {end-start:.2f}s!")
        log.info(f"{bot.user} is connected to {bot.guilds}")

    extensions = [
        "cogs.discord-utils",
        "cogs.music",
        "cogs.moderation",
        "cogs.smashorpass",
    ]

    for extension in extensions:
        log.debug(f"loaded {extension} extension")
        bot.load_extension(extension)

    bot.run(arle_config.secrets.discord_token)
    log.warning("shutting down arlebot")
    log.debug("Goodbye :(")


if __name__ == "__main__":
    log.success("Hello :)")
    main()
