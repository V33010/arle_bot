import discord
from discord import Option
from discord.ext import commands


class Miscellaneous(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(
        name='add_emoji',
        description='Add a custom emoji to the server. Provide an image and name.',
    )
    async def add_emoji(
        self,
        ctx: discord.ApplicationContext,
        image: Option(discord.Attachment, 'The image to use for the emoji', required=True),
        name: Option(str, 'The name for the emoji', required=True),
    ):
        # Check if the user has the manage_emojis permission
        if not ctx.user.guild_permissions.manage_emojis:
            await ctx.respond("You don't have permission to add emojis!", ephemeral=True)
            return

        # Get the guild's emoji limits
        emoji_limit = ctx.guild.emoji_limit
        current_emoji_count = len(ctx.guild.emojis)
        available_slots = emoji_limit - current_emoji_count

        # Check if there are available slots
        if available_slots <= 0:
            await ctx.respond(
                f'Error: No emoji slots available! This server has reached its limit of {emoji_limit} emojis.',
                ephemeral=True,
            )
            return

        try:
            # Read the image
            image_bytes = await image.read()

            # Create the emoji
            new_emoji = await ctx.guild.create_custom_emoji(name=name, image=image_bytes)

            await ctx.respond(
                f'Successfully added emoji {new_emoji}!\n'
                f'There are now {available_slots - 1} emoji slots remaining out of {emoji_limit} total slots.'
            )

        except discord.HTTPException as e:
            if e.code == 50035:  # Invalid image data
                await ctx.respond(
                    "Error: The image file is invalid. Make sure it's a valid image format (PNG, JPG, GIF) "
                    'and under 256KB in size.',
                    ephemeral=True,
                )
            else:
                await ctx.respond(f'Error: Failed to add emoji. {str(e)}', ephemeral=True)


def setup(bot):
    bot.add_cog(Miscellaneous(bot))
