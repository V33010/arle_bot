import discord
import requests
from discord.ui import Button, View
from discord.ext import commands
import random


class SmashOrPass(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session_keys = {}  # Tracks keys for each user session

    async def fetch_image_from_api(self):
        """Fetch a random image URL and metadata from the API."""
        api_url = "https://valorant-api.com/v1/weapons/skinchromas"
        response = requests.get(api_url)

        if response.status_code == 200:
            data = response.json()["data"]
            # Choose a random skin chroma
            if data:
                image_data = random.choice(data)
                image_url = image_data["fullRender"]
                display_name = image_data["displayName"]
                return image_url, display_name
        return None, None

    @commands.slash_command(
        name="smashorpass", description="Start a SmashOrPass session."
    )
    async def smashorpass(self, ctx: discord.ApplicationContext):
        """Start the Smash or Pass session."""
        user_id = ctx.user.id
        self.session_keys[user_id] = 1
        previous_message = None

        # Send an initial acknowledgment response
        await ctx.respond("Starting Smash or Pass...", ephemeral=True)

        async def send_new_image():
            """Send a new image with buttons and attach callbacks."""
            image_url, display_name = await self.fetch_image_from_api()

            if not image_url:
                await ctx.send("Could not fetch an image from the API.")
                return None

            # Create buttons
            smash_button = Button(
                style=discord.ButtonStyle.danger, label="Smash", custom_id="smash"
            )
            pass_button = Button(
                style=discord.ButtonStyle.primary, label="Pass", custom_id="pass"
            )
            exit_button = Button(
                style=discord.ButtonStyle.success, label="Exit", custom_id="exit"
            )

            # Define the view
            view = View(timeout=None)
            view.add_item(smash_button)
            view.add_item(pass_button)
            view.add_item(exit_button)

            async def handle_interaction(interaction: discord.Interaction):
                """Handle button interactions."""
                nonlocal previous_message, view
                if interaction.user.id != user_id:
                    await interaction.response.send_message(
                        "This is not your session!", ephemeral=True
                    )
                    return

                response_text = ""

                if interaction.custom_id == "smash":
                    response_text = "You smashed it!"
                elif interaction.custom_id == "pass":
                    response_text = "You passed it!"
                elif interaction.custom_id == "exit":
                    response_text = "You exited the session!"
                    self.session_keys[user_id] = 0  # End session
                    await interaction.response.send_message(response_text)
                    # Disable all buttons
                    for item in view.children:
                        if isinstance(item, Button):
                            item.disabled = True
                    await interaction.message.edit(view=view)
                    return

                # Respond to the interaction
                await interaction.response.send_message(response_text, ephemeral=True)

                # Disable buttons on the previous message
                if previous_message:
                    for item in view.children:
                        if isinstance(item, Button):
                            item.disabled = True
                    await previous_message.edit(view=view)

                # Send the next image if session is still active
                if self.session_keys[user_id] == 1:
                    new_message, new_view = await send_new_image()
                    if new_message:
                        previous_message = new_message
                        view = new_view

            # Attach the callback to the buttons
            smash_button.callback = handle_interaction
            pass_button.callback = handle_interaction
            exit_button.callback = handle_interaction

            # Send the image with buttons
            embed = discord.Embed(title=display_name, color=discord.Color.blue())
            embed.set_image(url=image_url)
            embed.set_footer(
                text=f"{ctx.user.name}'s session"
            )  # Add username to the footer
            if self.session_keys[user_id] == 1:
                message = await ctx.send(embed=embed, view=view)
                return message, view
            else:
                return None, None

        # Initial image send
        previous_message, _ = await send_new_image()


def setup(bot):
    bot.add_cog(SmashOrPass(bot))
