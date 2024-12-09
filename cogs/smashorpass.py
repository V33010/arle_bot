import tomllib

import discord
from discord.ext import commands
from discord.ui import Button, View

from db.arle import Database
from validators.config import ConfigValidator
from validators.skin import SkinChromas


class SmashOrPass(commands.Cog):
    def __init__(self, bot: commands.Bot):
        with open("config.toml", "rb") as t:
            data = tomllib.load(t)
        self.config: ConfigValidator = ConfigValidator.model_validate(data)
        self.db = Database(self.config)
        self.bot = bot
        self.session_threads = {}  # Maps user ID to thread ID

    @commands.slash_command(
        name="smashorpass", description="Start a Smash or Pass session."
    )
    async def smashorpass(self, ctx: discord.ApplicationContext):
        """Handles the Smash or Pass command."""
        try:
            # Acknowledge the interaction
            await ctx.defer(ephemeral=True)

            user_id = ctx.user.id

            # Check if the user already has a session
            if user_id in self.session_threads:
                await ctx.respond(
                    "You already have an active Smash or Pass session!", ephemeral=True
                )
                return

            # Create a thread for the session
            thread_name = f"{ctx.user.name}'s SmashOrPass Session"
            thread = await ctx.channel.create_thread(
                name=thread_name, type=discord.ChannelType.public_thread
            )

            # Store the thread ID for the user
            self.session_threads[user_id] = thread.id

            # Respond to the user
            await ctx.respond(
                f"Your session has started! Go to {thread.mention} to continue.",
                ephemeral=True,
            )

            # Start the Smash or Pass session
            await self.send_new_image(ctx.user, thread)

        except Exception as e:
            # Log any errors and inform the user
            print(f"Error in smashorpass command: {e}")
            await ctx.respond(
                "An error occurred while starting your session. Please try again later.",
                ephemeral=True,
            )

    async def send_new_image(self, user: discord.User, thread: discord.Thread):
        """Send a new image with buttons to the thread."""
        try:
            # Fetch an image and display name from the API
            skin: SkinChromas = self.db.fetch_random_image()
            if not skin.fullRender:
                await thread.send("Could not fetch an image. Please try again later.")
                return

            # Create buttons for Smash or Pass
            smash_button = Button(
                label="Smash", style=discord.ButtonStyle.danger, custom_id="smash"
            )
            pass_button = Button(
                label="Pass", style=discord.ButtonStyle.primary, custom_id="pass"
            )
            exit_button = Button(
                label="Exit", style=discord.ButtonStyle.success, custom_id="exit"
            )

            # Define the View and add callbacks
            view = View(timeout=None)
            view.add_item(smash_button)
            view.add_item(pass_button)
            view.add_item(exit_button)

            async def button_callback(interaction: discord.Interaction):
                """Handle button interactions."""
                if interaction.user.id != user.id:
                    await interaction.response.send_message(
                        "This is not your session!", ephemeral=True
                    )
                    return

                # Disable buttons and archive the thread
                for child in view.children:
                    child.disabled = True

                # Fetch the current embed
                current_embed = interaction.message.embeds[0]
                new_title = current_embed.title

                # Determine the user's choice
                if interaction.data["custom_id"] == "exit":
                    # End the session
                    await interaction.response.send_message(
                        "Session ended. Goodbye!", ephemeral=True
                    )
                    await interaction.message.edit(view=view)
                    await thread.archive()
                    self.session_threads.pop(user.id, None)
                else:
                    # Update embed title based on the user's choice
                    if interaction.data["custom_id"] == "smash":
                        new_title += " [Smashed]"
                    else:
                        new_title += " [Passed]"

                    # Update the embed with the new title
                    current_embed.title = new_title
                    await interaction.response.defer()
                    await interaction.message.edit(embed=current_embed, view=view)

                    # Send a new image
                    await self.send_new_image(user, thread)

            smash_button.callback = button_callback
            pass_button.callback = button_callback
            exit_button.callback = button_callback

            # Send the image and buttons to the thread
            embed = discord.Embed(title=skin.displayName, color=discord.Color.blue())
            embed.set_image(url=skin.fullRender)
            embed.set_footer(text=f"{user.name}'s session")
            await thread.send(embed=embed, view=view)

        except Exception as e:
            print(f"Error in send_new_image: {e}")
            await thread.send("An error occurred while fetching a new image.")

    def cog_unload(self):
        """Clean up when the cog is unloaded."""
        self.session_threads.clear()


def setup(bot):
    bot.add_cog(SmashOrPass(bot))
