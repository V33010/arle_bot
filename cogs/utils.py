import discord
import subprocess
import sys
import os
import asyncio
from discord.commands import slash_command
from discord.ext import commands


class Ping(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Create the restart script when the cog is loaded
        self.create_restart_script()

    def create_restart_script(self):
        """Creates the permanent restart script"""
        cogs_dir = os.path.dirname(os.path.abspath(__file__))
        bot_dir = os.path.dirname(cogs_dir)
        restart_path = os.path.join(bot_dir, "restart_bot.bat")

        # Only create if it doesn't exist
        if not os.path.exists(restart_path):
            with open(restart_path, "w") as bat_file:
                bat_file.write(f"""
@echo off
cd /d "{bot_dir}"
timeout /t 2 /nobreak > nul
python "{os.path.join(bot_dir, 'arleBot.py')}"
""")

    @slash_command(name="ping", description="Return bot latency")
    async def ping(self, ctx: discord.ApplicationContext):
        await ctx.respond(f"pong! ({self.bot.latency * 1000:.2f} ms)")

    @slash_command(name="reboot", description="Reboots the bot (Owner only)")
    @commands.is_owner()
    async def reboot(self, ctx: discord.ApplicationContext):
        """Reboots the bot"""
        try:
            await ctx.respond("Rebooting...", ephemeral=True)

            # Get paths
            cogs_dir = os.path.dirname(os.path.abspath(__file__))
            bot_dir = os.path.dirname(cogs_dir)
            restart_path = os.path.join(bot_dir, "restart_bot.bat")

            # Start the restart script
            subprocess.Popen([restart_path], shell=True, cwd=bot_dir)

            # Close the bot
            await self.bot.close()

            # Exit the process
            os._exit(0)

        except Exception as e:
            await ctx.respond(f"Error during reboot: {str(e)}", ephemeral=True)


def setup(bot):
    bot.add_cog(Ping(bot))

