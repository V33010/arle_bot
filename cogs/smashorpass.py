import discord
import os
import random
import json
from discord.ui import Button, View
from discord.ext import commands

images_folder_path = (
    r"C:\Vivek\coding\arleBot\smashorpass\skin_assets\skins\allskins_full"
)


class SmashOrPass(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.image_folder = images_folder_path

    def get_random_image(self):
        """Fetch a random image from the folder."""
        images = [f for f in os.listdir(self.image_folder) if f.endswith(".png")]
        if not images:
            return None
        return os.path.join(self.image_folder, random.choice(images))

    @commands.slash_command(
        name="smashorpass", description="Send one random image with buttons"
    )
    async def smashorpass(self, ctx: discord.ApplicationContext):
        """Send one random image with working buttons."""
        image_path = self.get_random_image()
        if image_path is None:
            await ctx.respond("No images available in the folder.", ephemeral=True)
            return

        # Prepare the image file to send
        image = discord.File(image_path)

        # Buttons: Smash, Pass, Exit
        smash_button = Button(
            style=discord.ButtonStyle.danger, label="Smash", custom_id="smash"
        )
        pass_button = Button(
            style=discord.ButtonStyle.primary, label="Pass", custom_id="pass"
        )
        exit_button = Button(
            style=discord.ButtonStyle.success, label="Exit", custom_id="exit"
        )

        # Define the view with buttons
        view = View(timeout=None)
        view.add_item(smash_button)
        view.add_item(pass_button)
        view.add_item(exit_button)

        # Send the image with buttons
        message = await ctx.respond(file=image, view=view)
        original_user = ctx.user.id  # Store the user who initiated the session

        async def handle_interaction(interaction: discord.Interaction):
            """Handle button interactions."""
            if interaction.user.id != original_user:
                await interaction.response.send_message(
                    "This is not your session!", ephemeral=True
                )
                return

            if interaction.custom_id == "smash":
                response_text = "You smashed it!"
            elif interaction.custom_id == "pass":
                response_text = "You passed it!"
            elif interaction.custom_id == "exit":
                response_text = "You exited it!"
            await interaction.response.send_message(response_text)
            # Disable all buttons
            for item in view.children:
                if isinstance(item, Button):
                    item.disabled = True

            # Edit the original message to disable buttons
            await interaction.message.edit(view=view)

        # Link button callbacks to the interaction handler
        smash_button.callback = handle_interaction
        pass_button.callback = handle_interaction
        exit_button.callback = handle_interaction


def setup(bot):
    bot.add_cog(SmashOrPass(bot))
