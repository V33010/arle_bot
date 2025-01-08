import asyncio
import functools
import os
import random
import tomllib
import traceback
from concurrent.futures import ThreadPoolExecutor

import discord
from discord.ext import commands
from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials
from yt_dlp import YoutubeDL

from utils.logger import get_context_logger, log
from validators.config import ConfigValidator

with open(os.path.join('config.toml'), 'rb') as f:
    data = tomllib.load(f)
arle_config: ConfigValidator = ConfigValidator.model_validate(data)

youtube_api_key = arle_config.secrets.youtube_api_key


def format_duration(duration: int):
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
        self.current_url_info = {}  # Dictionary to store current URL info for each server
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
        }
        self.youtube_api_key = youtube_api_key
        self.playlists_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'playlists')
        self.INITIAL_SONGS_TO_LOAD = 4
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
                if guild_id not in self.current_url_info:
                    self.current_url_info[guild_id] = {}

                self.current_url_info[guild_id] = {
                    'webpage_url': video.get('webpage_url') or video.get('url'),
                    'title': video.get('title', 'Unknown Title'),
                }
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

    async def refresh_url(self, stored_info, guild_id):
        """Refresh the streaming URL for a video for specific server"""
        log.debug('Function refresh_url invoked')
        try:
            if stored_info and stored_info['webpage_url']:
                with YoutubeDL(self.ydl_opts) as ydl:
                    info = ydl.extract_info(stored_info['webpage_url'], download=False)
                    duration = info.get('duration', 0)

                    # Update stored info for this server
                    if guild_id in self.current_url_info:
                        self.current_url_info[guild_id]['webpage_url'] = info.get('webpage_url')

                    log.success(f"URL refreshed successfully: {info.get('url')}")
                    return info.get('url'), stored_info['title'], duration
        except Exception as e:
            log.error(f'Error refreshing URL: {e}')
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
                ctxlog.success('Playback started.')
                return True
        except Exception as e:
            ctxlog.error(f'Playback error: {e}')
            # Try to refresh the URL and play again
            ctxlog.debug('Trying to refresh URL...')
            if guild_id in self.current_url_info:
                new_url, _, new_duration = await self.refresh_url(
                    self.current_url_info[guild_id], guild_id
                )
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
        try:
            # First determine and play the next song
            current_song = None
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
                url, title, duration = current_song

                if ctx.voice_client is None:
                    voice_channel = ctx.author.voice.channel
                    await voice_channel.connect()
                    await asyncio.sleep(0.5)

                if ctx.voice_client and not ctx.voice_client.is_playing():
                    success = await self.play_audio(
                        ctx,
                        url,
                        title,
                        duration,
                        after=lambda e: self.bot.loop.create_task(self.play_next_song(ctx)),
                    )

                    if success:
                        await ctx.send(f'Now playing: {title} ({format_duration(duration)})')
                        voice_channel = ctx.author.voice.channel
                        await voice_channel.set_status(status=f'{title}')

                        # Now process more songs from temp queue if available
                        # This happens after the next song has started playing
                        if self.queue.get_temp_queue_size(guild_id) > 0:
                            asyncio.create_task(self.process_temp_queue(ctx))
                    else:
                        await ctx.send('Failed to play the current song, skipping...')
                        await self.play_next_song(ctx)
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
                    if guild_id in self.current_url_info:
                        del self.current_url_info[guild_id]
                    if guild_id in self.loop_types:
                        del self.loop_types[guild_id]

                    # Disconnect the bot once all songs in the queue have been completed
                    await ctx.voice_client.disconnect()

        except Exception as e:
            ctxlog.error(f'Error in play_next_song: {e}')
            ctxlog.error(traceback.format_exc())

            # Attempt to clean up on error
            try:
                if ctx.voice_client:
                    await ctx.voice_client.disconnect()

                # Clean up server-specific states
                queue_data = self.queue.get_queue(guild_id)
                queue_data['queue'] = []
                queue_data['temp_queue'] = []
                queue_data['current_index'] = -1

                if guild_id in self.current_url_info:
                    del self.current_url_info[guild_id]
                if guild_id in self.loop_types:
                    del self.loop_types[guild_id]

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
                            await voice_channel.set_status(status=f'{title}')
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

                    if guild_id in self.current_url_info:
                        del self.current_url_info[guild_id]
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

                if guild_id in self.current_url_info:
                    del self.current_url_info[guild_id]
                if guild_id in self.loop_types:
                    del self.loop_types[guild_id]

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
                    ctxlog.info(f'Found url: {url}')
                    self.queue.add_song(guild_id, (url, title, duration))
                    ctx.voice_client.play(
                        discord.FFmpegPCMAudio(url, **self.FFMPEG_OPTIONS),
                        after=lambda e: self.bot.loop.create_task(self.play_next_song(ctx)),
                    )
                    await ctx.send(f'Now playing: {title} ({format_duration(duration)})')
                    await voice_channel.set_status(status=f'{title}')
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

            queue_message = ''
            current_index = queue_data['current_index']

            for i in range(total_length):
                song = queue_data['queue'][i]
                if i == current_index:
                    queue_message += f'{i}. ({format_duration(song[2])}) | {song[1]} ▶️\n'
                else:
                    queue_message += f'{i}. ({format_duration(song[2])}) | {song[1]}\n'

            queue_message = (
                f'Currently playing {current_index + 1} of {total_length}\n' + queue_message
            )

            if len(queue_message) > 2000:
                await ctx.respond('Showing complete queue...')
                chunks = [queue_message[i : i + 2000] for i in range(0, len(queue_message), 2000)]
                for chunk in chunks:
                    await ctx.send(chunk)
                ctxlog.success(f'Complete queue displayed with chunking for guild {guild_id}')
            else:
                await ctx.respond(queue_message)
                ctxlog.success(f'Complete queue displayed without chunking for guild {guild_id}')

        except Exception as e:
            ctxlog.error(f'Error in display_queue_long: {e}')
            await ctx.respond('An error occurred while displaying the queue.')

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


def setup(bot):
    bot.add_cog(MusicYT(bot))
