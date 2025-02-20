import asyncio
import math
import os
import random
import re
import time
import tomllib
import traceback

import discord
import requests

# import spotipy
from discord.ext import commands
from mutagen.id3 import ID3
from mutagen.mp3 import MP3
from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials

from utils.logger import get_context_logger, log
from validators.config import ConfigValidator

# from typing import Tuple


cookies_path = os.path.abspath('cookies/cookies.txt')
# print(f"Cookies Path: {cookies_path}")
# print(f"File Exists: {os.path.exists(cookies_path)}")


with open(os.path.join('config.toml'), 'rb') as f:
    data = tomllib.load(f)
arle_config: ConfigValidator = ConfigValidator.model_validate(data)

youtube_api_key = arle_config.secrets.youtube_api_key

# log.info(f"youtube_api_key: {youtube_api_key}")


def truncate_field_value(value: str, limit: int = 1024) -> str:
    """Truncate a field value to fit Discord's limits"""
    if len(value) <= limit:
        return value
    return value[: limit - 3] + '...'


def format_duration(duration: int):
    # Format duration as minutes:seconds
    minutes = duration // 60
    seconds = duration % 60
    duration_str = f'{minutes}:{seconds:02d}'
    return duration_str


async def get_playlist_tracks_async(
    playlist_url: str, client_id: str, client_secret: str
) -> list[str]:
    """
    Extract tracks from a public Spotify playlist asynchronously using client credentials
    Returns list of tracks in 'song_name artist_name' format
    """
    # Initialize Spotify client with client credentials
    auth_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
    sp = Spotify(auth_manager=auth_manager)

    if 'spotify.com' in playlist_url:
        playlist_id = playlist_url.split('/')[-1].split('?')[0]
    else:
        playlist_id = playlist_url

    playlist_tracks = []
    try:
        results = sp.playlist_tracks(playlist_id)
        while results:
            for item in results['items']:
                if item['track']:
                    track = item['track']
                    artist_name = track['artists'][0]['name'] if track['artists'] else ''
                    track_info = f"{track['name']} {artist_name}"
                    # Clean the track info
                    track_info = ''.join(e for e in track_info if e.isalnum() or e.isspace())
                    track_info = ''.join([i if ord(i) < 128 else ' ' for i in track_info])
                    playlist_tracks.append(track_info)

            if results['next']:
                results = sp.next(results)
            else:
                results = None

        return playlist_tracks
    except Exception as e:
        raise Exception(f'Error fetching Spotify playlist: {str(e)}')


class PlaylistView(discord.ui.View):
    def __init__(self, folder_data, songs_per_page=10):
        super().__init__(timeout=60)
        self.folder_data = folder_data
        self.current_page = 0
        self.songs_per_page = songs_per_page
        self.total_pages = math.ceil(len(folder_data['files']) / songs_per_page)
        self.update_buttons()

    def update_buttons(self):
        self.previous_page.disabled = self.current_page == 0
        self.next_page.disabled = self.current_page >= self.total_pages - 1

    def get_embed(self):
        start_idx = self.current_page * self.songs_per_page
        end_idx = start_idx + self.songs_per_page
        current_files = self.folder_data['files'][start_idx:end_idx]

        embed = discord.Embed(
            title=f"📂 Contents of {self.folder_data['name']}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )

        # Add folder summary
        embed.add_field(
            name='📊 Folder Summary',
            value=f"**Total Songs:** {len(self.folder_data['files'])}\n"
            f"**Total Duration:** {format_duration(self.folder_data['total_duration'])}\n"
            f"**Total Size:** {self.folder_data['total_size']:.1f}MB",
            inline=False,
        )

        # Add current page songs
        songs_description = []
        for i, (filename, title, duration, size, artist) in enumerate(
            current_files, start=start_idx + 1
        ):
            song_info = f'`{i}.` **{title}**'
            if artist:
                song_info += f' - {artist}'
            song_info += f'\n┗ Duration: {format_duration(duration)} • Size: {size:.1f}MB'
            songs_description.append(song_info)

        if songs_description:
            embed.add_field(name='📋 Songs', value='\n'.join(songs_description), inline=False)
        else:
            embed.add_field(name='📋 Songs', value='No songs in this page', inline=False)

        # Add page information
        footer_text = (
            f"Page {self.current_page + 1}/{self.total_pages} • "
            f"Showing songs {start_idx + 1}-{min(end_idx, len(self.folder_data['files']))} "
            f"of {len(self.folder_data['files'])}"
        )
        embed.set_footer(text=footer_text)

        return embed

    @discord.ui.button(label='Previous', style=discord.ButtonStyle.grey, emoji='⬅️')
    async def previous_page(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.current_page = max(0, self.current_page - 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label='Next', style=discord.ButtonStyle.grey, emoji='➡️')
    async def next_page(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except Exception:
            pass


class QueueView(discord.ui.View):
    def __init__(self, queue_data, songs_per_page=10):
        super().__init__(timeout=60)  # 60 seconds timeout
        self.queue_data = queue_data
        self.current_page = 0
        self.songs_per_page = songs_per_page
        self.total_pages = math.ceil(len(queue_data['queue']) / songs_per_page)

        # Update button states
        self.update_buttons()

    def update_buttons(self):
        # Disable/Enable previous button
        self.previous_page.disabled = self.current_page == 0
        # Disable/Enable next button
        self.next_page.disabled = self.current_page >= self.total_pages - 1

    def get_embed(self):
        start_idx = self.current_page * self.songs_per_page
        end_idx = start_idx + self.songs_per_page
        current_songs = self.queue_data['queue'][start_idx:end_idx]
        current_index = self.queue_data['current_index']

        embed = discord.Embed(
            title='🎵 Queue',
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )

        description = []
        for i, song in enumerate(current_songs, start=start_idx):
            _, title, duration = song
            line = f'`{i + 1}.` ({format_duration(duration)}) | {title}'
            if i == current_index:
                line += ' ▶️'
            description.append(line)

        if description:
            embed.description = '\n'.join(description)
        else:
            embed.description = 'No songs in this page'

        # Add queue information
        total_songs = len(self.queue_data['queue'])
        total_duration = sum(song[2] for song in self.queue_data['queue'])

        embed.add_field(
            name='Queue Info',
            value=f'**Total Songs:** {total_songs}\n**Total Duration:** {format_duration(total_duration)}',
            inline=False,
        )

        footer_text = (
            f'Currently Playing: {current_index + 1}/{total_songs} • '
            f'Page {self.current_page + 1}/{self.total_pages} • '
            f'Showing songs {start_idx + 1}-{min(end_idx, total_songs)} of {total_songs}'
        )

        # Add page information
        embed.set_footer(text=footer_text)

        return embed

    @discord.ui.button(label='Previous', style=discord.ButtonStyle.grey, emoji='⬅️')
    async def previous_page(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.current_page = max(0, self.current_page - 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label='Next', style=discord.ButtonStyle.grey, emoji='➡️')
    async def next_page(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def on_timeout(self):
        # Disable all buttons when the view times out
        for item in self.children:
            item.disabled = True
        # Try to update the message with disabled buttons
        try:
            await self.message.edit(view=self)
        except Exception:
            pass


class MusicQueue:
    def __init__(self):
        self.queues = {}  # Dictionary to store queues for each server

    def get_queue(self, guild_id):
        if guild_id not in self.queues:
            self.queues[guild_id] = {
                'queue': [],
                'current_index': -1,
            }
        return self.queues[guild_id]

    def add_song(self, guild_id, song_tuple):
        queue_data = self.get_queue(guild_id)
        queue_data['queue'].append(song_tuple)
        if queue_data['current_index'] == -1:
            queue_data['current_index'] = 0

    def add_to_temp_queue(self, guild_id, songs):
        queue_data = self.get_queue(guild_id)
        queue_data['temp_queue'].extend(songs)

    def get_temp_queue_size(self, guild_id):
        queue_data = self.get_queue(guild_id)
        return len(queue_data['temp_queue'])

    def get_next_temp_songs(self, guild_id, count):
        queue_data = self.get_queue(guild_id)
        songs = queue_data['temp_queue'][:count]
        queue_data['temp_queue'] = queue_data['temp_queue'][count:]
        return songs

    def get_loaded_songs(self, guild_id):
        queue_data = self.get_queue(guild_id)
        return [(i + 1, song[1], song[2]) for i, song in enumerate(queue_data['queue'])]

    def get_temp_queue_songs(self, guild_id):
        queue_data = self.get_queue(guild_id)
        return [(i + 1, song) for i, song in enumerate(queue_data['temp_queue'])]

    def current_song(self, guild_id):
        queue_data = self.get_queue(guild_id)
        if queue_data['current_index'] != -1:
            return queue_data['queue'][queue_data['current_index']]
        return None

    def next_song(self, guild_id):
        queue_data = self.get_queue(guild_id)
        if (
            queue_data['current_index'] != -1
            and queue_data['current_index'] < len(queue_data['queue']) - 1
        ):
            queue_data['current_index'] += 1
            return queue_data['queue'][queue_data['current_index']]
        return None

    def previous_song(self, guild_id):
        queue_data = self.get_queue(guild_id)
        if queue_data['current_index'] > 0:
            queue_data['current_index'] -= 1
            return queue_data['queue'][queue_data['current_index']]
        return None

    def remove_current_song(self, guild_id):
        queue_data = self.get_queue(guild_id)
        if queue_data['current_index'] != -1:
            removed_song = queue_data['queue'].pop(queue_data['current_index'])
            if queue_data['current_index'] >= len(queue_data['queue']):
                queue_data['current_index'] = len(queue_data['queue']) - 1
            return removed_song
        return None


class MusicLocal(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = MusicQueue()
        self.loop_types = {}  # Keep this for loop functionality
        self.twenty_four_seven = {}  # Keep this if you want 24/7 playback
        self.playback_times = {}

        self.FFMPEG_OPTIONS = {
            'options': '-vn -af "aresample=44100:filter_size=64:phase_shift=8"',
        }

        self.music_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 'music'
        )  # Directory for music files

    def get_loop_type(self, guild_id):
        return self.loop_types.get(guild_id)

    def set_loop_type(self, guild_id, loop_type):
        self.loop_types[guild_id] = loop_type

    def get_current_song(self, guild_id):
        """Get current song for specific server"""
        return self.queue.current_song(guild_id)

    def get_audio_info(self, file_path):
        """Get audio file information"""
        try:
            audio = MP3(file_path)
            duration = int(audio.info.length)

            # Try to get title from ID3 tags
            try:
                tags = ID3(file_path)
                title = tags.get('TIT2', os.path.basename(file_path))
            except Exception:
                # If no ID3 tags, use filename as title
                title = os.path.basename(file_path)

            return file_path, title, duration
        except Exception as e:
            log.error(f'Error getting audio info: {e}')
            return None, None, None

    async def play_audio(self, ctx, file_path, title, duration, after=None):
        """Helper function to handle local audio playback"""
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info("Function 'play_audio' invoked.")

        try:
            if not os.path.exists(file_path):
                ctxlog.error(f'Audio file not found: {file_path}')
                return False

            if ctx.voice_client:
                ctx.voice_client.play(
                    discord.FFmpegPCMAudio(file_path, **self.FFMPEG_OPTIONS),
                    after=after,
                )

                self.playback_times[guild_id] = time.time()
                ctxlog.success(f'Started playing: {title}')
                return True

        except Exception as e:
            ctxlog.error(f'Playback error: {e}')
            traceback.print_exc()  # This will help debug any FFmpeg-related issues

        return False

    async def play_next_song(self, ctx):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.debug('play_next_song called')

        if hasattr(self, 'seeking') and guild_id in self.seeking:
            ctxlog.debug('Skipping play_next_song due to seek operation.')
            return

        try:
            # Determine next song based on loop settings
            current_song = None
            queue_data = None
            if self.get_current_song(guild_id):
                queue_data = self.queue.get_queue(guild_id)
                loop_type = self.get_loop_type(guild_id)

                if (
                    loop_type == 'all'
                    and queue_data['current_index'] == len(queue_data['queue']) - 1
                ):
                    queue_data['current_index'] = 0
                    current_song = self.get_current_song(guild_id)
                elif loop_type == 'once':
                    current_song = self.get_current_song(guild_id)
                else:
                    current_song = self.queue.next_song(guild_id)

            if current_song and ctx.voice_client:
                ctxlog.info(f'Current song from play_next_song: {current_song}')
                file_path, title, duration = current_song

                # Verify file still exists
                if not os.path.exists(file_path):
                    ctxlog.error(f'Audio file not found: {file_path}')
                    await ctx.send('Failed to play the current song (file not found), skipping...')
                    await self.play_next_song(ctx)
                    return

                # Check if voice channel is empty
                voice_channel = ctx.voice_client.channel
                member_count = len([m for m in voice_channel.members if not m.bot])

                if member_count == 0 and not self.twenty_four_seven.get(guild_id, False):
                    ctxlog.info(f'No users in voice channel for guild {guild_id}, disconnecting.')
                    await self._cleanup_guild(ctx, guild_id)
                    await ctx.voice_client.disconnect()
                    return

                if ctx.voice_client.is_connected():
                    success = await self.play_audio(
                        ctx,
                        file_path,
                        title,
                        duration,
                        after=lambda e: self.bot.loop.create_task(self.play_next_song(ctx)),
                    )

                    if success:
                        await ctx.send(f'Now playing: {title} ({format_duration(duration)})')
                        try:
                            if voice_channel:
                                await voice_channel.set_status(status=f'▶️ {title}')
                        except Exception as status_error:
                            ctxlog.warning(f'Could not update status: {status_error}')
                    else:
                        await ctx.send('Failed to play the current song, skipping...')
                        await self.play_next_song(ctx)
                else:
                    ctxlog.warning(f'Voice client disconnected in guild {guild_id}')
                    return

            else:
                if ctx.voice_client and not ctx.voice_client.is_playing():
                    await self._cleanup_guild(ctx, guild_id)
                    if ctx.voice_client:
                        await ctx.voice_client.disconnect()

        except Exception as e:
            ctxlog.error(f'Error in play_next_song: {e}')
            ctxlog.error(traceback.format_exc())
            await self._cleanup_guild(ctx, guild_id)
            if ctx.voice_client:
                await ctx.voice_client.disconnect()

    async def _cleanup_guild(self, ctx, guild_id):
        """Helper method to clean up guild-specific states"""
        queue_data = self.queue.get_queue(guild_id)
        queue_data['queue'] = []
        queue_data['current_index'] = -1

        if guild_id in self.loop_types:
            del self.loop_types[guild_id]
        if guild_id in self.playback_times:
            del self.playback_times[guild_id]

    @commands.slash_command(
        name='play_music',
        description='Play music from local files in your voice channel.',
    )
    async def play_music(self, ctx: discord.ApplicationContext, filename: str):
        """
        Play music in the voice channel from local files.
        Parameters:
            ctx: The command context
            filename: The path to the audio file
        """
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} requested to play: {filename}')

        await ctx.defer()

        try:
            # Check if user is in a voice channel
            if ctx.author.voice is None:
                ctxlog.warning(
                    f'{ctx.author.name} attempted to call play_music without joining a voice channel.'
                )
                await ctx.respond('You need to join a voice channel first!')
                return

            voice_channel = ctx.author.voice.channel

            # Check if bot has necessary permissions
            permissions = voice_channel.permissions_for(ctx.guild.me)
            if not permissions.connect or not permissions.speak:
                await ctx.respond(
                    "I don't have permission to join and speak in your voice channel!"
                )
                ctxlog.warning(f'Missing permissions for voice channel in guild {guild_id}')
                return

            # Verify file exists and get audio information
            file_path = os.path.join(self.music_dir, filename)  # Use absolute path
            if not os.path.exists(file_path):
                await ctx.respond(f"File '{filename}' not found in music directory.")
                ctxlog.warning(f'File not found: {file_path}')
                return

            # Get audio information
            audio_info = self.get_audio_info(file_path)
            if not audio_info:
                await ctx.respond(f"Failed to read audio file '{filename}'.")
                return

            file_path, title, duration = audio_info
            duration_str = format_duration(duration)

            # Add the song to the server's queue
            self.queue.add_song(guild_id, (file_path, title, duration))
            await ctx.respond(f'Added {title} ({duration_str}) to the queue.')
            ctxlog.info(f'Added {title} to the queue for guild {guild_id}')

            # Handle voice client connection
            try:
                if ctx.voice_client is None:
                    await voice_channel.connect()
                    await asyncio.sleep(0.5)  # Small delay to ensure connection is stable
                    if guild_id in self.twenty_four_seven:
                        self.twenty_four_seven[guild_id] = True
                    ctxlog.info(f'Connected to voice channel in guild {guild_id}')

                elif ctx.voice_client.channel != voice_channel:
                    await ctx.voice_client.move_to(voice_channel)
                    await asyncio.sleep(0.5)
                    ctxlog.info(f'Moved to different voice channel in guild {guild_id}')

            except Exception as e:
                ctxlog.error(f'Error connecting to voice channel: {e}')
                await ctx.send('Error connecting to voice channel. Please try again.')
                return

            # Start playing if nothing is currently playing
            if not ctx.voice_client.is_playing():
                try:
                    current_song = self.get_current_song(guild_id)
                    if current_song:
                        file_path, title, duration = current_song
                        success = await self.play_audio(
                            ctx,
                            file_path,
                            title,
                            duration,
                            after=lambda e: self.bot.loop.create_task(self.play_next_song(ctx)),
                        )

                        if success:
                            await ctx.send(f'Now playing: {title} ({format_duration(duration)})')
                            await voice_channel.set_status(status=f'▶️ {title}')
                            ctxlog.success(f'Started playing {title} in guild {guild_id}')
                        else:
                            await ctx.send('Failed to play the song. Skipping...')
                            await self.play_next_song(ctx)
                            ctxlog.warning(f'Failed to play {title} in guild {guild_id}')

                except Exception as e:
                    ctxlog.error(f'Error starting playback: {e}')
                    await self._cleanup_guild(ctx, guild_id)
                    if ctx.voice_client:
                        await ctx.voice_client.disconnect()
                    await ctx.send('An error occurred while trying to play the song.')

        except Exception as e:
            ctxlog.error(f'Unexpected error in play_music: {e}')
            ctxlog.error(traceback.format_exc())
            await ctx.send('An unexpected error occurred. Please try again later.')

            # Cleanup on critical error
            await self._cleanup_guild(ctx, guild_id)
            if ctx.voice_client:
                await ctx.voice_client.disconnect()

    @commands.slash_command(name='add_to_queue', description='Add a music file to the queue.')
    async def add_to_queue(self, ctx: discord.ApplicationContext, filename: str):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used add_to_queue command with file: {filename}')

        await ctx.defer()

        try:
            # Verify file exists and get audio information
            file_path = os.path.join(self.music_dir, filename)
            if not os.path.exists(file_path):
                await ctx.respond(f"File '{filename}' not found in music directory.")
                ctxlog.warning(f'File not found: {file_path}')
                return

            # Get audio information
            audio_info = self.get_audio_info(file_path)
            if not audio_info:
                await ctx.respond(f"Failed to read audio file '{filename}'.")
                return

            file_path, title, duration = audio_info
            self.queue.add_song(guild_id, (file_path, title, duration))
            await ctx.respond(f'Added {title} ({format_duration(duration)}) to the queue.')
            ctxlog.success(f'{title} added to queue by {ctx.author.name} in guild {guild_id}')

            if not ctx.voice_client or not ctx.voice_client.is_playing():
                ctxlog.warning(f'{ctx.author.name} added song to empty queue in guild {guild_id}')
                await self.play_next_song(ctx)

        except Exception as e:
            ctxlog.error(f'Error in add_to_queue: {e}')
            await ctx.respond('An error occurred while adding the song to the queue.')

    @commands.slash_command(name='skip', description='Skip the current song.')
    async def skip(self, ctx: discord.ApplicationContext):
        """The skip command remains largely unchanged as it doesn't deal directly with files"""
        guild_id = ctx.guild.id
        if guild_id in self.playback_times:
            del self.playback_times[guild_id]
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f"{ctx.author.name} used command 'skip' in guild {guild_id}")

        try:
            if ctx.voice_client is None or not ctx.voice_client.is_playing():
                await ctx.respond('No music playing to be skipped.')
                ctxlog.warning(f'Used skip command without music playback in guild {guild_id}')
                return

            current_song = self.get_current_song(guild_id)
            if current_song:
                current_title = current_song[1]

                ctxlog.info(f'Stopping current song in guild {guild_id}...')
                ctx.voice_client.stop()

                await ctx.respond(f'Skipped {current_title}')
                ctxlog.success(f'Skipped current song in guild {guild_id}')
            else:
                await ctx.respond('No song currently playing.')
                ctxlog.warning(f'No current song found in guild {guild_id}')

        except Exception as e:
            ctxlog.error(f'Error in skip command: {e}')
            await ctx.respond('An error occurred while trying to skip the song.')

    @commands.slash_command(name='nowplaying', description='Display the currently playing song.')
    async def nowplaying(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command nowplaying in guild {guild_id}')
        await ctx.defer()

        try:
            if not ctx.voice_client or not self.get_current_song(guild_id):
                await ctx.respond('No song is currently playing.')
                ctxlog.warning(f'No song playing currently in guild {guild_id}')
                return

            current_song = self.get_current_song(guild_id)
            if current_song:
                file_path, song_title, total_duration = current_song

                # Try to get additional metadata from the file
                try:
                    audio = ID3(file_path)
                    artist = audio.get('TPE1', ['Unknown Artist'])[0]
                    album = audio.get('TALB', ['Unknown Album'])[0]
                except Exception as e:
                    ctxlog.warning(f'Could not read ID3 tags: {e}')
                    artist = 'Unknown Artist'
                    album = 'Unknown Album'

                # Calculate current timestamp
                if guild_id in self.playback_times and ctx.voice_client.is_playing():
                    elapsed_time = int(time.time() - self.playback_times[guild_id])
                    current_timestamp = min(elapsed_time, total_duration)
                else:
                    current_timestamp = 0

                # Create embed for better presentation
                embed = discord.Embed(
                    title='🎵 Now Playing',
                    description=f'**{song_title}**\nby {artist}\nfrom {album}',
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow(),
                )

                # Add timestamp field
                embed.add_field(
                    name='Time',
                    value=f'`{format_duration(current_timestamp)}/{format_duration(total_duration)}`',
                    inline=False,
                )

                # Create progress bar
                bar_length = 20
                progress = current_timestamp / total_duration if total_duration > 0 else 0
                filled = int(bar_length * progress)
                progress_bar = '▰' * filled + '▱' * (bar_length - filled)

                embed.add_field(
                    name='Progress',
                    value=f'`{progress_bar}` {(progress * 100):.1f}%',
                    inline=False,
                )

                # Add file information
                file_size = os.path.getsize(file_path) / (1024 * 1024)  # Convert to MB
                embed.add_field(
                    name='File Info',
                    value=f'Size: {file_size:.1f} MB\nPath: {os.path.basename(file_path)}',
                    inline=False,
                )

                # Get loop status and create footer text
                loop_type = self.get_loop_type(guild_id)
                if loop_type == 'all':
                    footer_text = '🔁 Loop: ALL'
                elif loop_type == 'once':
                    footer_text = '🔂 Loop: ONCE'
                else:
                    footer_text = '➡️ Loop: OFF'

                embed.set_footer(text=footer_text)

                await ctx.respond(embed=embed)
                ctxlog.success(
                    f'Now playing {song_title} at {current_timestamp}/{total_duration} '
                    f'in guild {guild_id}'
                )
            else:
                ctxlog.error(
                    f"Could not find current song in function 'nowplaying' for guild {guild_id}"
                )
                await ctx.respond('Error retrieving current song information.')

        except Exception as e:
            ctxlog.error(f'Error in nowplaying command for guild {guild_id}: {e}')
            ctxlog.error(traceback.format_exc())
            await ctx.respond('An error occurred while getting the current song information.')

    @commands.slash_command(name='display_queue_long', description='Display the entire queue.')
    async def display_queue_long(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        await ctx.defer()
        ctxlog.info(f'{ctx.author.name} used display_queue_long command in guild {guild_id}')

        try:
            queue_data = self.queue.get_queue(guild_id)
            total_length = len(queue_data['queue'])

            if total_length == 0:
                await ctx.respond('The queue is currently empty.')
                ctxlog.warning(f'Queue is currently empty in guild {guild_id}')
                return

            # Create the view and get initial embed
            view = QueueView(queue_data)
            embed = view.get_embed()

            # Send the message
            message = await ctx.respond(embed=embed, view=view)

            # Store the message for timeout handling
            if isinstance(message, discord.Webhook):
                view.message = await message.fetch()
            else:
                view.message = message

            ctxlog.success(f'Queue displayed with pagination for guild {guild_id}')

        except Exception as e:
            ctxlog.error(f'Error in display_queue_long: {e}')
            ctxlog.error(traceback.format_exc())
            await ctx.respond('An error occurred while displaying the queue.')

    @commands.slash_command(name='past_songs', description='Display the previously played songs.')
    async def past_songs(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command past_songs.')

        queue_data = self.queue.get_queue(guild_id)
        if queue_data['current_index'] < 1:
            await ctx.respond('There are no past songs.')
            return

        try:
            past_songs = []
            for i in range(0, queue_data['current_index']):
                _, title, duration = queue_data['queue'][i]
                past_songs.append(f'{i+1}. {title} ({format_duration(duration)})')

            past_songs_text = '\n'.join(past_songs)

            if len(past_songs_text) > 2000:
                chunks = [
                    past_songs_text[i : i + 2000] for i in range(0, len(past_songs_text), 2000)
                ]
                for chunk in chunks:
                    await ctx.send(chunk)
                ctxlog.success('Past songs displayed with chunking.')
            else:
                embed = discord.Embed(
                    title='📜 Previously Played Songs',
                    description=past_songs_text,
                    color=discord.Color.blue(),
                )
                await ctx.respond(embed=embed)
                ctxlog.success('Past songs displayed without chunking.')

        except Exception as e:
            ctxlog.error(f'Error in past_songs: {e}')
            await ctx.respond('An error occurred while retrieving past songs.')

    @commands.slash_command(name='get_current_index', description='Get the current queue index.')
    async def get_current_index(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command get_current_index in guild {guild_id}')

        try:
            queue_data = self.queue.get_queue(guild_id)
            current_index = queue_data['current_index']
            total_songs = len(queue_data['queue'])

            embed = discord.Embed(
                title='📊 Queue Status',
                description=f'Current Position: {current_index + 1}/{total_songs}',
                color=discord.Color.blue(),
            )
            await ctx.respond(embed=embed)

        except Exception as e:
            ctxlog.error(f'Error in get_current_index: {e}')
            await ctx.respond('An error occurred while getting queue index.')

    @commands.slash_command(name='previous', description='Play the previous song.')
    async def previous(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command previous in guild {guild_id}')

        await ctx.defer()

        try:
            queue_data = self.queue.get_queue(guild_id)
            ctxlog.debug(f"Current index initially: {queue_data['current_index']}")

            if queue_data['current_index'] < 1:
                await ctx.respond('No previously played songs.')
                ctxlog.warning(f'No previous songs available in guild {guild_id}')
                return

            # Keep the existing index manipulation logic
            queue_data['current_index'] -= 2
            if queue_data['current_index'] == -1:
                queue_data['current_index'] = 0

            ctxlog.debug(f"Current index after manual update: {queue_data['current_index']}")

            # Get the song we're going back to
            previous_song = queue_data['queue'][queue_data['current_index']]
            _, title, _ = previous_song

            if ctx.voice_client and ctx.voice_client.is_playing():
                ctx.voice_client.stop()
                ctxlog.success(f'Current song stopped successfully in guild {guild_id}')
                await ctx.respond(f'Playing previous song: {title}')
            else:
                # If nothing is playing, start playback
                await self.play_next_song(ctx)
                await ctx.respond(f'Started playing previous song: {title}')

        except Exception as e:
            ctxlog.error(f'Error in previous command: {e}')
            await ctx.respond('An error occurred while trying to play the previous song.')

            # Keep the existing cleanup logic
            try:
                queue_data = self.queue.get_queue(guild_id)
                if queue_data['current_index'] < 0:
                    queue_data['current_index'] = 0
            except Exception as cleanup_error:
                ctxlog.error(f'Error during cleanup: {cleanup_error}')

    @commands.slash_command(name='pause', description='Pause the current song.')
    async def pause(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        if guild_id in self.playback_times:
            self.playback_times[guild_id] = self.playback_times[guild_id] - time.time()
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command pause in guild {guild_id}')

        try:
            if ctx.voice_client is None or not ctx.voice_client.is_playing():
                ctxlog.warning(f'No music playing in guild {guild_id}')
                await ctx.respond('No music playing.')
                return

            current_song = self.get_current_song(guild_id)
            if current_song:
                _, current_title, _ = current_song
                ctx.voice_client.pause()
                await ctx.respond(f'Paused: {current_title}')

                try:
                    voice_channel = ctx.author.voice.channel
                    await voice_channel.set_status(status=f'⏸️ {current_title}')
                except Exception as status_error:
                    ctxlog.warning(f'Could not update status: {status_error}')

                ctxlog.success(f'Paused music playback in guild {guild_id}: {current_title}')
            else:
                await ctx.respond('No music currently playing.')
                ctxlog.warning(f'No current song found in guild {guild_id}')

        except Exception as e:
            ctxlog.error(f'Error in pause command for guild {guild_id}: {e}')
            await ctx.respond('An error occurred while trying to pause the music.')

            try:
                if ctx.voice_client and ctx.voice_client.is_playing():
                    ctx.voice_client.pause()
                    ctxlog.info(f'Recovered pause state for guild {guild_id}')
            except Exception as recovery_error:
                ctxlog.error(f'Error during state recovery: {recovery_error}')

    @commands.slash_command(name='resume', description='Resume playing the paused song.')
    async def play(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        if guild_id in self.playback_times and isinstance(self.playback_times[guild_id], float):
            self.playback_times[guild_id] = time.time() + self.playback_times[guild_id]
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command resume in guild {guild_id}')

        try:
            if ctx.voice_client is None:
                await ctx.respond('No music queued.')
                ctxlog.warning(f'Tried using resume command for an empty queue in guild {guild_id}')
                return

            if ctx.voice_client.is_playing():
                current_song = self.get_current_song(guild_id)
                current_title = current_song[1] if current_song else 'Unknown'
                ctxlog.warning(
                    f'Tried using resume command while music playback is active in guild {guild_id}'
                    f' (Currently playing: {current_title})'
                )
                await ctx.respond(f'Music already playing: {current_title}')
                return

            if ctx.voice_client.is_paused():
                current_song = self.get_current_song(guild_id)
                if current_song:
                    _, current_title, duration = current_song

                    ctx.voice_client.resume()
                    await ctx.respond(
                        f'Resumed playing: {current_title} ({format_duration(duration)})'
                    )

                    try:
                        voice_channel = ctx.author.voice.channel
                        await voice_channel.set_status(status=f'▶️ {current_title}')
                    except Exception as status_error:
                        ctxlog.warning(f'Could not update status: {status_error}')

                    ctxlog.success(f'Resumed music playback in guild {guild_id}: {current_title}')
                else:
                    await ctx.respond('Error: No song information found.')
                    ctxlog.error(f'No current song information found for guild {guild_id}')
            else:
                queue_data = self.queue.get_queue(guild_id)
                if len(queue_data['queue']) > 0:
                    await ctx.respond('No song is paused. Use /play_music to start playing.')
                    ctxlog.warning(f'Queue exists but no song is paused in guild {guild_id}')
                else:
                    await ctx.respond('No music queued.')
                    ctxlog.warning(f'No music in queue for guild {guild_id}')

        except Exception as e:
            ctxlog.error(f'Error in resume command for guild {guild_id}: {e}')
            await ctx.respond('An error occurred while trying to resume the music.')

            try:
                if ctx.voice_client and ctx.voice_client.is_paused():
                    ctx.voice_client.resume()
                    ctxlog.info(f'Recovered resume state for guild {guild_id}')
            except Exception as recovery_error:
                ctxlog.error(f'Error during state recovery: {recovery_error}')

            try:
                queue_data = self.queue.get_queue(guild_id)
                if queue_data['current_index'] >= len(queue_data['queue']):
                    queue_data['current_index'] = len(queue_data['queue']) - 1
                    ctxlog.info(f'Recovered queue index state for guild {guild_id}')
            except Exception as queue_error:
                ctxlog.error(f'Error during queue state recovery: {queue_error}')

    @commands.slash_command(name='stop', description='Stop the music and clear the queue.')
    async def stop(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command stop in guild {guild_id}')

        try:
            # Get current song info before clearing for logging
            current_song = self.get_current_song(guild_id)
            current_title = current_song[1] if current_song else 'Unknown'

            # Clear queue for this specific server
            queue_data = self.queue.get_queue(guild_id)
            queue_size = len(queue_data['queue'])

            # Reset queue data
            queue_data['queue'] = []
            queue_data['current_index'] = -1

            ctxlog.debug(f'Cleared queue for guild {guild_id} (Cleared {queue_size} songs)')

            # Clean up server-specific states
            if guild_id in self.loop_types:
                del self.loop_types[guild_id]
            if guild_id in self.playback_times:
                del self.playback_times[guild_id]
            if guild_id in self.twenty_four_seven:
                del self.twenty_four_seven[guild_id]

            # Handle voice client
            voice_client = ctx.voice_client
            if voice_client:
                try:
                    if voice_client.is_playing() or voice_client.is_paused():
                        voice_client.stop()
                        ctxlog.info(f'Stopped playing: {current_title}')

                    # Update voice channel status before disconnecting
                    try:
                        voice_channel = ctx.author.voice.channel
                        await voice_channel.set_status(status='')
                    except Exception as status_error:
                        ctxlog.warning(f'Could not update status: {status_error}')

                    await voice_client.disconnect()
                    ctxlog.info(f'Disconnected from voice channel in guild {guild_id}')
                except Exception as voice_error:
                    ctxlog.error(f'Error handling voice client: {voice_error}')
            else:
                ctxlog.info(f'No voice client to disconnect in guild {guild_id}')

            # Prepare response message
            embed = discord.Embed(
                title='🛑 Music Stopped',
                description=f'• Cleared {queue_size} songs from queue\n'
                f'• Last played: {current_title}\n'
                f'• Disconnected from voice channel',
                color=discord.Color.red(),
            )

            await ctx.respond(embed=embed)
            ctxlog.success(f'Successfully stopped music and cleared queue in guild {guild_id}')

        except Exception as e:
            ctxlog.error(f'Error in stop command for guild {guild_id}: {e}')
            ctxlog.error(traceback.format_exc())

            await ctx.respond('An error occurred while stopping the music.')

            # Emergency cleanup
            try:
                queue_data = self.queue.get_queue(guild_id)
                queue_data['queue'] = []
                queue_data['current_index'] = -1

                if guild_id in self.loop_types:
                    del self.loop_types[guild_id]
                if guild_id in self.playback_times:
                    del self.playback_times[guild_id]

                if ctx.voice_client:
                    await ctx.voice_client.disconnect()

                ctxlog.info(f'Emergency cleanup completed for guild {guild_id}')
            except Exception as cleanup_error:
                ctxlog.error(f'Error during emergency cleanup: {cleanup_error}')

    @commands.slash_command(
        name='display_queue',
        description='Display the next 10 songs and total songs in queue',
    )
    async def display_queue(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command display_queue in guild {guild_id}')
        await ctx.defer()

        file = discord.File(
            'image_assets/31e0895d-7eac-43a3-b926-9f4781c08435.webp',
            filename='queue_image.webp',
        )

        queue_data = self.queue.get_queue(guild_id)
        if len(queue_data['queue']) == 0:
            await ctx.respond('The queue is currently empty.')
            return

        try:
            # Get current song info
            current_song = self.get_current_song(guild_id)
            if current_song:
                file_path, current_title, current_duration = current_song
                # Try to get additional metadata
                try:
                    audio = ID3(file_path)
                    artist = audio.get('TPE1', [''])[0]
                    if artist:
                        current_title = f'{current_title} - {artist}'
                except Exception:
                    pass
            else:
                current_title = 'Unknown'
                current_duration = 0

            current_index = queue_data['current_index']

            # Get next songs
            try:
                next_songs = queue_data['queue'][
                    queue_data['current_index'] + 1 : queue_data['current_index'] + 11
                ]
            except IndexError:
                next_songs = queue_data['queue'][queue_data['current_index'] + 1 :]

            # Create embed
            embed = discord.Embed(
                title='🎵 Queue Preview',
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow(),
            )

            # Add current song field
            embed.add_field(
                name='🔊 Now Playing',
                value=f'**{current_title}**\n`Duration:` {format_duration(current_duration)}',
                inline=False,
            )

            # Add separator
            embed.add_field(name='⎯' * 20, value='', inline=False)

            # Add upcoming songs with length checking
            if next_songs:
                upcoming_description = []
                total_duration = 0
                current_length = 0

                for i, (file_path, title, duration) in enumerate(next_songs, 1):
                    total_duration += duration
                    time_until = sum(song[2] for song in next_songs[: i - 1])

                    # Try to get artist info
                    try:
                        audio = ID3(file_path)
                        artist = audio.get('TPE1', [''])[0]
                        if artist:
                            title = f'{title} - {artist}'
                    except Exception:
                        pass

                    # Create the line for this song
                    song_line = (
                        f'`{i}.` 💠 **{title}**\n'
                        f'┗ Duration: {format_duration(duration)} • Plays in: {format_duration(time_until)}'
                    )

                    if current_length + len(song_line) + 1 < 1024:
                        upcoming_description.append(song_line)
                        current_length += len(song_line) + 1
                    else:
                        upcoming_description.append('*...and more songs*')
                        break

                embed.add_field(
                    name='📋 Up Next',
                    value='\n'.join(upcoming_description) or 'No upcoming songs',
                    inline=False,
                )
            else:
                embed.add_field(name='📋 Up Next', value='*No more songs in queue*', inline=False)

            # Add queue statistics
            remaining_songs = len(queue_data['queue']) - (current_index + 1)
            total_remaining_duration = sum(
                song[2] for song in queue_data['queue'][current_index + 1 :]
            )

            stats = (
                f'**Songs Remaining:** {remaining_songs}\n'
                f'**Total Duration:** {format_duration(total_remaining_duration)}\n'
                f'**Songs Shown:** {len(next_songs)}/10'
            )

            embed.add_field(name='📊 Queue Stats', value=stats, inline=False)

            embed.set_thumbnail(url='attachment://queue_image.webp')

            embed.set_footer(
                text=f"Currently Playing: {current_index + 1}/{len(queue_data['queue'])} • "
                f"Queue length: {format_duration(total_remaining_duration)}"
            )

            await ctx.respond(embed=embed, file=file)
            ctxlog.success('Sent display_queue successfully!')

        except Exception as e:
            ctxlog.error(f'Error in display_queue: {e}')
            ctxlog.error(traceback.format_exc())
            await ctx.respond('An error occurred while displaying the queue.')

    @commands.slash_command(
        name='shuffle', description='Shuffle all the remaining songs in the queue.'
    )
    async def shuffle(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command shuffle in guild {guild_id}')

        try:
            queue_data = self.queue.get_queue(guild_id)

            if len(queue_data['queue']) == 0:
                await ctx.respond('The queue is empty.')
                ctxlog.warning(f'Attempted to shuffle empty queue in guild {guild_id}')
                return

            if queue_data['current_index'] == len(queue_data['queue']) - 1:
                await ctx.respond('No songs remaining to shuffle.')
                ctxlog.warning(f'No remaining songs to shuffle in guild {guild_id}')
                return

            # Get the remaining songs (after current song)
            remaining_songs = queue_data['queue'][queue_data['current_index'] + 1 :]

            # Shuffle the remaining songs
            random.shuffle(remaining_songs)

            # Update the queue: keep current and previous songs, add shuffled remaining songs
            queue_data['queue'] = (
                queue_data['queue'][: queue_data['current_index'] + 1] + remaining_songs
            )

            ctxlog.success(f'Shuffled {len(remaining_songs)} songs in queue for guild {guild_id}')

            # Create embed for preview of upcoming songs
            next_songs = queue_data['queue'][queue_data['current_index'] + 1 :]
            preview_count = min(5, len(next_songs))  # Show up to 5 next songs

            if preview_count > 0:
                embed = discord.Embed(
                    title='🔀 Queue Shuffled',
                    description='The remaining songs in the queue have been shuffled.',
                    color=discord.Color.blue(),
                )

                preview_text = []
                for i, (file_path, title, duration) in enumerate(next_songs[:preview_count], 1):
                    # Try to get artist info
                    try:
                        audio = ID3(file_path)
                        artist = audio.get('TPE1', [''])[0]
                        if artist:
                            title = f'{title} - {artist}'
                    except Exception:
                        pass

                    preview_text.append(
                        f'`{i}.` **{title}**\n┗ Duration: {format_duration(duration)}'
                    )

                embed.add_field(name='📋 Next Up', value='\n'.join(preview_text), inline=False)

                total_remaining = len(next_songs)
                if total_remaining > preview_count:
                    embed.set_footer(
                        text=f'Showing {preview_count} of {total_remaining} remaining songs'
                    )

                await ctx.respond(embed=embed)
                ctxlog.info(
                    f'Displayed preview of {preview_count} upcoming songs in guild {guild_id}'
                )
            else:
                await ctx.respond('Shuffled the remaining songs in the queue.')

        except Exception as e:
            ctxlog.error(f'Error in shuffle command for guild {guild_id}: {e}')
            ctxlog.error(traceback.format_exc())
            await ctx.respond('An error occurred while shuffling the queue.')

            # Attempt to recover queue state if needed
            try:
                queue_data = self.queue.get_queue(guild_id)
                if queue_data['current_index'] >= len(queue_data['queue']):
                    queue_data['current_index'] = len(queue_data['queue']) - 1
                    ctxlog.info(f'Recovered queue index state for guild {guild_id}')
            except Exception as recovery_error:
                ctxlog.error(f'Error during state recovery: {recovery_error}')

    @commands.slash_command(name='loop_once', description='Loop the current song')
    async def loop_once(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used loop_once command in guild {guild_id}')

        try:
            current_song = self.get_current_song(guild_id)
            if not current_song:
                await ctx.respond('No song is currently playing.')
                return

            _, title, _ = current_song
            self.set_loop_type(guild_id, 'once')

            embed = discord.Embed(
                title='🔂 Loop Enabled',
                description=f'Now looping current song:\n**{title}**',
                color=discord.Color.blue(),
            )
            await ctx.respond(embed=embed)
            ctxlog.success(f'Enabled loop_once for {title} in guild {guild_id}')

        except Exception as e:
            ctxlog.error(f'Error in loop_once: {e}')
            await ctx.respond('An error occurred while enabling loop.')

    @commands.slash_command(name='loop_all', description='Loop all songs in queue')
    async def loop_all(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used loop_all command in guild {guild_id}')

        try:
            queue_data = self.queue.get_queue(guild_id)
            if len(queue_data['queue']) == 0:
                await ctx.respond('The queue is empty.')
                return

            self.set_loop_type(guild_id, 'all')

            embed = discord.Embed(
                title='🔁 Queue Loop Enabled',
                description=f"Now looping all {len(queue_data['queue'])} songs in queue",
                color=discord.Color.blue(),
            )
            await ctx.respond(embed=embed)
            ctxlog.success(f'Enabled loop_all in guild {guild_id}')

        except Exception as e:
            ctxlog.error(f'Error in loop_all: {e}')
            await ctx.respond('An error occurred while enabling queue loop.')

    @commands.slash_command(name='loop_off', description='Disable looping')
    async def loop_off(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used loop_off command in guild {guild_id}')

        try:
            previous_loop = self.get_loop_type(guild_id)
            self.set_loop_type(guild_id, None)

            embed = discord.Embed(
                title='➡️ Loop Disabled',
                description='Looping has been turned off',
                color=discord.Color.blue(),
            )
            if previous_loop:
                embed.set_footer(text=f'Previous mode: {previous_loop.upper()}')

            await ctx.respond(embed=embed)
            ctxlog.success(f'Disabled looping in guild {guild_id}')

        except Exception as e:
            ctxlog.error(f'Error in loop_off: {e}')
            await ctx.respond('An error occurred while disabling loop.')

    @commands.slash_command(name='play_playlist', description='Play all songs from a music folder')
    async def play_playlist(self, ctx: discord.ApplicationContext, folder_name: str):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used play_playlist command with folder: {folder_name}')
        await ctx.defer()

        if ctx.author.voice is None:
            ctxlog.warning('Attempted to use play_playlist command without joining voice channel.')
            await ctx.respond('You need to join a voice channel first.')
            return

        voice_channel = ctx.author.voice.channel
        folder_path = os.path.join(self.music_dir, folder_name)

        if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
            await ctx.respond(f"Folder '{folder_name}' doesn't exist in the music directory.")
            ctxlog.warning(f'Folder not found: {folder_path}')
            return

        try:
            # Get all audio files from the folder
            supported_formats = ('.mp3', '.wav', '.ogg', '.m4a')
            audio_files = [
                f for f in os.listdir(folder_path) if f.lower().endswith(supported_formats)
            ]

            if not audio_files:
                await ctx.respond(f"No supported audio files found in '{folder_name}'.")
                return

            # Shuffle the files if desired
            random.shuffle(audio_files)

            # Connect to voice channel if needed
            if ctx.voice_client is None:
                await voice_channel.connect()
                await asyncio.sleep(0.5)

            # Process and add all songs to queue
            processed_count = 0
            for audio_file in audio_files:
                file_path = os.path.join(folder_path, audio_file)
                audio_info = self.get_audio_info(file_path)

                if audio_info:
                    file_path, title, duration = audio_info
                    self.queue.add_song(guild_id, (file_path, title, duration))
                    processed_count += 1
                    ctxlog.info(f'Added to queue: {title}')

            # Start playing if nothing is playing
            if not ctx.voice_client.is_playing():
                current_song = self.get_current_song(guild_id)
                if current_song:
                    file_path, title, duration = current_song
                    success = await self.play_audio(
                        ctx,
                        file_path,
                        title,
                        duration,
                        after=lambda e: self.bot.loop.create_task(self.play_next_song(ctx)),
                    )

                    if success:
                        await ctx.send(f'Now playing: {title} ({format_duration(duration)})')
                        await voice_channel.set_status(status=f'▶️ {title}')
                        ctxlog.success(f'Started playing: {title}')

            # Create response embed
            embed = discord.Embed(
                title='📂 Playlist Loaded',
                description=f'Added songs from folder: **{folder_name}**',
                color=discord.Color.blue(),
            )

            embed.add_field(
                name='📊 Stats',
                value=f"• Added {processed_count} songs\n"
                f"• Total queue length: {len(self.queue.get_queue(guild_id)['queue'])} songs",
                inline=False,
            )

            # Add preview of first few songs
            if processed_count > 0:
                preview_songs = self.queue.get_queue(guild_id)['queue'][-processed_count:][:5]
                preview_text = []
                for i, (_, title, duration) in enumerate(preview_songs, 1):
                    preview_text.append(f'`{i}.` **{title}** ({format_duration(duration)})')

                embed.add_field(
                    name='📋 Preview',
                    value='\n'.join(preview_text) + '\n' + ('...' if processed_count > 5 else ''),
                    inline=False,
                )

            await ctx.respond(embed=embed)
            ctxlog.success(f'Successfully loaded {processed_count} songs from {folder_name}')

        except Exception as e:
            error_msg = f'Error processing folder: {str(e)}'
            ctxlog.error(error_msg)
            ctxlog.error(traceback.format_exc())
            await ctx.respond(f'An error occurred while loading the folder: {str(e)}')

    @commands.slash_command(
        name='available_playlists', description='Display all available music folders'
    )
    async def available_playlists(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command available_playlists in guild {guild_id}')

        await ctx.defer()

        try:
            # Get all directories from the music folder
            music_folders = [
                f
                for f in os.listdir(self.music_dir)
                if os.path.isdir(os.path.join(self.music_dir, f))
            ]

            if not music_folders:
                await ctx.respond('No music folders available.')
                ctxlog.warning(f'No music folders found in directory for guild {guild_id}')
                return

            # Sort folders alphabetically
            music_folders.sort()

            # Create embed for better presentation
            embed = discord.Embed(
                title='📂 Available Music Folders',
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow(),
            )

            # Process each folder
            for i, folder in enumerate(music_folders, 1):
                folder_path = os.path.join(self.music_dir, folder)

                try:
                    # Get supported audio files
                    supported_formats = ('.mp3', '.wav', '.ogg', '.m4a')
                    audio_files = [
                        f for f in os.listdir(folder_path) if f.lower().endswith(supported_formats)
                    ]

                    # Calculate total duration and size
                    total_duration = 0
                    total_size = 0
                    for audio_file in audio_files:
                        file_path = os.path.join(folder_path, audio_file)
                        try:
                            audio_info = self.get_audio_info(file_path)
                            if audio_info:
                                total_duration += audio_info[2]
                            total_size += os.path.getsize(file_path)
                        except Exception:
                            continue

                    # Format folder information
                    folder_info = (
                        f'**Songs:** {len(audio_files)}\n'
                        f'**Duration:** {format_duration(total_duration)}\n'
                        f'**Size:** {total_size / (1024*1024):.1f} MB'
                    )

                    embed.add_field(name=f'{i}. {folder}', value=folder_info, inline=False)

                except Exception as folder_error:
                    ctxlog.warning(f'Error reading folder {folder}: {folder_error}')
                    embed.add_field(
                        name=f'{i}. {folder}',
                        value='Error reading folder contents',
                        inline=False,
                    )

            # Add summary footer
            embed.set_footer(text=f'Total folders: {len(music_folders)}')

            # Send the embed
            await ctx.respond(embed=embed)
            ctxlog.success(
                f'Successfully displayed {len(music_folders)} music folders '
                f'for guild {guild_id}'
            )

        except Exception as e:
            error_message = f'Error accessing music folders: {str(e)}'
            ctxlog.error(f'{error_message} in guild {guild_id}')
            ctxlog.error(traceback.format_exc())
            await ctx.respond(
                'Unable to access music folders at this time. Please try again later.'
            )

            # Log system information for debugging
            try:
                ctxlog.debug(f'Music directory path: {self.music_dir}')
                ctxlog.debug(f'Directory exists: {os.path.exists(self.music_dir)}')
                ctxlog.debug(f'Directory is readable: {os.access(self.music_dir, os.R_OK)}')
            except Exception as debug_error:
                ctxlog.error(f'Error gathering debug information: {debug_error}')

    @commands.slash_command(
        name='show_playlist', description='Display the contents of a music folder'
    )
    async def show_playlist(self, ctx: discord.ApplicationContext, folder_name: str):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used show_playlist command for folder: {folder_name}')
        await ctx.defer()

        folder_path = os.path.join(self.music_dir, folder_name)

        if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
            await ctx.respond(f"Folder '{folder_name}' doesn't exist.")
            ctxlog.warning(f'Attempted to show non-existent folder: {folder_name}')
            return

        try:
            # Get all audio files
            supported_formats = ('.mp3', '.wav', '.ogg', '.m4a')
            audio_files = [
                f for f in os.listdir(folder_path) if f.lower().endswith(supported_formats)
            ]

            if not audio_files:
                await ctx.respond(f"No audio files found in folder '{folder_name}'.")
                ctxlog.info(f'Displayed empty folder: {folder_name}')
                return

            # Sort files alphabetically
            audio_files.sort()

            # Process all files
            folder_data = {
                'name': folder_name,
                'files': [],
                'total_duration': 0,
                'total_size': 0,
            }

            for filename in audio_files:
                file_path = os.path.join(folder_path, filename)
                try:
                    audio_info = self.get_audio_info(file_path)
                    if audio_info:
                        _, title, duration = audio_info
                        size = os.path.getsize(file_path) / (1024 * 1024)  # Size in MB
                        folder_data['total_duration'] += duration
                        folder_data['total_size'] += size

                        # Try to get artist info
                        artist = ''
                        try:
                            audio = ID3(file_path)
                            artist = audio.get('TPE1', [''])[0]
                        except Exception:
                            pass

                        folder_data['files'].append((filename, title, duration, size, artist))

                except Exception as e:
                    ctxlog.warning(f'Error processing file {filename}: {e}')
                    folder_data['files'].append((filename, filename, 0, 0, ''))

            # Create the view and get initial embed
            view = PlaylistView(folder_data)
            embed = view.get_embed()

            # Send the message
            message = await ctx.respond(embed=embed, view=view)

            # Store the message for timeout handling
            if isinstance(message, discord.Webhook):
                view.message = await message.fetch()
            else:
                view.message = message

            ctxlog.success(
                f'Successfully displayed folder: {folder_name} with {len(audio_files)} songs'
            )

        except Exception as e:
            error_msg = f'Error reading folder: {str(e)}'
            ctxlog.error(error_msg)
            ctxlog.error(traceback.format_exc())
            await ctx.respond('Failed to read folder contents. Please try again.')

    @commands.slash_command(name='skip_multiple', description='Skip multiple songs in the queue.')
    async def skip_multiple(
        self, ctx: discord.ApplicationContext, number: int
    ):  # Changed to int type
        guild_id = ctx.guild.id
        if guild_id in self.playback_times:
            del self.playback_times[guild_id]
        ctxlog = get_context_logger(ctx)
        ctxlog.info(
            f"{ctx.author.name} used command 'skip_multiple' with number: {number} "
            f'in guild {guild_id}'
        )

        try:
            # Check if music is playing
            if ctx.voice_client is None or not ctx.voice_client.is_playing():
                await ctx.respond('No music playing to be skipped.')
                ctxlog.warning(
                    f'Used skip_multiple command without music playback in guild {guild_id}'
                )
                return

            # Validate skip count
            if number <= 0:
                await ctx.respond('Please provide a positive number.')
                ctxlog.warning(f'Invalid skip count provided: {number} in guild {guild_id}')
                return

            # Get queue data for this server
            queue_data = self.queue.get_queue(guild_id)
            current_index = queue_data['current_index']
            queue_length = len(queue_data['queue'])

            # Calculate remaining songs in queue
            remaining_songs = queue_length - (current_index + 1)

            # Check if skip count is valid
            if number > remaining_songs:
                embed = discord.Embed(
                    title='⚠️ Cannot Skip',
                    description=f"Cannot skip {number} songs.\n"
                    f"Only {remaining_songs} song{'s' if remaining_songs != 1 else ''} "
                    f"remaining in queue.",
                    color=discord.Color.red(),
                )
                await ctx.respond(embed=embed)
                ctxlog.warning(
                    f'Attempted to skip more songs than available in guild {guild_id}: '
                    f'{number} > {remaining_songs}'
                )
                return

            # Store current and target songs for message
            current_song = self.get_current_song(guild_id)
            current_title = current_song[1] if current_song else 'Unknown'

            target_index = current_index + number
            target_song = queue_data['queue'][target_index] if target_index < queue_length else None
            target_title = target_song[1] if target_song else 'Unknown'

            # Try to get additional metadata for display
            try:
                if current_song and target_song:
                    current_path = current_song[0]
                    target_path = target_song[0]

                    current_audio = ID3(current_path)
                    target_audio = ID3(target_path)

                    current_artist = current_audio.get('TPE1', [''])[0]
                    target_artist = target_audio.get('TPE1', [''])[0]

                    if current_artist:
                        current_title = f'{current_title} - {current_artist}'
                    if target_artist:
                        target_title = f'{target_title} - {target_artist}'
            except Exception:
                pass

            # Adjust the current_index before stopping
            queue_data['current_index'] += number - 1  # -1 because play_next_song increments by 1

            # Stop current song which will trigger play_next_song
            ctxlog.info(f'Stopping current song in guild {guild_id}...')
            ctx.voice_client.stop()

            # Create response embed
            embed = discord.Embed(
                title=f"⏭️ Skipped {number} song{'s' if number != 1 else ''}",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow(),
            )

            embed.add_field(name='From', value=current_title, inline=False)

            embed.add_field(name='To', value=target_title, inline=False)

            embed.add_field(
                name='Queue Status',
                value=f'Remaining songs: {remaining_songs - number}',
                inline=False,
            )

            await ctx.respond(embed=embed)
            ctxlog.success(
                f"Successfully skipped {number} songs in guild {guild_id}. "
                f"New index: {queue_data['current_index']}"
            )

        except Exception as e:
            error_msg = f'Error in skip_multiple: {str(e)}'
            ctxlog.error(f'{error_msg} in guild {guild_id}')
            ctxlog.error(traceback.format_exc())

            await ctx.respond('An error occurred while trying to skip songs. Please try again.')

            # Attempt to recover queue state
            try:
                queue_data = self.queue.get_queue(guild_id)
                if queue_data['current_index'] >= len(queue_data['queue']):
                    queue_data['current_index'] = len(queue_data['queue']) - 1
                    ctxlog.info(f'Recovered queue index state for guild {guild_id}')
            except Exception as recovery_error:
                ctxlog.error(f'Error during state recovery: {recovery_error}')

    @commands.slash_command(
        name='jump', description='Jump to a specific song in the queue by its number.'
    )
    async def jump(self, ctx: discord.ApplicationContext, number: int):  # Changed to int type
        guild_id = ctx.guild.id
        if guild_id in self.playback_times:
            del self.playback_times[guild_id]
        ctxlog = get_context_logger(ctx)
        ctxlog.info(
            f"{ctx.author.name} used command 'jump' with number: {number} in guild {guild_id}"
        )

        try:
            # Check if music is playing
            if ctx.voice_client is None or not ctx.voice_client.is_playing():
                await ctx.respond('No music playing.')
                ctxlog.warning(f'Used jump command without music playback in guild {guild_id}')
                return

            # Get queue data for this server
            queue_data = self.queue.get_queue(guild_id)
            queue_length = len(queue_data['queue'])

            # Check if the index is within queue bounds
            if number < 1 or number > queue_length:
                embed = discord.Embed(
                    title='⚠️ Invalid Position',
                    description=f'Please use a number between 1 and {queue_length}',
                    color=discord.Color.red(),
                )
                await ctx.respond(embed=embed)
                ctxlog.warning(
                    f'Jump index out of range in guild {guild_id}: {number}, '
                    f'queue length: {queue_length}'
                )
                return

            # Get current and target song information
            current_song = self.get_current_song(guild_id)
            current_title = current_song[1] if current_song else 'Unknown'
            current_path = current_song[0] if current_song else None

            target_song = queue_data['queue'][number - 1]
            target_path, target_title, target_duration = target_song

            # Try to get additional metadata
            try:
                if current_path:
                    current_audio = ID3(current_path)
                    current_artist = current_audio.get('TPE1', [''])[0]
                    if current_artist:
                        current_title = f'{current_title} - {current_artist}'

                target_audio = ID3(target_path)
                target_artist = target_audio.get('TPE1', [''])[0]
                if target_artist:
                    target_title = f'{target_title} - {target_artist}'
            except Exception as metadata_error:
                ctxlog.warning(f'Error reading metadata: {metadata_error}')

            # Set the index to one less than target because play_next_song increments by 1
            queue_data['current_index'] = number - 2

            # Stop current song which will trigger play_next_song
            ctxlog.info(f'Stopping current song in guild {guild_id}...')
            ctx.voice_client.stop()

            # Create response embed
            embed = discord.Embed(
                title='⏯️ Jumped to Requested Song',
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow(),
            )

            embed.add_field(name='From', value=current_title, inline=False)

            embed.add_field(
                name='To',
                value=f'{target_title}\nDuration: {format_duration(target_duration)}',
                inline=False,
            )

            embed.add_field(name='Position', value=f'Song {number} of {queue_length}', inline=False)

            # Calculate remaining songs
            remaining_songs = queue_length - number
            embed.set_footer(text=f'Remaining songs in queue: {remaining_songs}')

            await ctx.respond(embed=embed)
            ctxlog.success(f'Successfully jumped to index {number} in guild {guild_id}')

            # Update voice channel status
            try:
                voice_channel = ctx.author.voice.channel
                await voice_channel.set_status(status=f'▶️ {target_title}')
            except Exception as status_error:
                ctxlog.warning(f'Could not update status: {status_error}')

        except Exception as e:
            error_msg = f'Error in jump command: {str(e)}'
            ctxlog.error(f'{error_msg} in guild {guild_id}')
            ctxlog.error(traceback.format_exc())

            embed = discord.Embed(
                title='❌ Error',
                description='An error occurred while trying to jump to the requested song.',
                color=discord.Color.red(),
            )
            await ctx.respond(embed=embed)

            # Attempt to recover queue state
            try:
                queue_data = self.queue.get_queue(guild_id)
                if queue_data['current_index'] >= len(queue_data['queue']):
                    queue_data['current_index'] = len(queue_data['queue']) - 1
                    ctxlog.info(f'Recovered queue index state for guild {guild_id}')
            except Exception as recovery_error:
                ctxlog.error(f'Error during state recovery: {recovery_error}')

            # Try to resume playback if possible
            try:
                if ctx.voice_client and not ctx.voice_client.is_playing():
                    await self.play_next_song(ctx)
            except Exception as playback_error:
                ctxlog.error(f'Error recovering playback: {playback_error}')

    @commands.slash_command(
        name='play_next',
        description='Add a song to play immediately after the current song.',
    )
    async def play_next(self, ctx: discord.ApplicationContext, filename: str):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(
            f'{ctx.author.name} used play_next command with file: {filename} in guild {guild_id}'
        )
        await ctx.defer()

        try:
            # Get queue data for this server
            queue_data = self.queue.get_queue(guild_id)

            # Check if there's an active queue
            if queue_data['current_index'] == -1:
                await ctx.respond('No active queue. Use /play_music to start playing music first.')
                ctxlog.warning(f'Used play_next without active queue in guild {guild_id}')
                return

            # Verify file exists and get audio information
            file_path = os.path.join(self.music_dir, filename)
            if not os.path.exists(file_path):
                await ctx.respond(f"File '{filename}' not found in music directory.")
                ctxlog.warning(f'File not found: {file_path}')
                return

            # Get audio information
            audio_info = self.get_audio_info(file_path)
            if not audio_info:
                await ctx.respond(f"Failed to read audio file '{filename}'.")
                return

            file_path, title, duration = audio_info

            # Try to get additional metadata
            try:
                audio = ID3(file_path)
                artist = audio.get('TPE1', [''])[0]
                if artist:
                    title = f'{title} - {artist}'
            except Exception:
                pass

            # Get current song info for context
            current_song = self.get_current_song(guild_id)
            if current_song:
                _, current_title, _ = current_song
                try:
                    current_audio = ID3(current_song[0])
                    current_artist = current_audio.get('TPE1', [''])[0]
                    if current_artist:
                        current_title = f'{current_title} - {current_artist}'
                except Exception:
                    pass
            else:
                current_title = 'Unknown'

            # Insert the song right after the current song
            insert_position = queue_data['current_index'] + 1
            queue_data['queue'].insert(insert_position, (file_path, title, duration))

            # Get next song info for context
            next_song_position = insert_position + 1
            if next_song_position < len(queue_data['queue']):
                next_song_info = queue_data['queue'][next_song_position]
                next_title = next_song_info[1]
                try:
                    next_audio = ID3(next_song_info[0])
                    next_artist = next_audio.get('TPE1', [''])[0]
                    if next_artist:
                        next_title = f'{next_title} - {next_artist}'
                except Exception:
                    pass
            else:
                next_title = 'End of queue'

            # Create response embed
            embed = discord.Embed(
                title='🎵 Added Song to Play Next',
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow(),
            )

            embed.add_field(name='Currently Playing', value=current_title, inline=False)

            embed.add_field(
                name='Playing Next',
                value=f'{title}\nDuration: {format_duration(duration)}',
                inline=False,
            )

            embed.add_field(name='Following', value=next_title, inline=False)

            embed.add_field(
                name='Queue Position',
                value=f"Position {insert_position + 1} of {len(queue_data['queue'])}",
                inline=False,
            )

            await ctx.respond(embed=embed)
            ctxlog.success(
                f'Successfully inserted song at position {insert_position} in guild {guild_id}: '
                f'{title}'
            )

        except Exception as e:
            error_msg = f'Error in play_next command: {str(e)}'
            ctxlog.error(f'{error_msg} in guild {guild_id}')
            ctxlog.error(traceback.format_exc())

            embed = discord.Embed(
                title='❌ Error',
                description='An error occurred while trying to add the song.',
                color=discord.Color.red(),
            )
            await ctx.respond(embed=embed)

            # Log queue state for debugging
            try:
                queue_data = self.queue.get_queue(guild_id)
                ctxlog.debug(
                    f"Queue state for guild {guild_id}: "
                    f"current_index={queue_data['current_index']}, "
                    f"queue_length={len(queue_data['queue'])}"
                )
            except Exception as debug_error:
                ctxlog.error(f'Error gathering debug information: {debug_error}')

    @commands.slash_command(name='suggest', description='Suggests similar songs from YouTube.')
    async def suggest(self, ctx):
        guild_id = ctx.guild.id
        ctxlogger = get_context_logger(ctx)
        ctxlogger.info(f"{ctx.author.name} used command 'suggest' in guild {guild_id}")

        # Get current song for this specific server
        current_song = self.get_current_song(guild_id)
        if not current_song:
            await ctx.respond('No song currently playing to base suggestions on.')
            ctxlogger.warning(f'No current song playing in guild {guild_id}')
            return

        # Get song metadata
        file_path, title, _ = current_song
        search_query = title

        # Try to get better metadata from ID3 tags
        try:
            audio = ID3(file_path)
            title_tag = audio.get('TIT2', [''])[0]
            artist_tag = audio.get('TPE1', [''])[0]
            if title_tag and artist_tag:
                search_query = f'{title_tag} {artist_tag}'
        except Exception:
            pass

        # Clean up the search query
        if '(' in search_query:
            search_query = search_query.split('(')[0]
        if '-' in search_query:
            search_query = search_query.split('-')[0]

        ctxlogger.info(f'Searching suggestions for: {search_query} in guild {guild_id}')
        await ctx.defer()

        try:
            # Fetch related videos using YouTube API
            url = 'https://www.googleapis.com/youtube/v3/search'
            params = {
                'part': 'snippet',
                'q': search_query,
                'type': 'video',
                'key': self.youtube_api_key,
                'maxResults': 5,
            }

            ctxlogger.debug(f'Sending GET request to url: {url} for guild {guild_id}')

            response = requests.get(url, params=params)
            if response.status_code != 200:
                ctxlogger.error(f'Request failed for guild {guild_id}: {response.status_code}')
                await ctx.respond('Failed to fetch suggestions. Please try again later.')
                return

            ctxlogger.success(f'Request returned code 200 for guild {guild_id}')
            data = response.json()
            suggestions = []

            for item in data.get('items', []):
                title = item['snippet']['title']
                video_id = item['id']['videoId']
                url = f'https://www.youtube.com/watch?v={video_id}'
                suggestions.append(f'[{title}]({url})')

            if not suggestions:
                ctxlogger.warning(
                    f'No suggestions found for query: {search_query} in guild {guild_id}'
                )
                await ctx.respond('No suggestions found!')
                return

            # Create a rich embed to display suggestions
            embed = discord.Embed(
                title='🎵 Similar Songs on YouTube',
                description=f'Based on: **{search_query}**\n\n'
                + '\n'.join(f'{i+1}. {suggestion}' for i, suggestion in enumerate(suggestions)),
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow(),
            )
            embed.set_footer(text='Note: These are YouTube suggestions for similar music')

            await ctx.respond(embed=embed)
            ctxlogger.success(f'Sent suggestions embed successfully for guild {guild_id}')

        except Exception as e:
            error_msg = f'Error in suggest command: {str(e)}'
            ctxlogger.error(f'{error_msg} in guild {guild_id}')
            ctxlogger.error(traceback.format_exc())
            await ctx.respond(
                'An error occurred while fetching suggestions. Please try again later.'
            )

    @commands.slash_command(
        name='queueinfo',
        description='Display detailed analytics about the current queue.',
    )
    async def queueinfo(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command queueinfo in guild {guild_id}')

        try:
            # Get queue data for this server
            queue_data = self.queue.get_queue(guild_id)

            if len(queue_data['queue']) == 0:
                await ctx.respond('The queue is currently empty.')
                ctxlog.warning(f'Queue is empty for guild {guild_id}')
                return

            # Calculate queue statistics
            total_songs = len(queue_data['queue'])
            current_index = queue_data['current_index']
            remaining_songs = len(queue_data['queue'][current_index:])
            completed_songs = total_songs - remaining_songs

            # Duration calculations
            total_duration = sum(song[2] for song in queue_data['queue'])
            remaining_duration = sum(song[2] for song in queue_data['queue'][current_index:])
            completed_duration = total_duration - remaining_duration
            avg_duration = total_duration // total_songs if total_songs > 0 else 0

            # Calculate total size of audio files
            total_size = 0
            for file_path, _, _ in queue_data['queue']:
                try:
                    total_size += os.path.getsize(file_path)
                except Exception:
                    continue
            total_size_mb = total_size / (1024 * 1024)  # Convert to MB

            # Create embed
            embed = discord.Embed(
                title='📊 Queue Statistics',
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow(),
            )

            # Songs information
            embed.add_field(
                name='📈 Queue Status',
                value=(
                    f'**Total Songs:** {total_songs}\n'
                    f'**Remaining:** {remaining_songs}\n'
                    f'**Completed:** {completed_songs}\n'
                    f'**Total Size:** {total_size_mb:.1f} MB'
                ),
                inline=True,
            )

            # Duration information
            embed.add_field(
                name='⏱️ Duration',
                value=(
                    f'**Total:** {format_duration(total_duration)}\n'
                    f'**Remaining:** {format_duration(remaining_duration)}\n'
                    f'**Completed:** {format_duration(completed_duration)}\n'
                    f'**Average:** {format_duration(avg_duration)} per song'
                ),
                inline=True,
            )

            # Current song and progress
            current_song = self.get_current_song(guild_id)
            if current_song:
                file_path, title, duration = current_song
                progress_percent = (completed_songs / total_songs) * 100 if total_songs > 0 else 0

                # Try to get additional metadata
                try:
                    audio = ID3(file_path)
                    artist = audio.get('TPE1', [''])[0]
                    album = audio.get('TALB', [''])[0]
                    if artist:
                        title = f'{title} - {artist}'
                    if album:
                        title += f' ({album})'
                except Exception:
                    pass

                # Create progress bar
                bar_length = 20
                filled = int((progress_percent / 100) * bar_length)
                progress_bar = '▰' * filled + '▱' * (bar_length - filled)

                embed.add_field(
                    name='🎵 Now Playing',
                    value=(
                        f'**Title:** {title}\n'
                        f'**Duration:** {format_duration(duration)}\n'
                        f'**Position:** {current_index + 1} of {total_songs}\n'
                        f'**Progress:** {progress_bar} ({progress_percent:.1f}%)'
                    ),
                    inline=False,
                )

            # Loop status
            loop_type = self.get_loop_type(guild_id)
            if loop_type:
                embed.add_field(
                    name='🔁 Loop Status',
                    value=f'Loop mode: {loop_type.title()}',
                    inline=True,
                )

            # Add file format information
            format_counts = {}
            for file_path, _, _ in queue_data['queue']:
                ext = os.path.splitext(file_path)[1].lower()
                format_counts[ext] = format_counts.get(ext, 0) + 1

            if format_counts:
                format_info = '\n'.join(
                    f'**{ext}:** {count} files' for ext, count in format_counts.items()
                )
                embed.add_field(name='📁 File Formats', value=format_info, inline=True)

            # Set footer with server info
            embed.set_footer(text=f'Server: {ctx.guild.name} | Queue ID: {guild_id}')

            await ctx.respond(embed=embed)
            ctxlog.success(f'Successfully displayed queue information for guild {guild_id}')

        except Exception as e:
            error_msg = f'Error getting queue information: {str(e)}'
            ctxlog.error(f'{error_msg} in guild {guild_id}')
            ctxlog.error(traceback.format_exc())

            await ctx.respond(
                'An error occurred while getting queue information. Please try again.'
            )

            # Log queue state for debugging
            try:
                queue_data = self.queue.get_queue(guild_id)
                ctxlog.debug(
                    f"Queue state for guild {guild_id}: "
                    f"queue_length={len(queue_data['queue'])}, "
                    f"current_index={queue_data['current_index']}"
                )
            except Exception as debug_error:
                ctxlog.error(f'Error gathering debug information: {debug_error}')

    @commands.slash_command(
        name='remove',
        description='Remove a specific song from the queue by its position number.',
    )
    async def remove(self, ctx: discord.ApplicationContext, position: int):  # Changed to int type
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(
            f'{ctx.author.name} used remove command with position: {position} '
            f'in guild {guild_id}'
        )

        try:
            # Get queue data for this server
            queue_data = self.queue.get_queue(guild_id)

            # Check if queue is empty
            if len(queue_data['queue']) == 0:
                await ctx.respond('The queue is currently empty.')
                ctxlog.warning(f'Attempted to remove from empty queue in guild {guild_id}')
                return

            # Validate position
            if position <= 0:
                await ctx.respond('Please provide a positive number.')
                return

            # Adjust position to 0-based index
            pos = position - 1
            queue_length = len(queue_data['queue'])

            # Check if number is in valid range
            if pos >= queue_length:
                embed = discord.Embed(
                    title='⚠️ Invalid Position',
                    description=f'Please provide a number between 1 and {queue_length}.',
                    color=discord.Color.red(),
                )
                await ctx.respond(embed=embed)
                ctxlog.warning(
                    f'Position out of range in guild {guild_id}: {position}, '
                    f'queue length: {queue_length}'
                )
                return

            # Check if trying to remove currently playing song
            if pos == queue_data['current_index']:
                embed = discord.Embed(
                    title='❌ Cannot Remove Current Song',
                    description='Cannot remove the currently playing song. Use /skip instead.',
                    color=discord.Color.red(),
                )
                await ctx.respond(embed=embed)
                ctxlog.warning(f'Attempted to remove currently playing song in guild {guild_id}')
                return

            try:
                # Get song details before removing
                removed_song = queue_data['queue'][pos]
                file_path, title, duration = removed_song

                # Try to get additional metadata
                try:
                    audio = ID3(file_path)
                    artist = audio.get('TPE1', [''])[0]
                    album = audio.get('TALB', [''])[0]
                    if artist:
                        title = f'{title} - {artist}'
                    if album:
                        title += f' ({album})'
                except Exception:
                    pass

                # Get context information
                current_song = self.get_current_song(guild_id)
                if current_song:
                    _, current_title, _ = current_song
                    try:
                        current_audio = ID3(current_song[0])
                        current_artist = current_audio.get('TPE1', [''])[0]
                        if current_artist:
                            current_title = f'{current_title} - {current_artist}'
                    except Exception:
                        pass
                else:
                    current_title = 'Unknown'

                # Remove the song
                queue_data['queue'].pop(pos)

                # Adjust current_index if we removed a song before it
                if pos < queue_data['current_index']:
                    queue_data['current_index'] -= 1
                    ctxlog.info(
                        f"Adjusted current_index to {queue_data['current_index']} "
                        f"in guild {guild_id}"
                    )

                # Prepare response embed
                embed = discord.Embed(
                    title='🗑️ Song Removed',
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow(),
                )

                embed.add_field(
                    name='Removed Song',
                    value=f'**Title:** {title}\n**Duration:** {format_duration(duration)}',
                    inline=False,
                )

                remaining_songs = len(queue_data['queue']) - (queue_data['current_index'] + 1)
                embed.add_field(
                    name='Queue Status',
                    value=(
                        f'**Position removed:** {position}\n'
                        f'**Current song:** {current_title}\n'
                        f'**Remaining songs:** {remaining_songs}'
                    ),
                    inline=False,
                )

                # Add queue progress
                total_songs = len(queue_data['queue'])
                progress_percent = ((queue_data['current_index'] + 1) / total_songs) * 100
                bar_length = 20
                filled = int((progress_percent / 100) * bar_length)
                progress_bar = '▰' * filled + '▱' * (bar_length - filled)

                embed.add_field(
                    name='Queue Progress',
                    value=f'`{progress_bar}` {progress_percent:.1f}%',
                    inline=False,
                )

                await ctx.respond(embed=embed)
                ctxlog.success(
                    f'Successfully removed song at position {position} in guild {guild_id}'
                )

            except Exception as e:
                error_msg = f'Error removing song: {str(e)}'
                ctxlog.error(f'{error_msg} in guild {guild_id}')
                await ctx.respond('Failed to remove song. Please try again.')

        except Exception as e:
            ctxlog.error(f'Error in remove command for guild {guild_id}: {e}')
            ctxlog.error(traceback.format_exc())

            await ctx.respond('An error occurred while removing the song. Please try again.')

            # Log queue state for debugging
            try:
                queue_data = self.queue.get_queue(guild_id)
                ctxlog.debug(
                    f"Queue state for guild {guild_id}: "
                    f"queue_length={len(queue_data['queue'])}, "
                    f"current_index={queue_data['current_index']}"
                )
            except Exception as debug_error:
                ctxlog.error(f'Error gathering debug information: {debug_error}')

    @commands.slash_command(
        name='seek',
        description='Seek to a specific timestamp in the current song (format: mm:ss)',
    )
    async def seek(self, ctx: discord.ApplicationContext, timestamp: str):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(
            f'{ctx.author.name} used seek command with timestamp: {timestamp} '
            f'in guild {guild_id}'
        )

        # Initialize seeking set if it doesn't exist
        if not hasattr(self, 'seeking'):
            self.seeking = set()

        try:
            # Check if already seeking
            if guild_id in self.seeking:
                await ctx.respond('A seek operation is already in progress.')
                return

            self.seeking.add(guild_id)

            # Check if music is playing
            if not ctx.voice_client or not ctx.voice_client.is_playing():
                await ctx.respond('No song is currently playing.')
                ctxlog.warning(f'Used seek command without active playback in guild {guild_id}')
                return

            # Validate timestamp format (mm:ss)
            if not re.match(r'^\d{1,2}:\d{2}$', timestamp):
                await ctx.respond('⚠️ Invalid timestamp format. Please use mm:ss (e.g., 2:30)')
                ctxlog.warning(f'Invalid timestamp format: {timestamp} in guild {guild_id}')
                return

            try:
                # Convert timestamp to seconds
                minutes, seconds = map(int, timestamp.split(':'))
                seek_position = minutes * 60 + seconds

                # Get current song information
                current_song = self.get_current_song(guild_id)
                if not current_song:
                    await ctx.respond('No song is currently playing.')
                    ctxlog.warning(f'No current song found in guild {guild_id}')
                    return

                file_path, title, song_duration = current_song

                # Check if seek position is valid
                if seek_position >= song_duration:
                    await ctx.respond(
                        f'⚠️ Timestamp exceeds song duration ({format_duration(song_duration)})'
                    )
                    ctxlog.warning(
                        f'Seek position {seek_position} exceeds duration {song_duration} '
                        f'in guild {guild_id}'
                    )
                    return

                # Try to get additional metadata
                try:
                    audio = ID3(file_path)
                    artist = audio.get('TPE1', [''])[0]
                    if artist:
                        title = f'{title} - {artist}'
                except Exception:
                    pass

                # Create new FFMPEG options with seek
                ffmpeg_options = {
                    'before_options': f'-ss {seek_position}',
                    'options': '-vn -af "aresample=44100:filter_size=64:phase_shift=8"',
                }

                # Stop current playback
                ctx.voice_client.stop()

                # Start playback from new position
                ctx.voice_client.play(
                    discord.FFmpegPCMAudio(file_path, **ffmpeg_options),
                    after=lambda e: self.bot.loop.create_task(self.play_next_song(ctx)),
                )

                self.playback_times[guild_id] = time.time() - seek_position

                # Create response embed
                embed = discord.Embed(
                    title='⏩ Seek Operation',
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow(),
                )

                embed.add_field(
                    name='Song Information',
                    value=(
                        f'**Title:** {title}\n'
                        f'**Total Duration:** {format_duration(song_duration)}'
                    ),
                    inline=False,
                )

                embed.add_field(
                    name='Seek Details',
                    value=(
                        f'**Seeked to:** {timestamp}\n'
                        f'**Time Remaining:** {format_duration(song_duration - seek_position)}'
                    ),
                    inline=False,
                )

                # Create progress bar
                bar_length = 20
                progress = seek_position / song_duration
                filled = int(bar_length * progress)
                progress_bar = '▰' * filled + '▱' * (bar_length - filled)

                embed.add_field(
                    name='Progress',
                    value=f'`{progress_bar}` {(progress * 100):.1f}%',
                    inline=False,
                )

                await ctx.respond(embed=embed)
                ctxlog.success(
                    f'Successfully seeked to position {seek_position} in guild {guild_id}'
                )

            except ValueError as e:
                await ctx.respond(
                    '⚠️ Invalid timestamp values. Please use valid numbers (e.g., 2:30)'
                )
                ctxlog.error(f'ValueError in seek command for guild {guild_id}: {e}')

        except Exception as e:
            error_msg = f'Error during seek: {str(e)}'
            ctxlog.error(f'{error_msg} in guild {guild_id}')
            ctxlog.error(traceback.format_exc())

            await ctx.respond('An error occurred while seeking. Please try again.')

            # Log playback state for debugging
            try:
                queue_data = self.queue.get_queue(guild_id)
                ctxlog.debug(
                    f"Playback state for guild {guild_id}: "
                    f"current_index={queue_data['current_index']}, "
                    f"is_playing={ctx.voice_client.is_playing() if ctx.voice_client else False}"
                )
            except Exception as debug_error:
                ctxlog.error(f'Error gathering debug information: {debug_error}')

        finally:
            # Always remove the seeking flag
            if guild_id in self.seeking:
                self.seeking.remove(guild_id)

    @commands.slash_command(
        name='24x7',
        description='Toggle 24/7 mode - bot will stay in channel even when empty',
    )
    async def _24x7(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used 24x7 command in guild {guild_id}')

        try:
            # Check if user is in a voice channel
            if ctx.author.voice is None:
                embed = discord.Embed(
                    title='⚠️ Not in Voice Channel',
                    description='You need to be in a voice channel to use this command!',
                    color=discord.Color.red(),
                )
                await ctx.respond(embed=embed)
                return

            # Toggle the state
            current_state = self.twenty_four_seven.get(guild_id, False)
            self.twenty_four_seven[guild_id] = not current_state

            # Create response embed
            embed = discord.Embed(
                title='🎵 24/7 Mode',
                color=(discord.Color.green() if not current_state else discord.Color.red()),
                timestamp=discord.utils.utcnow(),
            )

            status = 'Enabled' if not current_state else 'Disabled'
            embed.add_field(name='Status', value=f'24/7 Mode has been **{status}**', inline=False)

            if not current_state:  # If enabling
                current_song = self.get_current_song(guild_id)
                if current_song:
                    _, title, duration = current_song
                    embed.add_field(
                        name='Currently Playing',
                        value=f'**{title}**\nDuration: {format_duration(duration)}',
                        inline=False,
                    )

                embed.add_field(
                    name='Info',
                    value='• Bot will stay in the voice channel even when empty\n'
                    '• Queue will be preserved\n'
                    '• Use `/24x7` again to disable',
                    inline=False,
                )
            else:  # If disabling
                embed.add_field(
                    name='Info',
                    value='• Bot will now leave when voice channel is empty\n'
                    '• Queue will be cleared on leave\n'
                    '• Use `/24x7` again to enable',
                    inline=False,
                )

            embed.set_footer(text=f'Requested by {ctx.author.name} | Server: {ctx.guild.name}')

            await ctx.respond(embed=embed)
            ctxlog.success(f'24/7 mode {status.lower()} for guild {guild_id}')

        except Exception as e:
            ctxlog.error(f'Error in 24x7 command for guild {guild_id}: {e}')
            ctxlog.error(traceback.format_exc())

            embed = discord.Embed(
                title='❌ Error',
                description='An error occurred while toggling 24/7 mode.',
                color=discord.Color.red(),
            )
            await ctx.respond(embed=embed)


def setup(bot):
    bot.add_cog(MusicLocal(bot))
