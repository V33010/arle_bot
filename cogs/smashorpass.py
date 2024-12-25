import random
import tomllib

import discord
from discord.ext import commands
from discord.ui import Button, View

from db.arle import Database
from utils.logger import log, get_context_logger
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
        ctxlog = get_context_logger(ctx)
        ctxlog.info("got smash or pass request")
        try:
            # Acknowledge the interaction
            await ctx.defer(ephemeral=True)

            user_id = ctx.user.id
            # Check if the user already has a session
            if user_id in self.session_threads:
                await ctx.respond(
                    "You already have an active Smash or Pass session!",
                    ephemeral=True,
                )
                log.warning("user has an active session")
                return

            # Create a thread for the session
            thread_name = f"{ctx.user.name}'s SmashOrPass Session"
            thread = await ctx.channel.create_thread(
                name=thread_name, type=discord.ChannelType.public_thread
            )
            ctxlog.success(f"thread created succesfully {thread_name}")

            # Store the thread ID for the user
            self.session_threads[user_id] = thread.id

            # Respond to the user
            await ctx.respond(
                f"Your session has started! Go to {thread.mention} to continue.",
                ephemeral=True,
            )
            ctxlog.success("session started in thread successfully")
            # Start the Smash or Pass session

            await self.send_new_image(ctx.user, thread, ctxlog)

        except Exception as e:
            # Log any errors and inform the user
            log.exception(f"Error in smashorpass command: {e}")
            await ctx.respond(
                "An error occurred while starting your session. Please try again later.",
                ephemeral=True,
            )

    async def send_new_image(self, user: discord.User, thread: discord.Thread, log=log):
        sus_link = "https://r.mtdv.me/videos/araxysvandal"
        """Send a new image with buttons to the thread."""

        log.info("Sending skin image")
        try:
            # Fetch an image and display name from the API
            skin: SkinChromas = self.db.fetch_random_skin()

            log.debug(
                f"fetched {skin.displayName.replace("\n", " ").replace("\r", " ")} | occurance_rate {skin.total_occurance_rate} | pick_rate {skin.pickrate}"
            )

            video_url = skin.streamedVideo
            log.debug(f"video_url is {video_url}")
            if not skin.fullRender:
                await thread.send("Could not fetch an image. Please try again later.")
                log.critical("could not fetch skin image")
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
            video_button = Button(
                label="Video", style=discord.ButtonStyle.secondary, custom_id="video"
            )

            # Define the View and add callbacks
            view = View(timeout=None)
            view.add_item(smash_button)
            view.add_item(pass_button)
            if video_url:
                view.add_item(video_button)
            view.add_item(exit_button)

            async def button_callback(interaction):
                """Handle button interactions."""
                if interaction.user.id != user.id:
                    await interaction.response.send_message(
                        "This is not your session!", ephemeral=True
                    )
                    log.info("invalid session access attempted")
                    return

                # Disable buttons and archive the thread
                for child in view.children:
                    child.disabled = True

                # Fetch the current embed
                current_embed = interaction.message.embeds[0]
                new_title = current_embed.title

                # Determine the user's choice
                if interaction.data["custom_id"] == "video":
                    if video_url:
                        log.info("video url exists for this skin")
                        log.debug(video_url)
                        url_str = str(video_url)
                        if random.random() < 0.0001:
                            url_str = str(sus_link)
                        await interaction.response.send_message(
                            f"[link]({url_str})", ephemeral=True
                        )
                        log.success("video url sent successfully")
                    else:
                        await interaction.response.send_message(
                            "No video available for this skin."
                        )
                        log.info("no video url for this skin")

                else:
                    if interaction.data["custom_id"] == "exit":
                        # End the session
                        await interaction.response.send_message(
                            "Session ended. Goodbye!", ephemeral=True
                        )
                        log.info("ending session")
                        await interaction.message.edit(view=view)
                        await thread.archive()
                        self.session_threads.pop(user.id, None)
                    else:
                        # Update embed title based on the user's choice
                        if interaction.data["custom_id"] == "smash":
                            pick_rate = round(
                                (skin.pickrate + 1 / skin.total_occurance_rate) * 100, 2
                            )
                            new_title += f" [Smashed]"
                            new_field = f"Pickrate: {pick_rate}%"
                            log.debug(new_title)
                            self.db.increment_pickrate(
                                skin.uuid
                            )  # updates pickrate for the skin
                        else:
                            pick_rate = round(  # don't have to increase total_occurance_rate here since it's automatically taken care of while fetching the skin
                                (skin.pickrate / skin.total_occurance_rate) * 100, 2
                            )
                            new_title += f" [Passed]"
                            new_field = f"Pickrate: {pick_rate}%"
                            log.debug(new_title)

                        # Update the embed with the new title
                        current_embed.title = new_title
                        current_embed.add_field(name=new_field, value="", inline=False)
                        await interaction.response.defer()
                        await interaction.message.edit(embed=current_embed, view=view)

                        # Send a new image
                        await self.send_new_image(user, thread, log)

            smash_button.callback = button_callback
            pass_button.callback = button_callback
            exit_button.callback = button_callback
            video_button.callback = button_callback

            # Send the image and buttons to the thread
            embed = discord.Embed(title=skin.displayName, color=discord.Color.blue())
            embed.set_image(url=skin.fullRender)
            embed.set_footer(text=f"{user.name}'s session")
            await thread.send(embed=embed, view=view)

        except Exception as e:
            log.critical(f"Error in send_new_image: {e}")
            await thread.send("An error occurred while fetching a new image.")

    def cog_unload(self):
        """Clean up when the cog is unloaded."""
        self.session_threads.clear()


def setup(bot):
    bot.add_cog(SmashOrPass(bot))
