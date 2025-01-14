import tomllib
from timeit import default_timer as timer

import discord
from pydantic import ValidationError
from rich.traceback import install

from utils.logger import log
from validators.config import ConfigValidator


@log.catch()
def main():
    install()  # install rich colourful tracebacks
    log.info("Starting up arlebot")
    start = timer()
    log.debug("Starting timer")
    with open("config.toml", "rb") as f:
        data = tomllib.load(f)

    try:
        arle_config: ConfigValidator = ConfigValidator.model_validate(data)
        print("got here")
        log.success("Validated config successfully")
        log.debug(
            f'Config file \n{arle_config.model_dump_json(indent=4,exclude="secrets")}'
        )
    except ValidationError as v:
        log.error("invalid config file, cannot start up")
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
        server_names = [server.name for server in bot.guilds]
        for s in server_names:
            log.success(f"connected to {s}!")

    @bot.event
    async def on_application_command_error(
        ctx: discord.ApplicationContext, error: Exception
    ):
        # Catch CheckFailure specifically
        if isinstance(error, discord.errors.CheckFailure):
            with log.contextualize(
                user=ctx.author.name, channel=ctx.channel.name, server=ctx.guild.name
            ):
                log.warning(
                    f"Check failed for {ctx.command.name} command: {str(error)}"
                )

        else:
            log.error(f"Unexpected error in {ctx.command.name}: {error}")
            raise error

    extensions = [
        "cogs.discord-utils",
        "cogs.moderation",
        "cogs.smashorpass",
        "cogs.lyrics",
        "cogs.music_yt",
        "cogs.help",
        "cogs.misc",
        # 'cogs.video',
    ]

    if arle_config.arle.local_music:
        extensions.append("cogs.music")
    for extension in extensions:
        log.debug(f"loaded {extension} extension")
        bot.load_extension(extension)

    bot.run(arle_config.secrets.discord_token)
    log.warning("shutting down arlebot")
    log.debug("Goodbye :(")


if __name__ == "__main__":
    log.success("Hello :)")
    main()
