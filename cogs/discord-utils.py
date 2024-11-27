import platform
import discord
import subprocess
import os
from discord.commands import slash_command
from discord.ext import commands
from utils import reboot


class Ping(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Create the restart script when the cog is loaded
        self.create_restart_script()

    def create_restart_script(self):
        """Creates the permanent restart script"""
        cogs_dir = os.path.dirname(os.path.abspath(__file__))
        bot_dir = os.path.dirname(cogs_dir)
        bot_path = os.path.join(bot_dir, "arlebot.py")

        restart_path_win = os.path.join(bot_dir, "reboot_bot.bat")
        restart_path_linux = os.path.join(bot_dir, "reboot_bot.sh")
        restart_path = restart_path_linux

        restart_file, platform = reboot.get_restart_file(bot_dir, bot_path)

        if platform == "Windows":
            restart_path = restart_path_win

            # Only create if it doesn't exist
        with open(restart_path, "w") as exe_file:
            exe_file.write(restart_file)

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

            restart_path = os.path.join(bot_dir, "reboot_bot.bat")
            if platform.system() == "Linux":
                restart_path = os.path.join(bot_dir, "reboot_bot.sh")

            reboot.make_executable(restart_path)
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
