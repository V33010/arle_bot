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
        self.images_folder = images_folder_path
        self.session_active = {}  # Track user sessions

    def get_random_image(self):
        """Fetch a random image and its metadata."""
        images = [f for f in os.listdir(self.images_folder) if f.endswith(".png")]
        if not images:
            return None, None

        image = random.choice(images)
        image_path = os.path.join(self.images_folder, image)
        with open(image_path, "rb") as img_file:
            # Assuming the image has JSON metadata embedded as a comment or separate
            metadata = {}  # Fetch your JSON metadata from the image (you may need a library like PIL or similar)

        return image_path, metadata

    @commands.slash_command(
        name="smashorpass", description="Start a Smash or Pass session"
    )
    async def smashorpass(self, ctx: discord.ApplicationContext):
        """Start the Smash or Pass game."""
        if ctx.user.id in self.session_active and self.session_active[ctx.user.id]:
            await ctx.respond("You already have an active session!", ephemeral=True)
            return

        self.session_active[ctx.user.id] = True
        await ctx.respond("Starting Smash or Pass session...", ephemeral=True)
        await self.send_image(ctx)

    async def send_image(self, ctx: discord.ApplicationContext):
        """Send a random image with buttons."""
        image_path, metadata = self.get_random_image()

        if image_path is None:
            await ctx.send("No images available.")
            self.session_active[ctx.user.id] = False
            return

        image = discord.File(image_path)
        metadata_str = json.dumps(
            metadata, indent=2
        )  # You may want to format the metadata for display

        # Buttons for Smash, Pass, and Exit
        smash_button = Button(
            style=discord.ButtonStyle.danger, label="Smash", custom_id="smash"
        )
        pass_button = Button(
            style=discord.ButtonStyle.primary, label="Pass", custom_id="pass"
        )
        exit_button = Button(
            style=discord.ButtonStyle.success, label="Exit", custom_id="exit"
        )

        view = View(timeout=None)
        view.add_item(smash_button)
        view.add_item(pass_button)
        view.add_item(exit_button)

        # Wait for user interaction with buttons
        await ctx.send(content=f"Metadata:\n{metadata_str}", file=image, view=view)

        # Handle interactions with buttons
        def check(interaction):
            return interaction.user.id == ctx.user.id

        interaction = await self.bot.wait_for("button_click", check=check)

        if interaction.custom_id == "smash":
            await interaction.response.send_message(
                f"{interaction.user.name} smashed!", ephemeral=True
            )
        elif interaction.custom_id == "pass":
            await interaction.response.send_message(
                f"{interaction.user.name} passed!", ephemeral=True
            )
        elif interaction.custom_id == "exit":
            await interaction.response.send_message(
                f"{interaction.user.name} exited the session.", ephemeral=True
            )
            self.session_active[ctx.user.id] = False
            return

        # Recursively send the next image after a response
        await self.send_image(ctx)


def setup(bot):
    bot.add_cog(SmashOrPass(bot))
