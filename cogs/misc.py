from datetime import datetime

import discord
from discord import Option
from discord.ext import commands

from utils.logger import get_context_logger


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
        ctxlogger = get_context_logger(ctx)
        ctxlogger.info(f'{ctx.author.name} used command add_emoji')
        # Check if the user has the manage_emojis permission
        if not ctx.user.guild_permissions.manage_emojis:
            await ctx.respond("You don't have permission to add emojis!", ephemeral=True)
            ctxlogger.warn(
                f'{ctx.author.name} used add_emoji command without sufficient permissions'
            )
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
            ctxlogger.error(f'{ctx.guild.name} has no more emoji slots empty')
            return

        try:
            # Read the image
            image_bytes = await image.read()
            ctxlogger.debug('Image read successfully')

            # Create the emoji
            new_emoji = await ctx.guild.create_custom_emoji(name=name, image=image_bytes)

            await ctx.respond(
                f'Successfully added emoji {new_emoji}!\n'
                f'There are now {available_slots - 1} emoji slots remaining out of {emoji_limit} total slots.'
            )
            ctxlogger.success(f'Added emoji successfully: {name}')

        except discord.HTTPException as e:
            if e.code == 50035:  # Invalid image data
                await ctx.respond(
                    "Error: The image file is invalid. Make sure it's a valid image format (PNG, JPG, GIF) "
                    'and under 256KB in size.',
                    ephemeral=True,
                )
                ctxlogger.error('Invalid image format.')
            else:
                await ctx.respond(f'Error: Failed to add emoji. {str(e)}', ephemeral=True)
                ctxlogger.error(f'Failed to add emoji: {str(e)}')

    @commands.slash_command(
        name='user_avatar', description='Get the high-resolution avatar of any user'
    )
    async def user_avatar(
        self,
        ctx: discord.ApplicationContext,
        user: Option(discord.Member, 'The user whose avatar you want to see', required=False),
    ):
        ctxlogger = get_context_logger(ctx)
        ctxlogger.info(f'{ctx.author.name} used command user_avatar')
        # If no user is specified, use the command invoker
        target_user = user or ctx.author
        ctxlogger.info(f'Target user is {target_user}')

        # Create an embed for the avatar
        embed = discord.Embed(title=f"{target_user.display_name}'s Avatar", color=target_user.color)

        # Get both server-specific and global avatars if they exist
        server_avatar = target_user.guild_avatar
        global_avatar = target_user.avatar or target_user.default_avatar

        if server_avatar:
            # User has a server-specific avatar
            embed.add_field(
                name='Server Avatar',
                value=f"[PNG]({server_avatar.url}) | [JPG]({server_avatar.replace(format='jpg').url}) | [WEBP]({server_avatar.replace(format='webp').url})",
            )
            embed.set_image(url=server_avatar.url)

        # Always show global avatar info
        embed.add_field(
            name='Global Avatar',
            value=f"[PNG]({global_avatar.url}) | [JPG]({global_avatar.replace(format='jpg').url}) | [WEBP]({global_avatar.replace(format='webp').url})",
            inline=False,
        )

        # If no server avatar, use global avatar as embed image
        if not server_avatar:
            embed.set_image(url=global_avatar.url)

        # Add some user information
        embed.set_footer(text=f'User ID: {target_user.id}')

        await ctx.respond(embed=embed)
        ctxlogger.success('Sent avatar successfully')

    @commands.slash_command(
        name='server_info',
        description='Display detailed information about the current server',
    )
    async def server_info(self, ctx: discord.ApplicationContext):
        ctxlogger = get_context_logger(ctx)
        ctxlogger.info(f'{ctx.author.name} used command server_info')
        guild = ctx.guild

        # Get various member counts
        total_members = guild.member_count
        bot_count = len([m for m in guild.members if m.bot])
        human_count = total_members - bot_count
        online_count = len([m for m in guild.members if m.status != discord.Status.offline])

        # Get channel counts
        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        categories = len(guild.categories)

        # Get role information
        role_count = len(guild.roles) - 1  # Subtract @everyone role

        # Create timestamp for server creation
        created_at = int(guild.created_at.timestamp())

        # Get boost information
        boost_level = guild.premium_tier
        boost_count = guild.premium_subscription_count

        # Create embed
        embed = discord.Embed(
            title=f'{guild.name} Server Information',
            description=f'📋 **Server ID:** {guild.id}',
            color=discord.Color.blue(),
            timestamp=datetime.now(),
        )

        # Set server icon as thumbnail if it exists
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        # Add server owner field
        embed.add_field(
            name='👑 Owner',
            value=f'{guild.owner.mention} ({guild.owner.id})',
            inline=False,
        )

        # Member statistics
        embed.add_field(
            name='👥 Members',
            value=f'Total: {total_members:,}\n'
            f'Humans: {human_count:,}\n'
            f'Bots: {bot_count:,}\n'
            f'Online: {online_count:,}',
            inline=True,
        )

        # Channel statistics
        embed.add_field(
            name='📊 Channels',
            value=f'Categories: {categories}\n'
            f'Text: {text_channels}\n'
            f'Voice: {voice_channels}\n'
            f'Total: {text_channels + voice_channels}',
            inline=True,
        )

        # Server features
        features_list = [feature.replace('_', ' ').title() for feature in guild.features]
        if features_list:
            embed.add_field(
                name='✨ Features',
                value=(
                    '\n'.join(features_list)
                    if len(features_list) < 10
                    else f"{', '.join(features_list[:9])} and {len(features_list)-9} more..."
                ),
                inline=False,
            )

        # Boost status
        embed.add_field(
            name='🚀 Server Boost Status',
            value=f'Level: {boost_level}\n' f'Boosts: {boost_count}',
            inline=True,
        )

        # Additional information
        embed.add_field(
            name='📝 Additional Information',
            value=f'Roles: {role_count}\n'
            f'Emojis: {len(guild.emojis)}/{guild.emoji_limit}\n'
            f'Stickers: {len(guild.stickers)}/{guild.sticker_limit}\n'
            f'Verification Level: {str(guild.verification_level).title()}',
            inline=True,
        )

        # Add server creation date
        embed.set_footer(text=f'Server Created: <t:{created_at}:D>')

        await ctx.respond(embed=embed)
        ctxlogger.success('Sent the server info embed successfully')


def setup(bot):
    bot.add_cog(Miscellaneous(bot))
