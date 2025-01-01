import discord
from discord.ext import commands
from discord.ui import Button, View


class HelpDropdown(discord.ui.Select):
    def __init__(self, bot):
        self.bot = bot
        options = [
            discord.SelectOption(label='General', description='General bot commands'),
            discord.SelectOption(label='Moderation', description='Moderation commands'),
            discord.SelectOption(label='Music-YT', description='Youtube Music commands'),
            discord.SelectOption(label='Playlists', description='Playlist commands'),
            discord.SelectOption(label='Smashorpass', description='Smashorpass commands'),
            discord.SelectOption(label='Music-Local', description='Local Music commands'),
            discord.SelectOption(label='Utils', description='Utility commands'),
            # discord.SelectOption(label="", description=""),
        ]
        super().__init__(placeholder='Choose a category', options=options)

    async def callback(self, interaction: discord.Interaction):
        # Handle dropdown selection
        category = self.values[0]
        embed = discord.Embed(title=f'{category} Commands', color=discord.Color.blue())

        # Customize this section to populate commands dynamically
        if category == 'General':
            embed.add_field(name='/help', value='Displays the help menu', inline=False)
        elif category == 'Moderation':
            embed.add_field(
                name='/assign_bots',
                value='Add the bot role to all bots in the server',
                inline=False,
            )
            embed.add_field(
                name='/assign_members',
                value='Add the member role to all the members in the server',
                inline=False,
            )
            embed.add_field(
                name='/clear_chat',
                value='Send an empty message to clear the chat',
                inline=False,
            )
            embed.add_field(
                name='/delete_user_messages',
                value='Delete messages by the specified user in a particular channel',
                inline=False,
            )
            embed.add_field(
                name='/delete_messages',
                value='Delete latest messages in the current channel',
                inline=False,
            )

        elif category == 'Music-YT':
            embed.add_field(
                name='/play_music',
                value='Play music in your voice channel',
                inline=False,
            )
            embed.add_field(
                name='/play_playlist',
                value='Add a saved playlist to queue',
                inline=False,
            )
            embed.add_field(
                name='/play_playlist_yt',
                value='Play all songs from a Youtube playlist URL',
                inline=False,
            )
            embed.add_field(
                name='/add_to_queue',
                value='Add a song to the end of the queue',
                inline=False,
            )
            embed.add_field(
                name='/play_next',
                value='Add a song to play immediately after the current one',
                inline=False,
            )
            embed.add_field(
                name='/remove',
                value='Remove a song in the queue by its position',
                inline=False,
            )
            embed.add_field(name='/skip', value='Skip the current song', inline=False)
            embed.add_field(
                name='/skip_multiple',
                value='Skip multiple songs (best used with display_queue)',
                inline=False,
            )
            embed.add_field(
                name='/jump',
                value='Jump to a particular song in the queue (best used with display_queue_long)',
                inline=False,
            )
            embed.add_field(
                name='/nowplaying',
                value='Display the currently playing song',
                inline=False,
            )
            embed.add_field(
                name='/seek',
                value='Seek to a specific timestamp in the current song (format=mm:ss)',
                inline=False,
            )
            embed.add_field(
                name='/lyrics_from_genius',
                value='Fetch the lyrics for the specified song',
                inline=False,
            )
            embed.add_field(
                name='/save_queue',
                value='Save the songs in the current queue to a playlist',
                inline=False,
            )
            embed.add_field(
                name='/display_queue_long',
                value='Display the entire queue',
                inline=False,
            )
            embed.add_field(
                name='/display_queue',
                value='Display the next 10 songs in queue',
                inline=False,
            )
            embed.add_field(
                name='/display_temp_queue',
                value='Display the songs waiting to be loaded in queue',
                inline=False,
            )
            embed.add_field(
                name='/queueinfo',
                value='Display analytics about the current queue',
                inline=False,
            )
            embed.add_field(
                name='/suggest',
                value='Suggest songs similar to the current one',
                inline=False,
            )
            embed.add_field(
                name='/load_songs',
                value='Load songs from the temporary queue to main queue (max 10)',
                inline=False,
            )
            embed.add_field(
                name='/past_songs',
                value='Display the previously played songs',
                inline=False,
            )
            embed.add_field(name='/previous', value='Play the previous song', inline=False)
            embed.add_field(
                name='pause and resume',
                value='/pause Pauses the music playback\n/resume Resumes the music playback',
                inline=False,
            )
            embed.add_field(
                name='/stop',
                value='Stop the music, clear the queue, and disconnect the bot from the voice channel',
                inline=False,
            )
            embed.add_field(name='/shuffle', value='Shuffle the queue', inline=False)
            embed.add_field(
                name='Looping',
                value='/loop_once Loops the current song\n/loop_all Loops the entire queue\n/loop_off Turns off looping',
                inline=False,
            )
        elif category == 'Playlists':
            embed.add_field(
                name='/available_playlists',
                value='Show the available playlist',
                inline=False,
            )
            embed.add_field(
                name='/create_playlist',
                value='Create a new empty playlist',
                inline=False,
            )
            embed.add_field(
                name='/show_playlist',
                value='Show the songs in the specified playlist',
                inline=False,
            )
            embed.add_field(
                name='/add_song_to_playlist',
                value='Add song to an existing playlist',
                inline=False,
            )
            embed.add_field(
                name='/save_queue',
                value='Save all the songs in the current queue to a playlist',
                inline=False,
            )
            embed.add_field(
                name='/play_playlist',
                value='Play the specified playlist in your voice channel',
                inline=False,
            )
        elif category == 'Smashorpass':
            embed.add_field(
                name='/smashorpass',
                value='Play a game of smash or pass with valorant skins in a new thread',
                inline=False,
            )
        elif category == 'Utils':
            embed.add_field(name='/ping', value='Return bot latency', inline=False)
            embed.add_field(name='/reboot', value='Reboot the bot (Owner only)', inline=False)
        elif category == 'Music-Local':
            embed.add_field(name='/play_music-local', value='Play a local music file', inline=False)
            embed.add_field(
                name='/add_to_queue-local',
                value='Add a local music file to the queue',
                inline=False,
            )
            embed.add_field(
                name='/play_playlist-local',
                value='Play all audio files in the specified folder',
                inline=False,
            )
            embed.add_field(
                name='/nowplaying-local',
                value='Display the currently playing local music file',
                inline=False,
            )
            embed.add_field(
                name='/display_queue_long-local',
                value='Display the entire local queue',
                inline=False,
            )
            embed.add_field(
                name='/display_queue-local',
                value='Display the next 10 songs in local queue',
                inline=False,
            )
            embed.add_field(
                name='/lyrics_from_file-local',
                value='Fetch the lyrics from the currently playing music file',
                inline=False,
            )
            embed.add_field(
                name='/past_songs-local',
                value='Show the previously played local music files',
                inline=False,
            )
            embed.add_field(
                name='/previous-local',
                value='Play the previous local music file',
                inline=False,
            )
            embed.add_field(name='/skip-local', value='Skip the current song', inline=False)
            embed.add_field(name='/pause-local', value='Pause the current song', inline=False)
            embed.add_field(name='/resume-local', value='Resume the paused song', inline=False)
            embed.add_field(
                name='/stop-local',
                value='Stop the music and clear the local music queue',
                inline=False,
            )
            embed.add_field(
                name='/shuffle-local',
                value='Shuffle the local music queue',
                inline=False,
            )
            embed.add_field(
                name='/loop_once-local',
                value='Loop the currently playing music file',
                inline=False,
            )
            embed.add_field(
                name='/loop_all-local',
                value='Loop the entire local music queue',
                inline=False,
            )
            embed.add_field(
                name='/loop_off-local',
                value='Turn off looping for the local music queue',
                inline=False,
            )

        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpView(View):
    def __init__(self, bot):
        super().__init__()
        self.add_item(HelpDropdown(bot))

        # Add buttons for extra functionality
        self.add_item(
            Button(
                label='Invite Bot',
                url='https://your.bot/invite',
                style=discord.ButtonStyle.link,
            )
        )
        self.add_item(
            Button(
                label='Support Server',
                url='https://discord.gg/AasT54aFVN',
                style=discord.ButtonStyle.link,
            )
        )


class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(description='Shows the help menu')
    async def help(self, ctx: discord.ApplicationContext):
        embed = discord.Embed(
            title='Bot Help',
            description='Choose a category to see available commands or use the buttons below for more options.',
            color=discord.Color.green(),
        )
        embed.set_thumbnail(url='https://your.bot/logo.png')  # Replace with your bot's logo URL
        embed.set_footer(text='Your Bot Name | Help Menu')

        view = HelpView(self.bot)
        await ctx.respond(embed=embed, view=view)


# Add this cog to your bot
def setup(bot):
    bot.add_cog(HelpCog(bot))
