# sample text
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
        try:
            # First, try to respond to the interaction
            await ctx.defer(ephemeral=True)
            await asyncio.sleep(0.5)  # Small delay to ensure defer is processed
            await ctx.followup.send("Rebooting...", ephemeral=True)

            # Disconnect from voice if connected
            if ctx.guild.voice_client:
                try:
                    await ctx.guild.voice_client.disconnect()
                except Exception as e:
                    print(f"Failed to disconnect from voice: {e}")

            # Get paths
            cogs_dir = os.path.dirname(os.path.abspath(__file__))
            bot_dir = os.path.dirname(cogs_dir)
            restart_path = os.path.join(bot_dir, "restart_bot.bat")
            pid_file = os.path.join(bot_dir, "bot.pid")

            # Save current PID
            with open(pid_file, "w") as f:
                f.write(str(os.getpid()))

            # Create a more robust restart script
            with open(restart_path, "w") as bat_file:
                bat_file.write(f"""
@echo off
cd /d "{bot_dir}"

:: Kill any existing Python processes running the bot
if exist "{pid_file}" (
    set /p BOT_PID=<"{pid_file}"
    taskkill /F /PID %BOT_PID% /T > nul 2>&1
    del "{pid_file}"
)

:: Additional cleanup of any remaining instances
taskkill /F /FI "WINDOWTITLE eq arleBot*" /T > nul 2>&1

:: Wait for processes to fully terminate
timeout /t 3 /nobreak > nul

:: Start the bot in a new window
start "arleBot" /MIN cmd /c "python "{os.path.join(bot_dir, 'arleBot.py')}" & pause"

:: Exit the restart script
exit
""")

            # Start the restart script in a separate process
            subprocess.Popen(
                [restart_path], shell=True, creationflags=subprocess.CREATE_NEW_CONSOLE
            )

            # Give time for the response to be sent
            await asyncio.sleep(1)

            # Close the bot
            await self.bot.close()

            # Force exit the process
            os._exit(0)

        except Exception as e:
            print(f"Error during reboot: {e}")
            if not ctx.response.is_done():
                await ctx.respond(f"Error during reboot: {str(e)}", ephemeral=True)

    @commands.slash_command(
        name="clear_device_terminal", description="Clear the terminal screen."
    )
    async def clear_device_terminal(self, ctx: discord.ApplicationContext):
        print("\033[H\033[J")
        await ctx.respond("Cleared the device terminal.")


def setup(bot):
    bot.add_cog(Ping(bot))
