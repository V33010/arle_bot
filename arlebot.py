import discord
import os
from dotenv import load_dotenv


def clear_terminal():
    print("\033[H\033[J")


load_dotenv()
clear_terminal()
intents = discord.Intents().all()
intents.message_content = True
intents.members = True

bot = discord.Bot(intents=intents)


@bot.event
async def on_ready():
    print(f"{bot.user} is ready and online!")


extensions = [
    "cogs.utils",
    "cogs.music",
    "cogs.moderation",
    "cogs.smashorpass",
]

if __name__ == "__main__":
    for extension in extensions:
        bot.load_extension(extension)


bot.run(os.getenv("TOKEN"))
