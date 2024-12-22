import asyncio

import discord
from discord.ext import commands

from utils.logger import log


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def ensure_role(self, ctx, role_name, color):
        role = discord.utils.get(ctx.guild.roles, name=role_name)
        if role is None:
            role = await ctx.guild.create_role(
                name=role_name,
                permissions=discord.Permissions.none(),
                color=color,
                hoist=True,
            )
        return role

    async def cog_check(self, ctx: discord.ApplicationContext):
        """Global check to ensure only administrators can use commands in this Cog."""
        if not ctx.author.guild_permissions.administrator:
            with log.contextualize(
                user=ctx.author.name, channel=ctx.channel.name, server=ctx.guild.name
            ):
                log.warning(
                    f"User {ctx.author.name} tried to use an admin-only command without proper permissions."
                )

            await ctx.respond(
                "You do not have the permissions to use this command.",
                ephemeral=True,
            )
            return False
        return True

    @commands.slash_command(
        name="assign_bots",
        description="Assign the 'bot' role to all bots in the server",
    )
    async def assign_bots(self, ctx: discord.ApplicationContext):
        with log.contextualize(
            user=ctx.author.name, channel=ctx.channel.name, server=ctx.guild.name
        ):
            await ctx.respond("Assigning bots...")
            log.info("Got assign_bots command")

            # Ensure the 'bot' role exists or create it
            bot_role = await self.ensure_role(ctx, "bot", discord.Color(0xCC967A))
            if not bot_role:
                await ctx.followup.send("Failed to create or find the 'bot' role.")
                return

            # Check permissions
            if not ctx.guild.me.guild_permissions.manage_roles:
                log.warning("Not enough permissions to manage roles.")
                await ctx.followup.send("I do not have permission to manage roles.")
                return

            if ctx.guild.me.top_role <= bot_role:
                log.error(
                    "My highest role is not high enough in the role hierarchy to assign the 'bot' role."
                )
                await ctx.followup.send(
                    "My highest role is not high enough in the role hierarchy to assign the 'bot' role."
                )
                return

            # Assign roles to bot members
            count = 0
            tasks = []
            for member in ctx.guild.members:
                if member.bot and bot_role not in member.roles:
                    tasks.append(member.add_roles(bot_role))

            try:
                await asyncio.gather(*tasks)
                count = len(tasks)
            except Exception as e:
                log.error(f"Error assigning roles: {e}")
                await ctx.followup.send("An error occurred while assigning bot roles.")
                return

            # Respond with the result
            await ctx.followup.send(f"Assigned the 'bot' role to {count} bots.")

    @commands.slash_command(
        name="assign_members",
        description="Assign the 'member' role to all non-bot members in the server",
    )
    async def assign_members(self, ctx: discord.ApplicationContext):
        with log.contextualize(
            user=ctx.author.name, channel=ctx.channel.name, server=ctx.guild.name
        ):
            log.info("Got assign_members command")
            await ctx.respond("Assigning Members...")

            member_role = await self.ensure_role(ctx, "member", discord.Color(0x1ABC9C))
            if not member_role:
                await ctx.followup.send("Failed to create or find the 'member' role.")
                return

            if not ctx.guild.me.guild_permissions.manage_roles:
                await ctx.followup.send("I do not have permission to manage roles.")
                return

            if ctx.guild.me.top_role <= member_role:
                log.error(
                    "My highest role is not high enough in the role hierarchy to assign the 'member' role."
                )
                await ctx.followup.send(
                    "My highest role is not high enough in the role hierarchy to assign the 'member' role."
                )
                return

            count = 0
            tasks = []

            for member in ctx.guild.members:
                if not member.bot and member_role not in member.roles:
                    tasks.append(member.add_roles(member_role))

            try:
                await asyncio.gather(*tasks)
                count = len(tasks)
            except Exception as e:
                log.error(f"Errror in assigning roles: {e}")
                await ctx.followup.send(
                    "An error occurred while assigning member roles."
                )

            await ctx.followup.send(f"Assigned the 'member' role to {count} members.")

    @commands.slash_command(
        name="clear_chat", description="sends a long empty message to clear the chat"
    )
    # should send a long empty message to clear the chat (not deleting messages)
    async def clear_chat(self, ctx: discord.ApplicationContext):
        with log.contextualize(
            user=ctx.author.name, channel=ctx.channel.name, server=ctx.guild.name
        ):
            log.info("Got clear_chat command")
        await ctx.defer()

        if not ctx.guild.me.guild_permissions.manage_messages:
            await ctx.followup.send("I do not have permission to manage messages.")
            return

        await ctx.followup.send("." + "\n" * 50 + ".")

    @commands.slash_command(
        name="delete_user_messages",
        description="Delete a specified number of messages from a user in a specific channel",
    )
    async def delete_user_messages(
        self,
        ctx: discord.ApplicationContext,
        username: str,
        channel: discord.TextChannel,
        message_count: int,
    ):
        with log.contextualize(
            user=ctx.author.name, channel=ctx.channel.name, server=ctx.guild.name
        ):
            log.info(f"Got delete_user_messages command for {username}")
        await ctx.defer()

        # Check permissions
        if not ctx.guild.me.guild_permissions.manage_messages:
            await ctx.followup.send("I do not have permission to manage messages.")
            return

        # Find the user
        member = discord.utils.find(
            lambda m: m.name == username or m.display_name == username,
            ctx.guild.members,
        )
        if not member:
            await ctx.followup.send(f"User '{username}' not found in this server.")
            return

        # Fetch messages and delete
        deleted_count = 0
        async for message in channel.history(limit=1000):
            if message.author == member:
                await message.delete()
                deleted_count += 1
                if deleted_count >= message_count:
                    break

        await ctx.followup.send(
            f"Deleted {deleted_count} messages from {username} in {channel.mention}."
        )

    @commands.slash_command(
        name="delete_messages",
        description="Delete the N latest messages in the current channel",
    )
    async def delete_messages(
        self, ctx: discord.ApplicationContext, message_count: int
    ):
        with log.contextualize(
            user=ctx.author.name, channel=ctx.channel.name, server=ctx.guild.name
        ):
            log.info("Got delete_messages command ")
            log.info(f"deleting {message_count} messages")

        await ctx.defer()

        # Check permissions
        if not ctx.guild.me.guild_permissions.manage_messages:
            await ctx.followup.send("I do not have permission to manage messages.")
            return

        # Ensure the message count is valid
        if message_count < 1:
            await ctx.followup.send(
                "Please provide a valid number of messages to delete."
            )
            return

        # Fetch and delete the messages
        deleted_count = 0
        async for message in ctx.channel.history(limit=message_count + 1):
            await message.delete()
            log.debug(f"deleting message : {message.content}")
            deleted_count += 1

        await ctx.send(
            f"Deleted {deleted_count-1} messages in {ctx.channel.mention}.",
        )


def setup(bot):
    bot.add_cog(Moderation(bot))
