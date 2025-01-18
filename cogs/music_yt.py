import asyncio
import functools
import math
import os
import random
import re
import time
import tomllib
import traceback
from concurrent.futures import ThreadPoolExecutor

import aiohttp
import discord
import requests

# import spotipy
from discord.ext import commands
from pytube import Playlist
from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials
from yt_dlp import YoutubeDL

from utils.logger import get_context_logger, log
from validators.config import ConfigValidator

# from typing import Tuple


with open(os.path.join('config.toml'), 'rb') as f:
    data = tomllib.load(f)
arle_config: ConfigValidator = ConfigValidator.model_validate(data)

youtube_api_key = arle_config.secrets.youtube_api_key

# log.info(f"youtube_api_key: {youtube_api_key}")


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
                'temp_queue': [],
                'current_index': -1,
                'processing_lock': False,
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


class MusicYT(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = MusicQueue()
        self.spotify_client_id = arle_config.secrets.spotify_cid
        self.spotify_client_secret = arle_config.secrets.spotify_cs
        self.thread_pool = ThreadPoolExecutor(max_workers=6)
        self.loop_types = {}  # Dictionary to store loop state for each server
        self.playback_times = {}
        self.twenty_four_seven = {}
        self.FFMPEG_OPTIONS = {
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            'options': '-vn -af "aresample=44100:filter_size=64:phase_shift=8"',
        }

        self.ydl_opts = {
            'format': 'bestaudio',
            'noplaylist': True,
            'quiet': True,
            'extract_flat': False,
            'socket_timeout': 10,
            'retries': 5,
            'nocheckcertificate': True,
            'buffersize': 16384,
            'format_sort': ['abr'],
        }
        self.youtube_api_key = youtube_api_key
        self.playlists_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'playlists')
        self.INITIAL_SONGS_TO_LOAD = 3
        self.SONGS_TO_ADD_ON_NEXT = 2

    def get_loop_type(self, guild_id):
        return self.loop_types.get(guild_id)

    def set_loop_type(self, guild_id, loop_type):
        self.loop_types[guild_id] = loop_type

    async def process_temp_queue(self, ctx):
        """Process songs from temp queue and add them to main queue"""
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)

        # Get queue data for this specific server
        queue_data = self.queue.get_queue(guild_id)
        if queue_data['processing_lock']:
            return

        try:
            queue_data['processing_lock'] = True
            songs_to_process = self.queue.get_next_temp_songs(guild_id, self.SONGS_TO_ADD_ON_NEXT)

            # Process songs concurrently
            fetch_tasks = [self.fetch_youtube_url(song, guild_id) for song in songs_to_process]

            results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

            for song, result in zip(songs_to_process, results):
                if isinstance(result, Exception):
                    ctxlog.warning(
                        f'Failed to process song from temp queue: {song}, Error: {result}'
                    )
                    continue

                url, title, duration = result
                if url:
                    self.queue.add_song(guild_id, (url, title, duration))
                    ctxlog.info(f'Processed song from temp queue: {title}')
                else:
                    ctxlog.warning(f'Failed to process song from temp queue: {song}')

        except Exception as e:
            ctxlog.error(f'Error processing temp queue: {e}')
        finally:
            # Make sure to release the lock for this specific server
            queue_data['processing_lock'] = False

    def get_current_song(self, guild_id):
        """Get current song for specific server"""
        return self.queue.current_song(guild_id)

    def _fetch_youtube_url_sync(self, query, guild_id):
        """Synchronous version of fetch_youtube_url to run in thread pool"""
        with YoutubeDL(self.ydl_opts) as ydl:
            try:
                search_query = f'ytsearch:{query}' if not query.startswith('http') else query
                log.debug(f"Fetching '{search_query}' from YouTube.")
                info = ydl.extract_info(search_query, download=False)

                if 'entries' in info:
                    video = info['entries'][0]
                else:
                    video = info

                # Store URL info for specific server

                duration = video.get('duration', 0)
                log.success('Found video!')
                log.info(
                    f"Video URL: {video.get('url')}, Video TITLE: {video.get('title', 'Unknown Title')}, Duration: {duration}"
                )
                return video.get('url'), video.get('title', 'Unknown Title'), duration

            except Exception as e:
                log.error(f'Error fetching YouTube URL: {e}')
                return None, None, None

    async def fetch_youtube_url(self, query, guild_id):
        """Asynchronous wrapper for YouTube URL fetching"""
        try:
            # Run the synchronous function in the thread pool
            result = await asyncio.get_event_loop().run_in_executor(
                self.thread_pool,
                functools.partial(self._fetch_youtube_url_sync, query, guild_id),
            )
            return result
        except Exception as e:
            log.error(f'Error in async YouTube fetch: {e}')
            return None, None, None

    async def refresh_url(self, title, guild_id):
        """Fetch fresh URL for a song using its title"""
        log.debug(f'Refreshing URL for song: {title}')
        try:
            with YoutubeDL(self.ydl_opts) as ydl:
                # Directly search for the song using its title
                info = ydl.extract_info(f'ytsearch:{title}', download=False)

                if 'entries' in info:
                    video = info['entries'][0]  # Get the first search result
                    url = video.get('url')
                    duration = video.get('duration', 0)

                    log.success(f'Successfully fetched new URL for: {title}')
                    return url, title, duration

        except Exception as e:
            log.error(f'Error fetching new URL for {title}: {e}')
        return None, None, None

    async def play_audio(self, ctx, url, title, duration, after=None):
        """Helper function to handle audio playback with error recovery"""
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info("Function 'play_audio' invoked. ")
        try:
            if ctx.voice_client:
                ctx.voice_client.play(
                    discord.FFmpegPCMAudio(url, **self.FFMPEG_OPTIONS), after=after
                )

                self.playback_times[guild_id] = time.time()
                ctxlog.success('Playback started.')
                return True
        except Exception as e:
            ctxlog.error(f'Playback error: {e}')
            # Try to refresh the URL and play again
            ctxlog.debug('Trying to refresh URL...')
            new_url, _, new_duration = await self.refresh_url(title, guild_id)
            if new_url:
                try:
                    ctx.voice_client.play(
                        discord.FFmpegPCMAudio(new_url, **self.FFMPEG_OPTIONS),
                        after=after,
                    )
                    ctxlog.success(f'URL refreshed successfully: {new_url}')
                    return True
                except Exception as e2:
                    ctxlog.error(f'Error after URL refresh: {e2}')
        return False

    async def play_next_song(self, ctx):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.debug('play_next_song called')
        # Don't proceed if we're in the middle of a seek operation
        if hasattr(self, 'seeking') and guild_id in self.seeking:
            ctxlog.debug('Skipping play_next_song due to seek operation.')
            return

        try:
            # First determine and play the next song
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
                ctxlog.info(f"Current index from play_next_song: {queue_data["current_index"]}")
                url, title, duration = current_song

                # Try to refresh URL if needed
                max_retries = 3
                retry_count = 0
                while retry_count < max_retries:
                    try:
                        # Test if URL is still valid
                        async with aiohttp.ClientSession() as session:
                            async with session.head(url) as response:
                                if response.status != 200:
                                    raise Exception('URL expired')
                        break
                    except Exception:
                        ctxlog.warning(
                            f'URL expired, attempting refresh (attempt {retry_count + 1})'
                        )
                        new_url, _, new_duration = await self.refresh_url(title, guild_id)
                        if new_url:
                            url = new_url
                            duration = new_duration
                            break

                        retry_count += 1
                        if retry_count < max_retries:
                            await asyncio.sleep(1)  # Wait before retrying

                if retry_count == max_retries:
                    ctxlog.error('Failed to refresh URL after maximum retries')
                    await ctx.send('Failed to play the current song, skipping...')
                    # Adjust the queue index to skip this song
                    queue_data = self.queue.get_queue(guild_id)
                    if queue_data['current_index'] < len(queue_data['queue']) - 1:
                        queue_data['current_index'] += 1
                    await self.play_next_song(ctx)
                    return

                # Check if the voice client is in a channel with members
                voice_channel = ctx.voice_client.channel
                member_count = len([m for m in voice_channel.members if not m.bot])

                # Only disconnect if 24/7 mode is disabled and channel is empty
                if member_count == 0 and not self.twenty_four_seven.get(guild_id, False):
                    ctxlog.info(f'No users in voice channel for guild {guild_id}, disconnecting.')
                    # Clean up
                    if guild_id in self.playback_times:
                        del self.playback_times[guild_id]
                    queue_data = self.queue.get_queue(guild_id)
                    queue_data['queue'] = []
                    queue_data['current_index'] = -1
                    queue_data['temp_queue'] = []

                    await ctx.voice_client.disconnect()
                    return

                if ctx.voice_client.is_connected():
                    ctxlog.debug(f'Current URL: {url}')
                    success = await self.play_audio(
                        ctx,
                        url,
                        title,
                        duration,
                        after=lambda e: self.bot.loop.create_task(self.play_next_song(ctx)),
                    )

                    if success:
                        await ctx.send(f'Now playing: {title} ({format_duration(duration)})')
                        try:
                            if voice_channel:  # Add check for voice_channel
                                await voice_channel.set_status(status=f'▶️ {title}')
                        except Exception as status_error:
                            ctxlog.warning(f'Could not update status: {status_error}')

                        # Process more songs from temp queue if available
                        if self.queue.get_temp_queue_size(guild_id) > 0:
                            asyncio.create_task(self.process_temp_queue(ctx))
                    else:
                        await ctx.send('Failed to play the current song, skipping...')
                        await self.play_next_song(ctx)
                else:
                    ctxlog.warning(f'Voice client disconnected in guild {guild_id}')
                    return

            else:
                if ctx.voice_client and not ctx.voice_client.is_playing():
                    # Process any remaining songs in temp queue before disconnecting
                    if self.queue.get_temp_queue_size(guild_id) > 0:
                        await self.process_temp_queue(ctx)

                    # Clear queues before disconnecting
                    queue_data = self.queue.get_queue(guild_id)
                    queue_data['queue'] = []
                    queue_data['temp_queue'] = []
                    queue_data['current_index'] = -1

                    # Clean up server-specific states
                    if guild_id in self.loop_types:
                        del self.loop_types[guild_id]
                    if guild_id in self.playback_times:
                        del self.playback_times[guild_id]

                    if ctx.voice_client:  # Add check before disconnecting
                        await ctx.voice_client.disconnect()

        except Exception as e:
            ctxlog.error(f'Error in play_next_song: {e}')
            ctxlog.error(traceback.format_exc())

            # Attempt to clean up on error
            try:
                if ctx.voice_client:
                    await ctx.voice_client.disconnect()

                queue_data = self.queue.get_queue(guild_id)
                queue_data['queue'] = []
                queue_data['temp_queue'] = []
                queue_data['current_index'] = -1

                if guild_id in self.loop_types:
                    del self.loop_types[guild_id]
                if guild_id in self.playback_times:
                    del self.playback_times[guild_id]

            except Exception as cleanup_error:
                ctxlog.error(f'Error during cleanup: {cleanup_error}')

    @commands.slash_command(name='play_music', description='Play music in your voice channel.')
    async def play_music(self, ctx: discord.ApplicationContext, query: str):
        """
        Play music in the voice channel.
        Parameters:
            ctx: The command context
            query: The search query or URL for the song
        """
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} requested to play: {query}')

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

            # Fetch the song information
            url, title, duration = await self.fetch_youtube_url(query, guild_id)
            if not url:
                await ctx.respond(f"Failed to fetch the song '{query}' from YouTube.")
                ctxlog.warning(f'Failed to fetch song info for query: {query}')
                return

            duration_str = format_duration(duration)

            # Add the song to the server's queue
            self.queue.add_song(guild_id, (url, title, duration))
            await ctx.respond(f'Added {title} ({duration_str}) to the queue.')
            ctxlog.info(f'Added {title} to the queue for guild {guild_id}')

            # Handle voice client connection
            try:
                if ctx.voice_client is None:
                    await voice_channel.connect()
                    await asyncio.sleep(0.5)  # Small delay to ensure connection is stable
                    # If 24/7 mode was enabled but bot disconnected, re-enable it
                    if guild_id in self.twenty_four_seven:
                        self.twenty_four_seven[guild_id] = True
                    ctxlog.info(f'Connected to voice channel in guild {guild_id}')

                elif ctx.voice_client.channel != voice_channel:
                    # Move to the new channel if user is in a different one
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
                        url, title, duration = current_song
                        success = await self.play_audio(
                            ctx,
                            url,
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
                    if ctx.voice_client:
                        await ctx.voice_client.disconnect()
                    await ctx.send('An error occurred while trying to play the song.')

                    # Clean up server-specific states on error
                    queue_data = self.queue.get_queue(guild_id)
                    queue_data['queue'] = []
                    queue_data['temp_queue'] = []
                    queue_data['current_index'] = -1

                    if guild_id in self.loop_types:
                        del self.loop_types[guild_id]

        except Exception as e:
            ctxlog.error(f'Unexpected error in play_music: {e}')
            ctxlog.error(traceback.format_exc())
            await ctx.send('An unexpected error occurred. Please try again later.')

            # Attempt to clean up on critical error
            try:
                if ctx.voice_client:
                    await ctx.voice_client.disconnect()

                queue_data = self.queue.get_queue(guild_id)
                queue_data['queue'] = []
                queue_data['temp_queue'] = []
                queue_data['current_index'] = -1

                if guild_id in self.loop_types:
                    del self.loop_types[guild_id]

            except Exception as cleanup_error:
                ctxlog.error(f'Error during cleanup: {cleanup_error}')

    @commands.slash_command(name='add_to_queue', description='Add a music file to the queue.')
    async def add_to_queue(self, ctx: discord.ApplicationContext, query: str):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used add_to_queue command with query: {query}')

        await ctx.defer()

        try:
            url, title, duration = await self.fetch_youtube_url(query, guild_id)
            if not url:
                await ctx.respond('Failed to fetch the song from YouTube.')
                ctxlog.warning(f'Failed to fetch song for query: {query}')
                return

            self.queue.add_song(guild_id, (url, title, duration))
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
                url, song_title, total_duration = current_song

                # Fetch thumbnail using yt-dlp
                try:
                    with YoutubeDL(self.ydl_opts) as ydl:
                        # Use webpage_url from stored info or search for the song
                        info = ydl.extract_info(f'ytsearch:{song_title}', download=False)
                        if 'entries' in info:
                            thumbnail_url = info['entries'][0].get('thumbnail')
                        else:
                            thumbnail_url = info.get('thumbnail')
                        ctxlog.debug(f'Fetched thumbnail URL: {thumbnail_url}')
                except Exception as thumb_error:
                    ctxlog.warning(f'Could not fetch thumbnail: {thumb_error}')
                    thumbnail_url = None

                # Calculate current timestamp
                if guild_id in self.playback_times and ctx.voice_client.is_playing():
                    elapsed_time = int(time.time() - self.playback_times[guild_id])
                    current_timestamp = min(elapsed_time, total_duration)
                else:
                    current_timestamp = 0

                # Create embed for better presentation
                embed = discord.Embed(
                    title='🎵 Now Playing',
                    description=song_title,
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow(),
                )

                # Set thumbnail if available
                if thumbnail_url:
                    embed.set_thumbnail(url=thumbnail_url)

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
                    f"Could not find current song in function 'nowplaying' " f'for guild {guild_id}'
                )
                await ctx.respond('Error retrieving current song information.')

        except Exception as e:
            ctxlog.error(f'Error in nowplaying command for guild {guild_id}: {e}')
            ctxlog.error(traceback.format_exc())
            await ctx.respond('An error occurred while getting the current song information.')

    #
    # @commands.slash_command(name='nowplaying', description='Display the currently playing song.')
    # async def nowplaying(self, ctx: discord.ApplicationContext):
    #     guild_id = ctx.guild.id
    #     ctxlog = get_context_logger(ctx)
    #     ctxlog.info(f'{ctx.author.name} used command nowplaying in guild {guild_id}')
    #
    #     try:
    #         if not ctx.voice_client or not self.get_current_song(guild_id):
    #             await ctx.respond('No song is currently playing.')
    #             ctxlog.warning(f'No song playing currently in guild {guild_id}')
    #             return
    #
    #         current_song = self.get_current_song(guild_id)
    #         if current_song:
    #             song_title = current_song[1]
    #             total_duration = current_song[2]
    #
    #             # Calculate current timestamp
    #             if guild_id in self.playback_times and ctx.voice_client.is_playing():
    #                 elapsed_time = int(time.time() - self.playback_times[guild_id])
    #                 current_timestamp = min(elapsed_time, total_duration)
    #             else:
    #                 current_timestamp = 0
    #
    #             # Create embed for better presentation
    #             embed = discord.Embed(
    #                 title='🎵 Now Playing',
    #                 description=song_title,
    #                 color=discord.Color.blue(),
    #                 timestamp=discord.utils.utcnow(),
    #             )
    #
    #             # Add timestamp field
    #             embed.add_field(
    #                 name='Time',
    #                 value=f'`{format_duration(current_timestamp)}/{format_duration(total_duration)}`',
    #                 inline=False,
    #             )
    #
    #             # Create progress bar
    #             bar_length = 20
    #             progress = current_timestamp / total_duration if total_duration > 0 else 0
    #             filled = int(bar_length * progress)
    #             progress_bar = '▰' * filled + '▱' * (bar_length - filled)
    #
    #             embed.add_field(
    #                 name='Progress',
    #                 value=f'`{progress_bar}` {(progress * 100):.1f}%',
    #                 inline=False,
    #             )
    #
    #             # Get loop status and create footer text
    #             loop_type = self.get_loop_type(guild_id)
    #             if loop_type == 'all':
    #                 footer_text = '🔁 Loop: ALL'
    #             elif loop_type == 'once':
    #                 footer_text = '🔂 Loop: ONCE'
    #             else:
    #                 footer_text = '➡️ Loop: OFF'
    #
    #             embed.set_footer(text=footer_text)
    #
    #             await ctx.respond(embed=embed)
    #             ctxlog.success(
    #                 f'Now playing {song_title} at {current_timestamp}/{total_duration} '
    #                 f'in guild {guild_id}'
    #             )
    #         else:
    #             ctxlog.error(
    #                 f"Could not find current song in function 'nowplaying' " f'for guild {guild_id}'
    #             )
    #             await ctx.respond('Error retrieving current song information.')
    #
    #     except Exception as e:
    #         ctxlog.error(f'Error in nowplaying command for guild {guild_id}: {e}')
    #         ctxlog.error(traceback.format_exc())
    #         await ctx.respond('An error occurred while getting the current song information.')
    #
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
        else:
            past_songs = ''
            for i in range(0, queue_data['current_index']):
                past_songs += queue_data['queue'][i][1] + '\n'
            if len(past_songs) > 2000:
                chunks = [past_songs[j : j + 2000] for j in range(0, len(past_songs), 2000)]
                for chunk in chunks:
                    await ctx.send(chunk)
                ctxlog.success('Past songs displayed with chunking.')
            else:
                ctxlog.success('Past songs displayed without chunking.')
                await ctx.respond(past_songs)

    @commands.slash_command(name='get_current_index', description='Get the current queue index.')
    async def get_current_index(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command get_current_index in guild {guild_id}')
        queue_data = self.queue.get_queue(guild_id)
        current_index = queue_data['current_index']
        await ctx.respond(f'Current index: {current_index}')

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

            # Adjust index to play previous song
            queue_data['current_index'] -= 2
            if queue_data['current_index'] == -1:
                queue_data['current_index'] = 0

            ctxlog.debug(f"Current index after manual update: {queue_data['current_index']}")

            if ctx.voice_client and ctx.voice_client.is_playing():
                ctx.voice_client.stop()
                ctxlog.success(f'Current song stopped successfully in guild {guild_id}')
                await ctx.respond('Playing previous song.')
            else:
                # If nothing is playing, start playback
                await self.play_next_song(ctx)
                await ctx.respond('Started playing previous song.')

        except Exception as e:
            ctxlog.error(f'Error in previous command: {e}')
            await ctx.respond('An error occurred while trying to play the previous song.')

            # Attempt to clean up on error
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

            # Get current song info for better user feedback
            current_song = self.get_current_song(guild_id)
            if current_song:
                current_title = current_song[1]
                ctx.voice_client.pause()
                await ctx.respond(f'Paused: {current_title}')

                # Update voice channel status if applicable
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

            # Attempt to recover playback state if needed
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
            self.playback_times[guild_id] = (
                time.time() + self.playback_times[guild_id]
            )  # Restore the elapsed time
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
                    current_title = current_song[1]
                    duration = current_song[2]

                    ctx.voice_client.resume()
                    await ctx.respond(
                        f'Resumed playing: {current_title} ({format_duration(duration)})'
                    )

                    # Update voice channel status
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

            # Attempt to recover playback state if needed
            try:
                if ctx.voice_client and ctx.voice_client.is_paused():
                    ctx.voice_client.resume()
                    ctxlog.info(f'Recovered resume state for guild {guild_id}')
            except Exception as recovery_error:
                ctxlog.error(f'Error during state recovery: {recovery_error}')

            # Check queue state
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
            temp_queue_size = len(queue_data['temp_queue'])

            queue_data['queue'] = []
            queue_data['current_index'] = -1
            queue_data['temp_queue'] = []
            queue_data['processing_lock'] = False

            ctxlog.debug(
                f'Cleared queue for guild {guild_id} '
                f'(Cleared {queue_size} songs from main queue, '
                f'{temp_queue_size} from temp queue)'
            )

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
            response_msg = (
                '🛑 Music stopped and queue cleared:\n'
                f'• Cleared {queue_size} songs from queue\n'
                f'• Cleared {temp_queue_size} songs from temp queue\n'
                '• Disconnected from voice channel'
            )

            await ctx.respond(response_msg)
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
                queue_data['temp_queue'] = []
                queue_data['processing_lock'] = False

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
            current_title = current_song[1] if current_song else 'Unknown'
            current_duration = current_song[2] if current_song else 0
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
            embed.add_field(name='⎯' * 50, value='', inline=False)

            # Add upcoming songs
            if next_songs:
                upcoming_description = []
                total_duration = 0
                for i, (_, title, duration) in enumerate(next_songs, 1):
                    total_duration += duration
                    time_until = sum(song[2] for song in next_songs[: i - 1])
                    upcoming_description.append(
                        f'`{i}.` **{title}**\n'
                        f'┗ Duration: {format_duration(duration)} • Plays in: {format_duration(time_until)}'
                    )

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

            # Set thumbnail
            embed.set_thumbnail(url=('attachment://queue_image.webp'))

            # Set footer with current position
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

    # @commands.slash_command(
    #     name='display_queue',
    #     description='Display the next 10 songs and total songs in queue',
    # )
    # async def display_queue(self, ctx: discord.ApplicationContext):
    #     ctxlog = get_context_logger(ctx)
    #     ctxlog.info(f'{ctx.author.name} used command display_queue')
    #     guild_id = ctx.guild.id
    #     queue_data = self.queue.get_queue(guild_id)
    #     if len(queue_data['queue']) == 0:
    #         await ctx.respond('The queue is currently empty.')
    #         return
    #     try:
    #         next_songs = queue_data['queue'][
    #             queue_data['current_index'] + 1 : queue_data['current_index'] + 11
    #         ]
    #     except IndexError:
    #         next_songs = queue_data['queue'][queue_data['current_index'] :]
    #     next_song_titles = [song_info[1] for song_info in next_songs]
    #     next_song_durations = [song_info[2] for song_info in next_songs]
    #     n = 10
    #     if len(next_song_titles) < 10:
    #         n = len(next_song_titles)
    #     queue_message = f'Next {n} songs in queue:\n'
    #     for i in range(len(next_song_titles)):
    #         queue_message += (
    #             f'\n{i}. ({format_duration(next_song_durations[i])}) | {next_song_titles[i]}'
    #         )
    #     total_songs = len(queue_data['queue'][queue_data['current_index'] :])
    #     queue_message += f'\n\nTotal songs in queue: {total_songs}'
    #     await ctx.respond(queue_message)
    #     ctxlog.success('Sent display_queue successfully!')

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

            # Also shuffle any songs in the temp queue for this server
            temp_songs = queue_data['temp_queue']
            if temp_songs:
                random.shuffle(temp_songs)
                queue_data['temp_queue'] = temp_songs
                ctxlog.info(f'Shuffled {len(temp_songs)} songs in temp queue for guild {guild_id}')

            ctxlog.success(f'Shuffled {len(remaining_songs)} songs in queue for guild {guild_id}')

            # Prepare preview of upcoming songs
            next_songs = queue_data['queue'][queue_data['current_index'] + 1 :]
            preview_count = min(5, len(next_songs))  # Show up to 5 next songs

            if preview_count > 0:
                next_songs_message = 'Next songs after shuffle:\n'
                for i, song in enumerate(next_songs[:preview_count], 1):
                    _, title, duration = song
                    next_songs_message += f'{i}. ({format_duration(duration)}) | {title}\n'

                await ctx.respond('Shuffled the remaining songs in the queue.')
                await ctx.followup.send(next_songs_message)

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

        finally:
            # Ensure processing lock is released if it exists
            try:
                queue_data = self.queue.get_queue(guild_id)
                if 'processing_lock' in queue_data:
                    queue_data['processing_lock'] = False
            except Exception as cleanup_error:
                ctxlog.error(f'Error during cleanup: {cleanup_error}')

    @commands.slash_command(name='loop_once', description='Loop the current song')
    async def loop_once(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        self.set_loop_type(guild_id, 'once')
        await ctx.respond('Enabled loop for the current song.')

    @commands.slash_command(name='loop_all', description='Loop all songs in queue')
    async def loop_all(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        self.set_loop_type(guild_id, 'all')
        await ctx.respond('Enabled loop for the queue.')

    @commands.slash_command(name='loop_off', description='Disable looping')
    async def loop_off(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        self.set_loop_type(guild_id, None)
        await ctx.respond('Disabled looping.')

    @commands.slash_command(
        name='available_playlists', description='Display all available playlists'
    )
    async def available_playlists(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command available_playlists in guild {guild_id}')

        await ctx.defer()  # Defer response for potentially large playlist lists

        try:
            # Get all .txt files from the playlists directory
            playlist_files = [
                f
                for f in os.listdir(self.playlists_dir)
                if f.endswith('.txt') and os.path.isfile(os.path.join(self.playlists_dir, f))
            ]

            if not playlist_files:
                await ctx.respond('No playlists available.')
                ctxlog.warning(f'No playlist files found in directory for guild {guild_id}')
                return

            # Sort playlists alphabetically
            playlist_files.sort()

            # Create formatted messages with playlist information
            playlists_message = '📂 Available Playlists:\n\n'
            detailed_playlists = []

            for i, playlist in enumerate(playlist_files, 1):
                playlist_path = os.path.join(self.playlists_dir, playlist)
                playlist_name = os.path.splitext(playlist)[0]

                try:
                    # Get playlist size (number of songs)
                    with open(playlist_path, 'r', encoding='utf-8') as f:
                        song_count = sum(1 for line in f if line.strip())

                    # Get playlist file size
                    file_size = os.path.getsize(playlist_path) / 1024  # Convert to KB

                    detailed_playlists.append(
                        f'{i}. {playlist_name}\n'
                        f'   • Songs: {song_count}\n'
                        f'   • Size: {file_size:.1f}KB\n'
                    )
                except Exception as playlist_error:
                    ctxlog.warning(f'Error reading playlist {playlist_name}: {playlist_error}')
                    detailed_playlists.append(f'{i}. {playlist_name}\n')

            # Split into chunks if the message is too long
            chunks = []
            current_chunk = playlists_message

            for playlist_info in detailed_playlists:
                if len(current_chunk + playlist_info) > 1900:  # Discord limit safety
                    chunks.append(current_chunk)
                    current_chunk = playlists_message + playlist_info
                else:
                    current_chunk += playlist_info

            if current_chunk:
                chunks.append(current_chunk)

            # Add summary footer to last chunk
            chunks[-1] += f'\nTotal playlists: {len(playlist_files)}'

            # Send chunks as separate messages
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await ctx.respond(chunk)
                else:
                    await ctx.followup.send(chunk)

            ctxlog.success(
                f'Successfully displayed {len(playlist_files)} playlists '
                f'in {len(chunks)} messages for guild {guild_id}'
            )

        except Exception as e:
            error_message = f'Error accessing playlists: {str(e)}'
            ctxlog.error(f'{error_message} in guild {guild_id}')
            ctxlog.error(traceback.format_exc())
            await ctx.respond('Unable to access playlists at this time. Please try again later.')

            # Log system information for debugging
            try:
                ctxlog.debug(f'Playlists directory path: {self.playlists_dir}')
                ctxlog.debug(f'Directory exists: {os.path.exists(self.playlists_dir)}')
                ctxlog.debug(f'Directory is readable: {os.access(self.playlists_dir, os.R_OK)}')
            except Exception as debug_error:
                ctxlog.error(f'Error gathering debug information: {debug_error}')

    @commands.slash_command(name='play_playlist', description='Play songs from a playlist file')
    async def play_playlist(self, ctx: discord.ApplicationContext, playlist_name: str):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used play_playlist command with playlist: {playlist_name}')
        await ctx.defer()

        if ctx.author.voice is None:
            ctxlog.warning('Attempted to use play_playlist command without joining voice channel.')
            await ctx.respond('You need to join a voice channel first.')
            return

        voice_channel = ctx.author.voice.channel
        playlist_path = os.path.join(self.playlists_dir, f'{playlist_name}.txt')

        if not os.path.exists(playlist_path):
            await ctx.respond(f"Playlist '{playlist_name}' doesn't exist.")
            ctxlog.warning(f'Playlist not found: {playlist_path}')
            return
        ctxlog.info('Playlist path established')
        try:
            with open(playlist_path, 'r', encoding='utf-8') as file:
                songs = [line.strip() for line in file if line.strip()]

            if not songs:
                await ctx.respond(f"Playlist '{playlist_name}' is empty.")
                return

            # Add all songs to temp queue for this specific server
            random.shuffle(songs)
            self.queue.add_to_temp_queue(guild_id, songs)
            ctxlog.info(f'Added all songs to the temp queue from playlist: {playlist_name}')
            total_songs = len(songs)

            # Connect to voice channel if needed
            if ctx.voice_client is None:
                await voice_channel.connect()
                await asyncio.sleep(0.5)

            # Process first song immediately if nothing is playing
            if not ctx.voice_client.is_playing():
                first_song = self.queue.get_next_temp_songs(guild_id, 1)[0]
                ctxlog.info(f'First song: {first_song}')
                url, title, duration = await self.fetch_youtube_url(first_song, guild_id)

                if url:
                    self.queue.add_song(guild_id, (url, title, duration))
                    ctx.voice_client.play(
                        discord.FFmpegPCMAudio(url, **self.FFMPEG_OPTIONS),
                        after=lambda e: self.bot.loop.create_task(self.play_next_song(ctx)),
                    )
                    self.playback_times[guild_id] = time.time()
                    await ctx.send(f'Now playing: {title} ({format_duration(duration)})')
                    await voice_channel.set_status(status=f'▶️ {title}')
                    ctxlog.success(f'Started playing: {title}')

            # Process initial batch of songs concurrently
            initial_songs = self.queue.get_next_temp_songs(guild_id, self.INITIAL_SONGS_TO_LOAD)
            await ctx.respond(f'Loading playlist: "{playlist_name}" with {total_songs} songs.')

            # Fetch initial songs concurrently
            fetch_tasks = [self.fetch_youtube_url(song, guild_id) for song in initial_songs]
            results = await asyncio.gather(*fetch_tasks)

            processed_count = 0
            for url, title, duration in results:
                if url:
                    self.queue.add_song(guild_id, (url, title, duration))
                    processed_count += 1
                    ctxlog.info(f'Added to queue: {title}')

            remaining = self.queue.get_temp_queue_size(guild_id)
            await ctx.send(
                f"Added {processed_count} songs to queue. {remaining} songs remaining in playlist '{playlist_name}'. "
                f'More songs will be added automatically as the playlist progresses.'
            )

        except Exception as e:
            error_msg = f'Error processing playlist: {str(e)}'
            ctxlog.error(error_msg)
            await ctx.respond(error_msg)

    @commands.slash_command(name='create_playlist', description='Create a new empty playlist')
    async def create_playlist(self, ctx: discord.ApplicationContext, playlist_name: str):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used create_playlist command with name: {playlist_name}')

        # Clean the playlist name to prevent directory traversal and ensure it's safe
        playlist_name = ''.join(c for c in playlist_name if c.isalnum() or c in (' ', '-', '_'))
        playlist_path = os.path.join(self.playlists_dir, f'{playlist_name}.txt')

        try:
            # Check if playlist already exists
            if os.path.exists(playlist_path):
                await ctx.respond(f"A playlist named '{playlist_name}' already exists.")
                ctxlog.warning(f'Attempted to create existing playlist: {playlist_name}')
                return

            # Create the playlists directory if it doesn't exist
            os.makedirs(self.playlists_dir, exist_ok=True)

            # Create the empty playlist file
            with open(playlist_path, 'w', encoding='utf-8') as _:
                pass  # Creates an empty file

            await ctx.respond(f"Successfully created playlist '{playlist_name}'.")
            ctxlog.success(f'Created new playlist: {playlist_name}')

        except Exception as e:
            error_msg = f'Error creating playlist: {str(e)}'
            ctxlog.error(error_msg)
            await ctx.respond('Failed to create playlist. Please try again.')

    @commands.slash_command(
        name='show_playlist', description='Display the contents of a specific playlist'
    )
    async def show_playlist(self, ctx: discord.ApplicationContext, playlist_name: str):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used show_playlist command for playlist: {playlist_name}')

        # Build the playlist path
        playlist_path = os.path.join(self.playlists_dir, f'{playlist_name}.txt')

        # Check if playlist exists
        if not os.path.exists(playlist_path):
            await ctx.respond(f"Playlist '{playlist_name}' doesn't exist.")
            ctxlog.warning(f'Attempted to show non-existent playlist: {playlist_name}')
            return

        try:
            # Read the playlist file
            with open(playlist_path, 'r', encoding='utf-8') as file:
                songs = [line.strip() for line in file if line.strip()]

            if not songs:
                await ctx.respond(f"Playlist '{playlist_name}' is empty.")
                ctxlog.info(f'Displayed empty playlist: {playlist_name}')
                return

            # Create the message
            message = f"Contents of playlist '{playlist_name}':\n"
            for i, song in enumerate(songs, 1):
                message += f'{i}. {song}\n'

            # Handle messages that might exceed Discord's character limit
            if len(message) > 2000:
                # Split into chunks of 2000 characters, trying to break at newlines
                chunks = []
                current_chunk = ''

                for line in message.split('\n'):
                    if len(current_chunk) + len(line) + 1 > 2000:
                        chunks.append(current_chunk)
                        current_chunk = line + '\n'
                    else:
                        current_chunk += line + '\n'

                if current_chunk:
                    chunks.append(current_chunk)

                # Send chunks
                await ctx.respond(chunks[0])
                for chunk in chunks[1:]:
                    await ctx.followup.send(chunk)
            else:
                await ctx.respond(message)

            ctxlog.success(
                f'Successfully displayed playlist: {playlist_name} with {len(songs)} songs'
            )

        except Exception as e:
            error_msg = f'Error reading playlist: {str(e)}'
            ctxlog.error(error_msg)
            await ctx.respond('Failed to read playlist. Please try again.')

    @commands.slash_command(
        name='add_song_to_playlist', description='Add a song to an existing playlist'
    )
    async def add_song_to_playlist(
        self, ctx: discord.ApplicationContext, playlist_name: str, song: str
    ):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(
            f'{ctx.author.name} used add_song_to_playlist command for playlist: {playlist_name}'
        )

        # Build the playlist path
        playlist_path = os.path.join(self.playlists_dir, f'{playlist_name}.txt')

        # Check if playlist exists
        if not os.path.exists(playlist_path):
            await ctx.respond(f"Playlist '{playlist_name}' doesn't exist.")
            ctxlog.warning(f'Attempted to add song to non-existent playlist: {playlist_name}')
            return

        try:
            # Read existing content to check if we need a newline
            with open(playlist_path, 'r', encoding='utf-8') as file:
                content = file.read()

            # Append the song to the playlist file
            with open(playlist_path, 'a', encoding='utf-8') as file:
                # Add newline if file is not empty and doesn't end with newline
                if content and not content.endswith('\n'):
                    file.write('\n')
                file.write(f'{song}\n')

            await ctx.respond(f"Successfully added '{song}' to playlist '{playlist_name}'.")
            ctxlog.success(f'Added song to playlist {playlist_name}: {song}')

        except Exception as e:
            error_msg = f'Error adding song to playlist: {str(e)}'
            ctxlog.error(error_msg)
            await ctx.respond('Failed to add song to playlist. Please try again.')

    @commands.slash_command(
        name='display_temp_queue',
        description='Display all songs waiting to be processed in the temporary queue',
    )
    async def display_temp_queue(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used display_temp_queue command in guild {guild_id}')
        await ctx.defer()

        try:
            temp_songs = self.queue.get_temp_queue_songs(guild_id)
            queue_data = self.queue.get_queue(guild_id)

            if not temp_songs:
                await ctx.respond('No songs currently in the temporary queue.')
                ctxlog.info(f'No songs in temp queue for guild {guild_id}')
                return

            # Get current processing status
            is_processing = queue_data.get('processing_lock', False)

            # Create formatted message with status and statistics
            message = [
                '📋 **Temporary Queue Status:**',
                f'• Total songs waiting: {len(temp_songs)}',
                f"• Processing status: {'🔄 Processing' if is_processing else '⏸️ Idle'}",
                '\n**Songs Waiting to be Processed:**',
            ]

            for i, title in temp_songs:
                message.append(f'`{i}.` {title}')

            # Add estimated processing time (assuming ~2 seconds per song)
            est_time = len(temp_songs) * 2  # rough estimate in seconds
            est_minutes = est_time // 60
            est_seconds = est_time % 60
            message.append(f'\n⏱️ Estimated processing time: {est_minutes}m {est_seconds}s')

            # Split message if it's too long
            formatted_message = '\n'.join(message)
            if len(formatted_message) > 1900:
                chunks = []
                current_chunk = message[:4]  # Keep header in first chunk
                current_length = len('\n'.join(current_chunk))

                for line in message[4:]:  # Start after header
                    if current_length + len(line) + 1 > 1900:
                        # Add chunk info to split messages
                        current_chunk.append('\n(Continued in next message...)')
                        chunks.append('\n'.join(current_chunk))
                        current_chunk = ['(Continued from previous message)', line]
                        current_length = len('\n'.join(current_chunk))
                    else:
                        current_chunk.append(line)
                        current_length += len(line) + 1

                if current_chunk:
                    chunks.append('\n'.join(current_chunk))

                # Send chunks with progress indicator
                total_chunks = len(chunks)
                for i, chunk in enumerate(chunks, 1):
                    if i == 1:
                        await ctx.respond(f'{chunk}\n\n(Page {i}/{total_chunks})')
                    else:
                        await ctx.followup.send(f'{chunk}\n\n(Page {i}/{total_chunks})')
                    ctxlog.debug(f'Sent chunk {i}/{total_chunks} for guild {guild_id}')
            else:
                await ctx.respond(formatted_message)

            ctxlog.success(f'Displayed temp queue ({len(temp_songs)} songs) for guild {guild_id}')

        except Exception as e:
            error_msg = f'Error displaying temp queue: {str(e)}'
            ctxlog.error(f'{error_msg} in guild {guild_id}')
            ctxlog.error(traceback.format_exc())

            await ctx.respond(
                'An error occurred while displaying the temporary queue. ' 'Please try again later.'
            )

            # Log queue state for debugging
            try:
                queue_data = self.queue.get_queue(guild_id)
                ctxlog.debug(
                    f"Queue state for guild {guild_id}: "
                    f"temp_queue_size={len(queue_data['temp_queue'])}, "
                    f"processing_lock={queue_data.get('processing_lock', False)}"
                )
            except Exception as debug_error:
                ctxlog.error(f'Error gathering debug information: {debug_error}')

    @commands.slash_command(name='skip_multiple', description='Skip multiple songs in the queue.')
    async def skip_multiple(self, ctx: discord.ApplicationContext, number: str):
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

            # Try to convert input to integer
            try:
                skip_count = int(number)
                if skip_count <= 0:
                    await ctx.respond('Please provide a positive number.')
                    ctxlog.warning(f'Invalid skip count provided: {skip_count} in guild {guild_id}')
                    return
            except ValueError:
                await ctx.respond('Please provide a valid number.')
                ctxlog.warning(f'Invalid input provided: {number} in guild {guild_id}')
                return

            # Get queue data for this server
            queue_data = self.queue.get_queue(guild_id)
            current_index = queue_data['current_index']
            queue_length = len(queue_data['queue'])

            # Calculate remaining songs in queue
            remaining_songs = queue_length - (current_index + 1)

            # Check if skip count is valid
            if skip_count > remaining_songs:
                await ctx.respond(
                    f"⚠️ Cannot skip {skip_count} songs. Only {remaining_songs} "
                    f"song{'s' if remaining_songs != 1 else ''} remaining in queue."
                )
                ctxlog.warning(
                    f'Attempted to skip more songs than available in guild {guild_id}: '
                    f'{skip_count} > {remaining_songs}'
                )
                return

            # Store current and target songs for message
            current_song = self.get_current_song(guild_id)
            current_title = current_song[1] if current_song else 'Unknown'

            target_index = current_index + skip_count
            target_song = queue_data['queue'][target_index] if target_index < queue_length else None
            target_title = target_song[1] if target_song else 'Unknown'

            # Adjust the current_index before stopping
            queue_data['current_index'] += (
                skip_count - 1
            )  # -1 because play_next_song increments by 1

            # Stop current song which will trigger play_next_song
            ctxlog.info(f'Stopping current song in guild {guild_id}...')
            ctx.voice_client.stop()

            # Prepare detailed response message
            response = (
                f"⏭️ Skipped {skip_count} song{'s' if skip_count != 1 else ''}\n"
                f"• From: {current_title}\n"
                f"• To: {target_title}\n"
                f"• Remaining in queue: {remaining_songs - skip_count}"
            )

            await ctx.respond(response)
            ctxlog.success(
                f"Successfully skipped {skip_count} songs in guild {guild_id}. "
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
    async def jump(self, ctx: discord.ApplicationContext, number: str):
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

            # Try to convert input to integer
            try:
                jump_index = int(number)
            except ValueError:
                await ctx.respond('Please provide a valid number.')
                ctxlog.warning(f'Invalid input provided: {number} in guild {guild_id}')
                return

            # Get queue data for this server
            queue_data = self.queue.get_queue(guild_id)
            queue_length = len(queue_data['queue'])

            # Check if the index is within queue bounds
            if jump_index < 1 or jump_index > queue_length:
                await ctx.respond(
                    f'⚠️ Invalid song number. Please use a number between 1 and {queue_length}'
                )
                ctxlog.warning(
                    f'Jump index out of range in guild {guild_id}: {jump_index}, '
                    f'queue length: {queue_length}'
                )
                return

            # Get current and target song information
            current_song = self.get_current_song(guild_id)
            current_title = current_song[1] if current_song else 'Unknown'

            target_song = queue_data['queue'][jump_index - 1]
            target_title = target_song[1]
            target_duration = target_song[2]

            # Set the index to one less than target because play_next_song increments by 1
            queue_data['current_index'] = jump_index - 2

            # Stop current song which will trigger play_next_song
            ctxlog.info(f'Stopping current song in guild {guild_id}...')
            ctx.voice_client.stop()

            # Prepare detailed response message
            response = (
                f'⏯️ Jumped to requested song:\n'
                f'• From: {current_title}\n'
                f'• To: {target_title} ({format_duration(target_duration)})\n'
                f'• Position: {jump_index} of {queue_length}'
            )

            await ctx.respond(response)
            ctxlog.success(f'Successfully jumped to index {jump_index} in guild {guild_id}')

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

            await ctx.respond(
                'An error occurred while trying to jump to the requested song. ' 'Please try again.'
            )

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
    async def play_next(self, ctx: discord.ApplicationContext, query: str):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(
            f'{ctx.author.name} used play_next command with query: {query} ' f'in guild {guild_id}'
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

            # Fetch the song info
            url, title, duration = await self.fetch_youtube_url(query, guild_id)
            if not url:
                await ctx.respond(
                    'Failed to fetch the song from YouTube. Please try again with a different query.'
                )
                ctxlog.warning(f'Failed to fetch song info for query: {query} in guild {guild_id}')
                return

            # Get current song info for context
            current_song = self.get_current_song(guild_id)
            current_title = current_song[1] if current_song else 'Unknown'

            # Insert the song right after the current song
            insert_position = queue_data['current_index'] + 1
            queue_data['queue'].insert(insert_position, (url, title, duration))

            # Prepare detailed response message
            next_song_position = insert_position + 1
            next_song = (
                queue_data['queue'][next_song_position][1]
                if next_song_position < len(queue_data['queue'])
                else 'End of queue'
            )

            response = (
                f"🎵 Added song to play next:\n"
                f"• Current: {current_title}\n"
                f"• Next: {title} ({format_duration(duration)})\n"
                f"• Following: {next_song}\n"
                f"• Position: {insert_position + 1} of {len(queue_data['queue'])}"
            )

            await ctx.respond(response)
            ctxlog.success(
                f'Successfully inserted song at position {insert_position} in guild {guild_id}: '
                f'{title}'
            )

            # If this is the only song in queue after current, update temp queue processing
            if (
                insert_position == len(queue_data['queue']) - 1
                and len(queue_data['temp_queue']) > 0
            ):
                asyncio.create_task(self.process_temp_queue(ctx))
                ctxlog.info(
                    f'Triggered temp queue processing for guild {guild_id} '
                    f'after inserting next song'
                )

        except Exception as e:
            error_msg = f'Error in play_next command: {str(e)}'
            ctxlog.error(f'{error_msg} in guild {guild_id}')
            ctxlog.error(traceback.format_exc())

            await ctx.respond('An error occurred while trying to add the song. Please try again.')

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

    @commands.slash_command(
        name='load_songs',
        description='Load a specified number of songs from the temporary queue (max 10).',
    )
    async def load_songs(self, ctx: discord.ApplicationContext, number: str):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(
            f'{ctx.author.name} used load_songs command with number: {number} '
            f'in guild {guild_id}'
        )
        await ctx.defer()

        try:
            # Validate input number
            try:
                count = int(number)
                if count <= 0:
                    await ctx.respond('⚠️ Please provide a positive number.')
                    ctxlog.warning(f'Invalid count provided: {count} in guild {guild_id}')
                    return
                if count > 10:
                    await ctx.respond('⚠️ Maximum number of songs to load is 10.')
                    ctxlog.warning(f'Count exceeded maximum limit: {count} in guild {guild_id}')
                    return
            except ValueError:
                await ctx.respond('⚠️ Please provide a valid number.')
                ctxlog.warning(f'Invalid input provided: {number} in guild {guild_id}')
                return

            # Check if there are songs in temp queue
            temp_queue_size = self.queue.get_temp_queue_size(guild_id)
            if temp_queue_size == 0:
                await ctx.respond('No songs in temporary queue to load.')
                ctxlog.warning(f'Temp queue is empty for guild {guild_id}')
                return

            # Get songs to process
            available_songs = min(count, temp_queue_size)
            songs_to_process = self.queue.get_next_temp_songs(guild_id, available_songs)

            try:
                # Process songs concurrently
                fetch_tasks = [self.fetch_youtube_url(song, guild_id) for song in songs_to_process]
                results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

                processed_count = 0
                failed_count = 0
                processed_songs = []

                for song, result in zip(songs_to_process, results):
                    if isinstance(result, Exception):
                        failed_count += 1
                        ctxlog.warning(
                            f'Failed to process song in guild {guild_id}: {song} - {result}'
                        )
                        continue

                    url, title, duration = result
                    if url:
                        self.queue.add_song(guild_id, (url, title, duration))
                        processed_count += 1
                        processed_songs.append((title, duration))
                        ctxlog.info(f'Added to queue in guild {guild_id}: {title}')
                    else:
                        failed_count += 1

                # Prepare detailed response message
                remaining = self.queue.get_temp_queue_size(guild_id)

                response = [
                    '🎵 **Song Loading Results:**',
                    f'• Requested: {count} songs',
                    f'• Available: {available_songs} songs',
                    f'• Successfully loaded: {processed_count} songs',
                    f'• Failed: {failed_count} songs',
                    f'• Remaining in temp queue: {remaining} songs',
                ]

                if processed_songs:
                    response.append('\n**Successfully loaded songs:**')
                    for i, (title, duration) in enumerate(processed_songs, 1):
                        response.append(f'{i}. {title} ({format_duration(duration)})')

                # Split message if too long
                formatted_response = '\n'.join(response)
                if len(formatted_response) > 1900:
                    chunks = [
                        formatted_response[i : i + 1900]
                        for i in range(0, len(formatted_response), 1900)
                    ]
                    await ctx.respond(chunks[0])
                    for chunk in chunks[1:]:
                        await ctx.followup.send(chunk)
                else:
                    await ctx.respond(formatted_response)

                ctxlog.success(
                    f'Successfully processed {processed_count} songs in guild {guild_id}'
                )

                # Start playing if nothing is playing
                if ctx.voice_client and not ctx.voice_client.is_playing():
                    await self.play_next_song(ctx)

            except Exception as e:
                error_msg = f'Error processing songs: {str(e)}'
                ctxlog.error(f'{error_msg} in guild {guild_id}')
                await ctx.respond('An error occurred while loading songs. Please try again.')

        except Exception as e:
            ctxlog.error(f'Error in load_songs command for guild {guild_id}: {e}')
            ctxlog.error(traceback.format_exc())

            # Log queue state for debugging
            try:
                queue_data = self.queue.get_queue(guild_id)
                ctxlog.debug(
                    f"Queue state for guild {guild_id}: "
                    f"temp_queue_size={len(queue_data['temp_queue'])}, "
                    f"main_queue_size={len(queue_data['queue'])}"
                )
            except Exception as debug_error:
                ctxlog.error(f'Error gathering debug information: {debug_error}')

    @commands.slash_command(name='suggest', description='Suggests trending or recommended songs.')
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

        current_song_title = current_song[1]
        ctxlogger.info(f'Current song in guild {guild_id}: {current_song_title}')

        # Clean up the song title
        if '(' in current_song_title:
            current_song_title = current_song_title.split('(')[0]

        if '-' in current_song_title:
            current_song_title = current_song_title.split('-')[0]

        await ctx.defer()  # Respond with a delay

        try:
            # Fetch related videos using YouTube API
            url = 'https://www.googleapis.com/youtube/v3/search'
            params = {
                'part': 'snippet',
                'q': current_song_title,
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
                    f'No suggestions found for song: {current_song_title} in guild {guild_id}'
                )
                await ctx.respond('No suggestions found!')
                return

            # Create a rich embed to display suggestions
            embed = discord.Embed(
                title='🎵 Suggested Songs',
                description=(
                    f'Based on: {current_song_title}\n\n'
                    + '\n'.join(f'{i+1}. {suggestion}' for i, suggestion in enumerate(suggestions))
                ),
                color=discord.Color.blue(),
            )
            embed.set_footer(text='Use /play_music with the song title or URL to play')

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

            # Get temp queue information
            temp_queue_size = self.queue.get_temp_queue_size(guild_id)

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
                    f'**In Temp Queue:** {temp_queue_size}'
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
                title, duration = current_song[1], current_song[2]
                progress_percent = (completed_songs / total_songs) * 100 if total_songs > 0 else 0

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

            # Loop and playback status
            loop_type = self.get_loop_type(guild_id)
            if loop_type:
                embed.add_field(
                    name='🔁 Loop Status',
                    value=f'Loop mode: {loop_type.title()}',
                    inline=True,
                )

            # Queue health
            if temp_queue_size > 0:
                embed.add_field(
                    name='📥 Loading Status',
                    value=(
                        f'Songs waiting to be processed: {temp_queue_size}\n'
                        f'Estimated processing time: {(temp_queue_size * 2) // 60}m {(temp_queue_size * 2) % 60}s'
                    ),
                    inline=True,
                )

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
                    f"current_index={queue_data['current_index']}, "
                    f"temp_queue_size={len(queue_data['temp_queue'])}"
                )
            except Exception as debug_error:
                ctxlog.error(f'Error gathering debug information: {debug_error}')

    @commands.slash_command(
        name='remove',
        description='Remove a specific song from the queue by its position number.',
    )
    async def remove(self, ctx: discord.ApplicationContext, position: str):
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

            # Validate input is a number
            try:
                pos = int(position)
                if pos <= 0:
                    await ctx.respond('Please provide a positive number.')
                    return
            except ValueError:
                await ctx.respond('Please provide a valid number.')
                ctxlog.warning(f'Invalid position provided: {position} in guild {guild_id}')
                return

            # Adjust position to 0-based index
            pos = pos - 1  # Convert from user-friendly 1-based to 0-based index
            queue_length = len(queue_data['queue'])

            # Check if number is in valid range
            if pos >= queue_length:
                await ctx.respond(f'⚠️ Please provide a number between 1 and {queue_length}.')
                ctxlog.warning(
                    f'Position out of range in guild {guild_id}: {pos + 1}, '
                    f'queue length: {queue_length}'
                )
                return

            # Check if trying to remove currently playing song
            if pos == queue_data['current_index']:
                await ctx.respond('❌ Cannot remove the currently playing song. Use /skip instead.')
                ctxlog.warning(f'Attempted to remove currently playing song in guild {guild_id}')
                return

            try:
                # Get song details before removing
                removed_song = queue_data['queue'][pos]
                song_title = removed_song[1]
                song_duration = removed_song[2]

                # Get context information
                current_song = self.get_current_song(guild_id)
                current_title = current_song[1] if current_song else 'Unknown'

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
                    value=f'**Title:** {song_title}\n**Duration:** {format_duration(song_duration)}',
                    inline=False,
                )

                embed.add_field(
                    name='Queue Status',
                    value=(
                        f"**Position removed:** {pos + 1}\n"
                        f"**Current song:** {current_title}\n"
                        f"**Remaining songs:** {len(queue_data['queue']) - (queue_data['current_index'] + 1)}"
                    ),
                    inline=False,
                )

                await ctx.respond(embed=embed)
                ctxlog.success(
                    f'Successfully removed song at position {pos + 1} in guild {guild_id}'
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

                # Get current song duration
                current_song = self.get_current_song(guild_id)
                if not current_song:
                    await ctx.respond('No song is currently playing.')
                    ctxlog.warning(f'No current song found in guild {guild_id}')
                    return

                url, title, song_duration = current_song

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

                # Create new FFMPEG options with seek
                ffmpeg_options = {
                    'before_options': (
                        f'-reconnect 1 -reconnect_streamed 1 '
                        f'-reconnect_delay_max 5 -ss {seek_position}'
                    ),
                    'options': '-vn -af "aresample=44100:filter_size=64:phase_shift=8"',
                }

                # Get the current URL or refresh it if needed
                if not url:
                    url, _, _ = await self.refresh_url(title, guild_id)
                    if not url:
                        await ctx.respond('Failed to seek. Please try again.')
                        ctxlog.error(f'Failed to refresh URL in guild {guild_id}')
                        return

                # Stop current playback
                ctx.voice_client.stop()

                # Start playback from new position
                ctx.voice_client.play(
                    discord.FFmpegPCMAudio(url, **ffmpeg_options),
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
        name='play_playlist_yt',
        description='Play all songs from a YouTube playlist URL',
    )
    async def play_playlist_yt(self, ctx: discord.ApplicationContext, playlist_url: str):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(
            f'{ctx.author.name} used play_playlist_yt command with URL: {playlist_url} '
            f'in guild {guild_id}'
        )
        await ctx.defer()

        try:
            if ctx.author.voice is None:
                ctxlog.warning(
                    f'Attempted to use play_playlist_yt command without joining voice channel '
                    f'in guild {guild_id}'
                )
                await ctx.respond('You need to join a voice channel first.')
                return

            voice_channel = ctx.author.voice.channel

            # Validate permissions
            permissions = voice_channel.permissions_for(ctx.guild.me)
            if not permissions.connect or not permissions.speak:
                await ctx.respond(
                    "I don't have permission to join and speak in your voice channel!"
                )
                ctxlog.warning(f'Missing permissions for voice channel in guild {guild_id}')
                return

            try:
                # Get all video URLs from the playlist
                ctxlog.info(f'Fetching playlist videos for guild {guild_id}...')
                playlist = Playlist(playlist_url)
                video_links = [video_url for video_url in playlist.video_urls]

                if not video_links:
                    await ctx.respond('⚠️ No videos found in the playlist or invalid playlist URL.')
                    ctxlog.warning(f'No videos found in playlist for guild {guild_id}')
                    return

                # Add all videos to temp queue for this server
                random.shuffle(video_links)
                self.queue.add_to_temp_queue(guild_id, video_links)
                total_songs = len(video_links)

                # Connect to voice channel if needed
                if ctx.voice_client is None:
                    await voice_channel.connect()
                    await asyncio.sleep(0.5)

                # Process first song immediately if nothing is playing
                if not ctx.voice_client.is_playing():
                    first_song = self.queue.get_next_temp_songs(guild_id, 1)[0]
                    url, title, duration = await self.fetch_youtube_url(first_song, guild_id)

                    if url:
                        self.queue.add_song(guild_id, (url, title, duration))
                        ctx.voice_client.play(
                            discord.FFmpegPCMAudio(url, **self.FFMPEG_OPTIONS),
                            after=lambda e: self.bot.loop.create_task(self.play_next_song(ctx)),
                        )
                        await ctx.send(f'🎵 Now playing: {title} ({format_duration(duration)})')
                        await voice_channel.set_status(status=f'▶️ {title}')
                        ctxlog.success(f'Started playing: {title} in guild {guild_id}')

                # Process initial batch of songs concurrently
                initial_songs = self.queue.get_next_temp_songs(guild_id, self.INITIAL_SONGS_TO_LOAD)

                # Create initial response embed
                embed = discord.Embed(
                    title='📋 YouTube Playlist Loading',
                    description=f'Loading playlist with {total_songs} songs',
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow(),
                )
                embed.add_field(name='Status', value='Loading initial songs...', inline=False)
                await ctx.respond(embed=embed)

                # Fetch initial songs concurrently
                fetch_tasks = [self.fetch_youtube_url(song, guild_id) for song in initial_songs]
                results = await asyncio.gather(*fetch_tasks)

                processed_count = 0
                processed_songs = []
                for url, title, duration in results:
                    if url:
                        self.queue.add_song(guild_id, (url, title, duration))
                        processed_count += 1
                        processed_songs.append((title, duration))
                        ctxlog.info(f'Added to queue in guild {guild_id}: {title}')

                remaining = self.queue.get_temp_queue_size(guild_id)

                # Create status embed
                status_embed = discord.Embed(
                    title='📥 Playlist Loading Status',
                    color=discord.Color.green(),
                    timestamp=discord.utils.utcnow(),
                )

                status_embed.add_field(
                    name='Progress',
                    value=(
                        f'• Total songs in playlist: {total_songs}\n'
                        f'• Initially loaded: {processed_count}\n'
                        f'• Remaining to load: {remaining}\n'
                        f'• Estimated loading time: {(remaining * 2) // 60}m {(remaining * 2) % 60}s'
                    ),
                    inline=False,
                )

                if processed_songs:
                    songs_list = '\n'.join(
                        f'{i}. {title} ({format_duration(duration)})'
                        for i, (title, duration) in enumerate(processed_songs[:5], 1)
                    )
                    status_embed.add_field(
                        name='First Few Songs',
                        value=songs_list + ('\n...' if len(processed_songs) > 5 else ''),
                        inline=False,
                    )

                await ctx.send(embed=status_embed)
                ctxlog.success(f'Successfully started playlist loading in guild {guild_id}')

            except Exception as playlist_error:
                error_msg = f'Error processing YouTube playlist: {str(playlist_error)}'
                ctxlog.error(f'{error_msg} in guild {guild_id}')
                await ctx.respond(
                    'An error occurred while processing the playlist. '
                    'Please check the URL and try again.'
                )

        except Exception as e:
            ctxlog.error(f'Error in play_playlist_yt for guild {guild_id}: {e}')
            ctxlog.error(traceback.format_exc())

            await ctx.respond('An unexpected error occurred. Please try again later.')

            # Log queue state for debugging
            try:
                queue_data = self.queue.get_queue(guild_id)
                ctxlog.debug(
                    f"Queue state for guild {guild_id}: "
                    f"temp_queue_size={len(queue_data['temp_queue'])}, "
                    f"main_queue_size={len(queue_data['queue'])}"
                )
            except Exception as debug_error:
                ctxlog.error(f'Error gathering debug information: {debug_error}')

    @commands.slash_command(
        name='save_queue',
        description='Save all songs from current queue and temp queue to a playlist file',
    )
    async def save_queue(self, ctx: discord.ApplicationContext, playlist_name: str):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(
            f'{ctx.author.name} used save_queue command with playlist name: {playlist_name} '
            f'in guild {guild_id}'
        )

        try:
            # Clean the playlist name to prevent directory traversal and ensure it's safe
            playlist_name = ''.join(c for c in playlist_name if c.isalnum() or c in (' ', '-', '_'))
            playlist_path = os.path.join(self.playlists_dir, f'{playlist_name}.txt')

            if os.path.exists(playlist_path):
                error_msg = (
                    f'⚠️ A playlist named "{playlist_name}" already exists. '
                    f'Please choose a different name.'
                )
                ctxlog.warning(
                    f'Attempted to create duplicate playlist: {playlist_name} '
                    f'in guild {guild_id}'
                )
                await ctx.respond(error_msg)
                return

            try:
                # Create the playlists directory if it doesn't exist
                os.makedirs(self.playlists_dir, exist_ok=True)

                # Get queue data for this server
                queue_data = self.queue.get_queue(guild_id)

                # Get all songs from main queue
                main_queue_songs = []
                for _, title, _ in queue_data['queue']:
                    main_queue_songs.append(title)

                # Get all songs from temp queue
                temp_queue_songs = queue_data['temp_queue']

                # Combine all songs
                all_songs = main_queue_songs + temp_queue_songs
                total_songs = len(all_songs)

                if total_songs == 0:
                    await ctx.respond('⚠️ No songs in queue to save.')
                    ctxlog.warning(f'Attempted to save empty queue in guild {guild_id}')
                    return

                # Write songs to playlist file
                with open(playlist_path, 'w', encoding='utf-8') as file:
                    for song in all_songs:
                        file.write(f'{song}\n')

                # Create response embed
                embed = discord.Embed(
                    title='💾 Queue Saved to Playlist',
                    color=discord.Color.green(),
                    timestamp=discord.utils.utcnow(),
                )

                embed.add_field(
                    name='Playlist Details',
                    value=(
                        f'**Name:** {playlist_name}\n'
                        f'**Total Songs:** {total_songs}\n'
                        f'**From Main Queue:** {len(main_queue_songs)}\n'
                        f'**From Temp Queue:** {len(temp_queue_songs)}'
                    ),
                    inline=False,
                )

                # Add preview of first few songs
                if all_songs:
                    preview_songs = all_songs[:5]
                    songs_preview = '\n'.join(
                        f'{i}. {song}' for i, song in enumerate(preview_songs, 1)
                    )
                    if len(all_songs) > 5:
                        songs_preview += '\n...'

                    embed.add_field(name='Preview', value=songs_preview, inline=False)

                embed.add_field(
                    name='Usage',
                    value=(
                        'Use `/play_playlist` command with name '
                        f'`{playlist_name}` to play this playlist'
                    ),
                    inline=False,
                )

                await ctx.respond(embed=embed)
                ctxlog.success(
                    f'Successfully saved {total_songs} songs to playlist: {playlist_name} '
                    f'from guild {guild_id}'
                )

            except IOError as io_error:
                error_msg = f'Error writing to playlist file: {str(io_error)}'
                ctxlog.error(f'{error_msg} in guild {guild_id}')
                await ctx.respond(
                    'Failed to save queue to playlist due to file system error. '
                    'Please try again.'
                )

        except Exception as e:
            ctxlog.error(f'Error in save_queue command for guild {guild_id}: {e}')
            ctxlog.error(traceback.format_exc())

            await ctx.respond(
                'An unexpected error occurred while saving the queue. Please try again.'
            )

            # Log queue state for debugging
            try:
                queue_data = self.queue.get_queue(guild_id)
                ctxlog.debug(
                    f"Queue state for guild {guild_id}: "
                    f"main_queue_size={len(queue_data['queue'])}, "
                    f"temp_queue_size={len(queue_data['temp_queue'])}"
                )
            except Exception as debug_error:
                ctxlog.error(f'Error gathering debug information: {debug_error}')

    @commands.slash_command(
        name='play_liked_songs', description='Play your personal liked songs playlist'
    )
    async def play_liked_songs(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used play_liked_songs command in guild {guild_id}')
        await ctx.defer()

        try:
            # Check if user is in a voice channel
            if ctx.author.voice is None:
                ctxlog.warning(
                    f'Attempted to use play_liked_songs command without joining voice channel '
                    f'in guild {guild_id}'
                )
                await ctx.respond('You need to join a voice channel first.')
                return

            voice_channel = ctx.author.voice.channel

            # Check permissions
            permissions = voice_channel.permissions_for(ctx.guild.me)
            if not permissions.connect or not permissions.speak:
                await ctx.respond(
                    "I don't have permission to join and speak in your voice channel!"
                )
                ctxlog.warning(f'Missing permissions for voice channel in guild {guild_id}')
                return

            # Get user's personal playlist name (their discord ID)
            playlist_name = str(ctx.author.id)
            playlist_path = os.path.join(self.playlists_dir, f'{playlist_name}.txt')

            # Check if the playlist exists
            if not os.path.exists(playlist_path):
                await ctx.respond(
                    "❌ You don't have any liked songs yet. "
                    'Use `/like` to add songs to your playlist!'
                )
                ctxlog.warning(
                    f'Liked songs playlist not found for user: {ctx.author.name} '
                    f'in guild {guild_id}'
                )
                return

            try:
                # Read and validate playlist contents
                with open(playlist_path, 'r', encoding='utf-8') as file:
                    songs = [line.strip() for line in file if line.strip()]

                if not songs:
                    await ctx.respond('Your liked songs playlist is empty.')
                    return

                # Add all songs to temp queue with shuffle
                random.shuffle(songs)
                self.queue.add_to_temp_queue(guild_id, songs)
                total_songs = len(songs)

                # Connect to voice channel if needed
                if ctx.voice_client is None:
                    await voice_channel.connect()
                    await asyncio.sleep(0.5)

                # Process first song immediately if nothing is playing
                if not ctx.voice_client.is_playing():
                    first_song = self.queue.get_next_temp_songs(guild_id, 1)[0]
                    url, title, duration = await self.fetch_youtube_url(first_song, guild_id)
                    if url:
                        self.queue.add_song(guild_id, (url, title, duration))
                        ctx.voice_client.play(
                            discord.FFmpegPCMAudio(url, **self.FFMPEG_OPTIONS),
                            after=lambda e: self.bot.loop.create_task(self.play_next_song(ctx)),
                        )
                        await ctx.send(f'🎵 Now playing: {title} ({format_duration(duration)})')
                        await voice_channel.set_status(status=f'▶️ {title}')
                        ctxlog.success(f'Started playing: {title} in guild {guild_id}')

                # Create initial response embed
                initial_embed = discord.Embed(
                    title='💝 Loading Liked Songs',
                    description=f'Loading your personal playlist with {total_songs} songs',
                    color=discord.Color.nitro_pink(),
                    timestamp=discord.utils.utcnow(),
                )
                await ctx.respond(embed=initial_embed)

                # Process initial batch of songs concurrently
                initial_songs = self.queue.get_next_temp_songs(guild_id, self.INITIAL_SONGS_TO_LOAD)

                # Fetch initial songs concurrently
                fetch_tasks = [self.fetch_youtube_url(song, guild_id) for song in initial_songs]
                results = await asyncio.gather(*fetch_tasks)

                processed_count = 0
                processed_songs = []
                for url, title, duration in results:
                    if url:
                        self.queue.add_song(guild_id, (url, title, duration))
                        processed_count += 1
                        processed_songs.append((title, duration))
                        ctxlog.info(f'Added to queue in guild {guild_id}: {title}')

                remaining = self.queue.get_temp_queue_size(guild_id)

                # Create status embed
                status_embed = discord.Embed(
                    title='💝 Liked Songs Loading Status',
                    color=discord.Color.nitro_pink(),
                    timestamp=discord.utils.utcnow(),
                )

                status_embed.add_field(
                    name='Progress',
                    value=(
                        f'• Total liked songs: {total_songs}\n'
                        f'• Initially loaded: {processed_count}\n'
                        f'• Remaining to load: {remaining}\n'
                        f'• Estimated loading time: {(remaining * 2) // 60}m {(remaining * 2) % 60}s'
                    ),
                    inline=False,
                )

                if processed_songs:
                    songs_list = '\n'.join(
                        f'{i}. {title} ({format_duration(duration)})'
                        for i, (title, duration) in enumerate(processed_songs[:5], 1)
                    )
                    status_embed.add_field(
                        name='First Few Songs',
                        value=songs_list + ('\n...' if len(processed_songs) > 5 else ''),
                        inline=False,
                    )

                status_embed.set_footer(text=f'Liked Songs Playlist • {ctx.author.name}')

                await ctx.send(embed=status_embed)
                ctxlog.success(f'Successfully started liked songs playback in guild {guild_id}')

            except Exception as playlist_error:
                error_msg = f'Error processing liked songs playlist: {str(playlist_error)}'
                ctxlog.error(f'{error_msg} in guild {guild_id}')
                await ctx.respond(
                    'An error occurred while processing your liked songs. Please try again.'
                )

        except Exception as e:
            ctxlog.error(f'Error in play_liked_songs for guild {guild_id}: {e}')
            ctxlog.error(traceback.format_exc())

            await ctx.respond('An unexpected error occurred. Please try again later.')

            # Log queue state for debugging
            try:
                queue_data = self.queue.get_queue(guild_id)
                ctxlog.debug(
                    f"Queue state for guild {guild_id}: "
                    f"temp_queue_size={len(queue_data['temp_queue'])}, "
                    f"main_queue_size={len(queue_data['queue'])}"
                )
            except Exception as debug_error:
                ctxlog.error(f'Error gathering debug information: {debug_error}')

    @commands.slash_command(
        name='like_current_song',
        description='Add the currently playing song to your personal liked songs playlist',
    )
    async def like_current_song(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used like_current_song command in guild {guild_id}')

        try:
            # Get user's personal playlist name (their discord ID)
            playlist_name = str(ctx.author.id)
            playlist_path = os.path.join(self.playlists_dir, f'{playlist_name}.txt')

            # Get current song for this server
            current_song = self.get_current_song(guild_id)

            # Check if there's a song currently playing
            if not current_song:
                await ctx.respond('❌ No song is currently playing.')
                ctxlog.warning(
                    f'Attempted to like song when nothing was playing in guild {guild_id}'
                )
                return

            current_song_title = current_song[1]
            current_song_duration = current_song[2]

            try:
                # Create playlist if it doesn't exist
                if not os.path.exists(playlist_path):
                    os.makedirs(self.playlists_dir, exist_ok=True)
                    with open(playlist_path, 'w', encoding='utf-8') as _:
                        pass
                    ctxlog.info(f'Created new liked songs playlist for user: {ctx.author.name}')

                # Check if song is already in liked songs
                song_already_liked = False
                if os.path.exists(playlist_path):
                    with open(playlist_path, 'r', encoding='utf-8') as file:
                        liked_songs = [line.strip() for line in file if line.strip()]
                        song_already_liked = current_song_title in liked_songs

                if song_already_liked:
                    await ctx.respond(
                        f"💝 You've already liked this song!\n" f'Song: {current_song_title}'
                    )
                    return

                # Add the current song to the playlist
                with open(playlist_path, 'a', encoding='utf-8') as file:
                    if os.path.getsize(playlist_path) > 0:
                        file.write('\n')
                    file.write(f'{current_song_title}\n')

                # Count total liked songs
                with open(playlist_path, 'r', encoding='utf-8') as file:
                    total_liked = sum(1 for line in file if line.strip())

                # Create response embed
                embed = discord.Embed(
                    title='💝 Song Added to Liked Songs',
                    color=discord.Color.nitro_pink(),
                    timestamp=discord.utils.utcnow(),
                )

                embed.add_field(
                    name='Song Details',
                    value=(
                        f'**Title:** {current_song_title}\n'
                        f'**Duration:** {format_duration(current_song_duration)}'
                    ),
                    inline=False,
                )

                embed.add_field(
                    name='Playlist Info',
                    value=(
                        f'**Total Liked Songs:** {total_liked}\n'
                        'Use `/play_liked_songs` to play your playlist!'
                    ),
                    inline=False,
                )

                embed.set_footer(text=f'Liked Songs • {ctx.author.name}')

                await ctx.respond(embed=embed)
                ctxlog.success(
                    f"Added song to user's playlist in guild {guild_id}: {current_song_title}"
                )

            except IOError as io_error:
                error_msg = f'Error accessing playlist file: {str(io_error)}'
                ctxlog.error(f'{error_msg} in guild {guild_id}')
                await ctx.respond('Failed to access your liked songs playlist. Please try again.')

        except Exception as e:
            ctxlog.error(f'Error in like_current_song for guild {guild_id}: {e}')
            ctxlog.error(traceback.format_exc())

            await ctx.respond(
                'An unexpected error occurred while liking the song. Please try again.'
            )

            # Log current state for debugging
            try:
                queue_data = self.queue.get_queue(guild_id)
                ctxlog.debug(
                    f"Queue state for guild {guild_id}: "
                    f"current_index={queue_data['current_index']}, "
                    f"is_playing={ctx.voice_client.is_playing() if ctx.voice_client else False}"
                )
            except Exception as debug_error:
                ctxlog.error(f'Error gathering debug information: {debug_error}')

    @commands.slash_command(
        name='play_playlist_spotify',
        description='Play songs from a Spotify playlist URL',
    )
    async def play_playlist_spotify(self, ctx: discord.ApplicationContext, playlist_url: str):
        """
        Slash command to play songs from a Spotify playlist
        Args:
            ctx: Discord application context
            playlist_url: Spotify playlist URL
        """
        guild_id = ctx.guild.id
        ctxlog = get_context_logger(ctx)
        ctxlog.info(
            f'{ctx.author.name} used play_playlist_spotify command with URL: {playlist_url} '
            f'in guild {guild_id}'
        )
        await ctx.defer()

        try:
            # Check if user is in voice channel
            if ctx.author.voice is None:
                ctxlog.warning(
                    f'Attempted to use play_playlist_spotify command without joining voice channel '
                    f'in guild {guild_id}'
                )
                await ctx.respond('You need to join a voice channel first.')
                return

            voice_channel = ctx.author.voice.channel

            # Check permissions
            permissions = voice_channel.permissions_for(ctx.guild.me)
            if not permissions.connect or not permissions.speak:
                await ctx.respond(
                    "I don't have permission to join and speak in your voice channel!"
                )
                ctxlog.warning(f'Missing permissions for voice channel in guild {guild_id}')
                return

            try:
                # Create playlists directory if it doesn't exist
                os.makedirs('playlists', exist_ok=True)

                # Extract playlist name from URL for file naming
                playlist_id = playlist_url.split('/')[-1].split('?')[0]
                playlist_path = os.path.join('playlists', f'spotify_{playlist_id}.txt')

                # Create initial status embed
                loading_embed = discord.Embed(
                    title='🎵 Loading Spotify Playlist',
                    description='Fetching songs from Spotify...',
                    color=discord.Color.green(),
                    timestamp=discord.utils.utcnow(),
                )
                await ctx.respond(embed=loading_embed)

                # Fetch tracks from Spotify with credentials
                try:
                    songs = await get_playlist_tracks_async(
                        playlist_url, self.spotify_client_id, self.spotify_client_secret
                    )
                except Exception as spotify_error:
                    error_embed = discord.Embed(
                        title='❌ Spotify Error',
                        description=f'Error fetching playlist: {str(spotify_error)}',
                        color=discord.Color.red(),
                    )
                    await ctx.respond(embed=error_embed)
                    ctxlog.error(f'Spotify fetch error in guild {guild_id}: {str(spotify_error)}')
                    return

                if not songs:
                    await ctx.respond('This playlist appears to be empty or inaccessible.')
                    return

                # Save playlist to file for future use
                with open(playlist_path, 'w', encoding='utf-8') as file:
                    for song in songs:
                        file.write(f'{song}\n')

                # Shuffle and add to temp queue
                random.shuffle(songs)
                self.queue.add_to_temp_queue(guild_id, songs)
                total_songs = len(songs)

                # Connect to voice channel if needed
                if ctx.voice_client is None:
                    await voice_channel.connect()
                    await asyncio.sleep(0.5)

                # Process first song immediately if nothing is playing
                if not ctx.voice_client.is_playing():
                    first_song = self.queue.get_next_temp_songs(guild_id, 1)[0]
                    url, title, duration = await self.fetch_youtube_url(first_song, guild_id)
                    if url:
                        self.queue.add_song(guild_id, (url, title, duration))
                        ctx.voice_client.play(
                            discord.FFmpegPCMAudio(url, **self.FFMPEG_OPTIONS),
                            after=lambda e: self.bot.loop.create_task(self.play_next_song(ctx)),
                        )
                        await ctx.send(f'🎵 Now playing: {title} ({format_duration(duration)})')
                        await voice_channel.set_status(status=f'▶️ {title}')
                        ctxlog.success(f'Started playing: {title} in guild {guild_id}')

                # Process initial batch of songs
                initial_songs = self.queue.get_next_temp_songs(guild_id, self.INITIAL_SONGS_TO_LOAD)

                # Fetch initial songs concurrently
                fetch_tasks = [self.fetch_youtube_url(song, guild_id) for song in initial_songs]
                results = await asyncio.gather(*fetch_tasks)

                processed_count = 0
                processed_songs = []
                for url, title, duration in results:
                    if url:
                        self.queue.add_song(guild_id, (url, title, duration))
                        processed_count += 1
                        processed_songs.append((title, duration))
                        ctxlog.info(f'Added to queue in guild {guild_id}: {title}')

                remaining = self.queue.get_temp_queue_size(guild_id)

                # Create status embed
                status_embed = discord.Embed(
                    title='📥 Spotify Playlist Status',
                    color=discord.Color.green(),
                    timestamp=discord.utils.utcnow(),
                )

                status_embed.add_field(
                    name='Progress',
                    value=(
                        f'• Total songs: {total_songs}\n'
                        f'• Initially loaded: {processed_count}\n'
                        f'• Remaining to load: {remaining}\n'
                        f'• Estimated loading time: {(remaining * 2) // 60}m {(remaining * 2) % 60}s'
                    ),
                    inline=False,
                )

                if processed_songs:
                    songs_list = '\n'.join(
                        f'{i}. {title} ({format_duration(duration)})'
                        for i, (title, duration) in enumerate(processed_songs[:5], 1)
                    )
                    status_embed.add_field(
                        name='First Few Songs',
                        value=songs_list + ('\n...' if len(processed_songs) > 5 else ''),
                        inline=False,
                    )

                status_embed.set_footer(text=f'Spotify Playlist • {playlist_id}')

                await ctx.send(embed=status_embed)
                ctxlog.success(f'Successfully started Spotify playlist in guild {guild_id}')

            except Exception as playlist_error:
                error_msg = f'Error processing Spotify playlist: {str(playlist_error)}'
                ctxlog.error(f'{error_msg} in guild {guild_id}')
                await ctx.respond(
                    'An error occurred while processing the Spotify playlist. Please try again.'
                )

        except Exception as e:
            ctxlog.error(f'Error in play_playlist_spotify for guild {guild_id}: {e}')
            ctxlog.error(traceback.format_exc())

            await ctx.respond('An unexpected error occurred. Please try again later.')

            # Log queue state for debugging
            try:
                queue_data = self.queue.get_queue(guild_id)
                ctxlog.debug(
                    f"Queue state for guild {guild_id}: "
                    f"temp_queue_size={len(queue_data['temp_queue'])}, "
                    f"main_queue_size={len(queue_data['queue'])}"
                )
            except Exception as debug_error:
                ctxlog.error(f'Error gathering debug information: {debug_error}')

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
                await ctx.respond('You need to be in a voice channel to use this command!')
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
                embed.add_field(
                    name='Info',
                    value='Bot will now stay in the voice channel even when empty.',
                    inline=False,
                )

            embed.set_footer(text=f'Requested by {ctx.author.name}')

            await ctx.respond(embed=embed)
            ctxlog.success(f'24/7 mode {status.lower()} for guild {guild_id}')

        except Exception as e:
            ctxlog.error(f'Error in 24x7 command for guild {guild_id}: {e}')
            ctxlog.error(traceback.format_exc())
            await ctx.respond('An error occurred while toggling 24/7 mode.')


def setup(bot):
    bot.add_cog(MusicYT(bot))
