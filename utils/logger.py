import sys

import discord
from loguru import logger

globalFormat = (
    '<green>{time:YYYY-MM-DD HH:mm:ss}</green>| '
    '<level>{level: <8}</level>| '
    '<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - '
    '<level>{message}</level>'
    ' {extra}'
)


def setup_logging():
    # Remove any default logger handlers
    logger.remove()

    # Add a new handler with a detailed, informative format
    logger.add(
        sys.stdout,
        colorize=True,
        format=globalFormat,
        level='TRACE',  # Capture all log levels from DEBUG upwards
    )
    logger.add(
        'app.log',
        rotation='100 MB',
        format=globalFormat,
        level='TRACE',
    )

    logger.level('INFO', color='<light-white>')
    return logger


# Create a global logger instance that can be imported everywhere
log = setup_logging()


def get_context_logger(ctx: discord.ApplicationContext):
    return log.bind(
        user=ctx.author.name,
        channel=ctx.channel.name,
        server=ctx.guild.name,
        user_id=ctx.author.id,
    )
