# TODO: create play_yt_playlist command for handling youtube playlists
import asyncio
import functools
import os
import random
import traceback
from concurrent.futures import ThreadPoolExecutor

import discord
from discord.ext import commands
from yt_dlp import YoutubeDL

from utils.logger import get_context_logger, log


def format_duration(duration: int):
    # Format duration as minutes:seconds
    minutes = duration // 60
    seconds = duration % 60
    duration_str = f'{minutes}:{seconds:02d}'
    return duration_str


class MusicQueue:
    def __init__(self):
        self.queue = []
        self.temp_queue = []
        self.current_index = -1
        self.processing_lock = False

    def add_song(self, song_tuple):
        self.queue.append(song_tuple)
        if self.current_index == -1:
            self.current_index = 0

    def add_to_temp_queue(self, songs):
        self.temp_queue.extend(songs)

    def get_temp_queue_size(self):
        return len(self.temp_queue)

    def get_next_temp_songs(self, count):
        """Get the next batch of songs from temp queue"""
        songs = self.temp_queue[:count]
        self.temp_queue = self.temp_queue[count:]
        return songs

    def get_loaded_songs(self):
        """Get all loaded songs with their details"""
        return [(i + 1, song[1], song[2]) for i, song in enumerate(self.queue)]

    def get_temp_queue_songs(self):
        """Get all songs in temp queue"""
        return [(i + 1, song) for i, song in enumerate(self.temp_queue)]

    def current_song(self):
        if self.current_index != -1:
            return self.queue[self.current_index]
        return None

    def next_song(self):
        if self.current_index != -1 and self.current_index < len(self.queue) - 1:
            self.current_index += 1
            return self.queue[self.current_index]
        return None

    def previous_song(self):
        if self.current_index > 0:
            self.current_index -= 1
            return self.queue[self.current_index]
        return None

    def remove_current_song(self):
        if self.current_index != -1:
            removed_song = self.queue.pop(self.current_index)
            if self.current_index >= len(self.queue):
                self.current_index = len(self.queue) - 1
            return removed_song
        return None


class MusicYT(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = MusicQueue()
        self.thread_pool = ThreadPoolExecutor(max_workers=6)
        self.loop_type = None  # can be "all", "once" or None
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
        self.current_url_info = None
        self.playlists_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'playlists')
        self.INITIAL_SONGS_TO_LOAD = 4
        self.SONGS_TO_ADD_ON_NEXT = 2

    async def process_temp_queue(self, ctx):
        """Process songs from temp queue and add them to main queue"""
        ctxlog = get_context_logger(ctx)

        if self.queue.processing_lock:
            return

        try:
            self.queue.processing_lock = True
            songs_to_process = self.queue.get_next_temp_songs(self.SONGS_TO_ADD_ON_NEXT)

            # Process songs concurrently
            fetch_tasks = [self.fetch_youtube_url(song) for song in songs_to_process]

            results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

            for song, result in zip(songs_to_process, results):
                if isinstance(result, Exception):
                    ctxlog.warning(
                        f'Failed to process song from temp queue: {song}, Error: {result}'
                    )
                    continue

                url, title, duration = result
                if url:
                    self.queue.add_song((url, title, duration))
                    ctxlog.info(f'Processed song from temp queue: {title}')
                else:
                    ctxlog.warning(f'Failed to process song from temp queue: {song}')

        except Exception as e:
            ctxlog.error(f'Error processing temp queue: {e}')
        finally:
            self.queue.processing_lock = False

    def get_current_song(self):
        return self.queue.current_song()

    def _fetch_youtube_url_sync(self, query):
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

                self.current_url_info = {
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

    async def fetch_youtube_url(self, query):
        """Asynchronous wrapper for YouTube URL fetching"""
        try:
            # Run the synchronous function in the thread pool
            result = await asyncio.get_event_loop().run_in_executor(
                self.thread_pool, functools.partial(self._fetch_youtube_url_sync, query)
            )
            return result
        except Exception as e:
            log.error(f'Error in async YouTube fetch: {e}')
            return None, None, None

    async def refresh_url(self, stored_info):
        """Refresh the streaming URL for a video"""
        log.debug('Function refresh_url invoked')
        try:
            if stored_info and stored_info['webpage_url']:
                with YoutubeDL(self.ydl_opts) as ydl:
                    info = ydl.extract_info(stored_info['webpage_url'], download=False)
                    duration = info.get('duration', 0)
                    log.success(f"URL refreshed successfully: {info.get('url')}")
                    return info.get('url'), stored_info['title'], duration
        except Exception as e:
            log.error(f'Error refreshing URL: {e}')
        return None, None, None

    async def play_audio(self, ctx, url, title, duration, after=None):
        """Helper function to handle audio playback with error recovery"""
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
            if self.current_url_info:
                new_url, _, new_duration = await self.refresh_url(self.current_url_info)
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
        ctxlog = get_context_logger(ctx)
        try:
            # First determine and play the next song
            current_song = None
            if self.get_current_song():
                if (
                    self.loop_type == 'all'
                    and self.queue.current_index == len(self.queue.queue) - 1
                ):
                    self.queue.current_index = 0
                    current_song = self.get_current_song()
                elif self.loop_type == 'once':
                    current_song = self.get_current_song()
                else:
                    current_song = self.queue.next_song()

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

                        # Now process more songs from temp queue if available
                        # This happens after the next song has started playing
                        if self.queue.get_temp_queue_size() > 0:
                            asyncio.create_task(self.process_temp_queue(ctx))
                    else:
                        await ctx.send('Failed to play the current song, skipping...')
                        await self.play_next_song(ctx)
            else:
                if ctx.voice_client and not ctx.voice_client.is_playing():
                    # Process any remaining songs in temp queue before disconnecting
                    if self.queue.get_temp_queue_size() > 0:
                        await self.process_temp_queue(ctx)

                    # Clear queues before disconnecting
                    self.queue.queue = []
                    self.queue.temp_queue = []
                    self.queue.current_index = -1

                    # Disconnect the bot once all songs in the queue have been completed
                    await ctx.voice_client.disconnect()

        except Exception as e:
            ctxlog.error(f'Error in play_next_song: {e}')
            ctxlog.error(traceback.format_exc())

    @commands.slash_command(
        name='play_music', description='Play a music file in your voice channel.'
    )
    async def play_music(self, ctx: discord.ApplicationContext, query: str):
        ctxlog = get_context_logger(ctx)
        ctxlog.info('Received play_music request')
        await ctx.defer()

        if ctx.author.voice is None:
            await ctx.respond('You need to join a voice channel first.')
            return

        voice_channel = ctx.author.voice.channel

        url, title, duration = await self.fetch_youtube_url(query)
        if not url:
            await ctx.respond(f"Failed to fetch the song '{query}' from YouTube.")
            return
        duration_str = format_duration(duration)

        self.queue.add_song((url, title, duration))
        await ctx.respond(f'Added {title} ({duration_str})to the queue.')
        ctxlog.info(f'Added {title} to the queue.')

        # Connect if not already connected
        if ctx.voice_client is None:
            await voice_channel.connect()
            # Add a small delay to ensure connection is stable
            await asyncio.sleep(0.5)

        # Check if we need to start playing
        if not ctx.voice_client.is_playing():
            try:
                current_song = self.get_current_song()
                if current_song:
                    url, title, duration = current_song

                    ctx.voice_client.play(
                        discord.FFmpegPCMAudio(url, **self.FFMPEG_OPTIONS),
                        after=lambda e: self.bot.loop.create_task(self.play_next_song(ctx)),
                    )

                    ctxlog.success(f'Music playback started in {voice_channel}')
            except Exception as e:
                log.error(f'Error starting playback: {e}')
                if ctx.voice_client:
                    await ctx.voice_client.disconnect()

    @commands.slash_command(name='add_to_queue', description='Add a music file to the queue.')
    async def add_to_queue(self, ctx: discord.ApplicationContext, query: str):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used add_to_queue command.')
        await ctx.defer()
        url, title, duration = await self.fetch_youtube_url(query)
        if not url:
            await ctx.respond('Failed to fetch the song from YouTube.')
            return

        self.queue.add_song((url, title, duration))
        await ctx.respond(f'Added {title} ({format_duration(duration)}) to the queue.')
        ctxlog.success(f'{title} added to queue by {ctx.author.name}.')

        if not ctx.voice_client or not ctx.voice_client.is_playing():
            ctxlog.warning(f'{ctx.author.name} added song to empty queue.')
            await self.play_next_song(ctx)

    @commands.slash_command(name='skip', description='Skip the current song.')
    async def skip(self, ctx: discord.ApplicationContext):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f"{ctx.author.name} used command 'skip'")
        if ctx.voice_client is None or not ctx.voice_client.is_playing():
            await ctx.respond('No music playing to be skipped.')
            ctxlog.warning('Used skip command without music playback.')
            return

        current_song = self.get_current_song()
        current_song = current_song[1]

        ctxlog.info('Stopping current song...')
        ctx.voice_client.stop()

        await ctx.respond(f'Skipped {current_song}')
        ctxlog.success('Skipped current song')

    @commands.slash_command(name='nowplaying', description='Display the currently playing song.')
    async def nowplaying(self, ctx: discord.ApplicationContext):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used nowplaying command.')
        if not self.get_current_song():
            await ctx.respond('No song is currently playing.')
            ctxlog.warning('No song playing currently.')
            return
        else:
            current_song = self.get_current_song()
            if current_song:
                song_title = current_song[1]
                duration = current_song[2]
                await ctx.respond(f'Now playing {song_title} ({format_duration(duration)}).')
                ctxlog.success(f'Now playing {song_title}.')
            else:
                ctxlog.error("Could not find current song in function 'nowplaying'")

    @commands.slash_command(name='display_queue_long', description='Display the entire queue.')
    async def display_queue_long(self, ctx: discord.ApplicationContext):
        ctxlog = get_context_logger(ctx)
        await ctx.defer()
        ctxlog.info(f'{ctx.author.name} used display_queue_long command.')
        total_length = len(self.queue.queue)
        if total_length == 0:
            await ctx.respond('The queue is currently empty.')
            ctxlog.warning('Queue is currently empty.')
        else:
            print(f'current_index from display_queue_long: {self.queue.current_index}')
            queue_message = ''
            for i in range(total_length):
                if i == self.queue.current_index:
                    queue_message += (
                        str(i)
                        + '. ('
                        + format_duration(self.queue.queue[i][2])
                        + ') | '
                        + str(self.queue.queue[i][1])
                        + ' ▶️\n'
                    )
                else:
                    queue_message += (
                        str(i)
                        + '. ('
                        + format_duration(self.queue.queue[i][2])
                        + ') | '
                        + str(self.queue.queue[i][1])
                        + '\n'
                    )
            queue_message = (
                f'Currently playing {self.queue.current_index + 1} of {total_length}\n'
                + queue_message
            )
            if len(queue_message) > 2000:
                ctx.respond('Showing complete queue...')
                chunks = [queue_message[i : i + 2000] for i in range(0, len(queue_message), 2000)]
                for chunk in chunks:
                    await ctx.send(chunk)
                ctxlog.success('Complete queue displayed with chunking.')
            else:
                await ctx.respond(queue_message)
                ctxlog.success('Complete queue displayed without chunking.')

    @commands.slash_command(name='past_songs', description='Display the previously played songs.')
    async def past_songs(self, ctx: discord.ApplicationContext):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command past_songs.')
        if self.queue.current_index < 1:
            await ctx.respond('There are no past songs.')
        else:
            past_songs = ''
            for i in range(0, self.queue.current_index):
                past_songs += self.queue.queue[i][1] + '\n'

            if len(past_songs) > 2000:
                chunks = [past_songs[j : j + 2000] for j in range(0, len(past_songs), 2000)]
                for chunk in chunks:
                    await ctx.send(chunk)
                ctxlog.success('Past songs displayed with chunking.')
            else:
                ctxlog.success('Past songs displayed without chunking.')
                await ctx.respond(past_songs)

    @commands.slash_command(name='previous', description='Play the previous song.')
    async def previous(self, ctx: discord.ApplicationContext):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command previous.')
        await ctx.defer()
        ctxlog.debug(f'Current index initially: {self.queue.current_index}')
        if self.queue.current_index < 1:
            await ctx.respond('No previously played songs.')
            return
        else:
            self.queue.current_index -= 2
        if self.queue.current_index == -1:
            self.queue.current_index = 0
        ctxlog.debug(f'Current index after manual update: {self.queue.current_index}')
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            ctxlog.success('Current song stopped successfully.')
            await ctx.respond('Playing previous song.')

    @commands.slash_command(name='pause', description='Pause the current song.')
    async def pause(self, ctx: discord.ApplicationContext):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command pause.')
        if ctx.voice_client is None or not ctx.voice_client.is_playing():
            ctxlog.warning('No music playing')
            await ctx.respond('No music playing.')
            return

        ctx.voice_client.pause()
        await ctx.respond('Paused the song.')
        ctxlog.success('Paused music playback.')

    @commands.slash_command(name='resume', description='Resume playing the paused song.')
    async def play(self, ctx: discord.ApplicationContext):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command resume')
        if ctx.voice_client is None:
            await ctx.respond('No music queued.')
            ctxlog.warning('Tried using resume command for an empty queue.')
            return

        if ctx.voice_client.is_playing():
            ctxlog.warning('Tried using resume command while music playback is active')
            await ctx.respond('Music already playing.')
            return

        if ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.respond(f'Resumed playing {self.get_current_song()[1]}')
            ctxlog.success('Resumed music playback.')
        else:
            await ctx.respond('No music queued.')

    @commands.slash_command(name='stop', description='Stop the music and clear the queue.')
    async def stop(self, ctx: discord.ApplicationContext):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command stop')
        self.queue.queue = []
        self.queue.current_index = -1
        self.queue.temp_queue = []
        ctxlog.debug('Cleared the queue and set self.current_index = -1')

        if ctx.voice_client is None:
            ctxlog.warning('Tried using stop command without music playback.')
            await ctx.respond('No music playing.')
            return

        ctx.voice_client.stop()
        await ctx.voice_client.disconnect()
        await ctx.respond(
            'Stopped the music, cleared the queue, and disconnected from the voice channel.'
        )
        ctxlog.success('Stopped music playback successfully.')

    @commands.slash_command(
        name='display_queue',
        description='Display the next 10 songs and total songs in queue',
    )
    async def display_queue(self, ctx: discord.ApplicationContext):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command display_queue')
        if len(self.queue.queue) == 0:
            await ctx.respond('The queue is currently empty.')
            return

        try:
            next_songs = self.queue.queue[
                self.queue.current_index + 1 : self.queue.current_index + 11
            ]
        except IndexError:
            next_songs = self.queue.queue[self.queue.current_index :]
        next_song_titles = [song_info[1] for song_info in next_songs]
        next_song_durations = [song_info[2] for song_info in next_songs]
        n = 10
        if len(next_song_titles) < 10:
            n = len(next_song_titles)
        queue_message = f'Next {n} songs in queue:\n'
        for i in range(len(next_song_titles)):
            queue_message += (
                f'\n{i}. ({format_duration(next_song_durations[i])}) | {next_song_titles[i]}'
            )
        total_songs = len(self.queue.queue[self.queue.current_index :])
        queue_message += f'\n\nTotal songs in queue: {total_songs}'

        await ctx.respond(queue_message)
        ctxlog.success('Sent display_queue successfully!')

    @commands.slash_command(
        name='shuffle', description='Shuffle all the remaining songs in the queue.'
    )
    async def shuffle(self, ctx: discord.ApplicationContext):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command shuffle')
        if len(self.queue.queue) == 0:
            await ctx.respond('The queue is empty.')
            return
        remaining_songs = self.queue.queue[self.queue.current_index + 1 :]
        random.shuffle(remaining_songs)
        # update the queue
        self.queue.queue = self.queue.queue[: self.queue.current_index + 1] + remaining_songs
        temp_songs = self.queue.temp_queue
        random.shuffle(temp_songs)
        self.queue.temp_queue = temp_songs
        ctxlog.success('Shuffled the songs and updated the queue.')

        # Get all remaining songs if less than 5, otherwise get next 5
        next_songs = self.queue.queue[self.queue.current_index + 1 :]
        if len(next_songs) > 5:
            next_songs = next_songs[:5]
            ctxlog.info('Showing next 5 songs after shuffle')
        else:
            ctxlog.info(f'Showing all {len(next_songs)} remaining songs after shuffle')

        # Create message for next songs
        next_songs_message = 'Next songs after shuffle:\n'
        for i, song in enumerate(next_songs, 1):
            _, title, duration = song
            next_songs_message += f'{i}. ({format_duration(duration)}) | {title}\n'

        await ctx.respond('Shuffled the remaining songs in the queue.')
        await ctx.followup.send(next_songs_message)

    @commands.slash_command(name='loop_once', description='Loop the current song')
    async def loop_once(self, ctx: discord.ApplicationContext):
        ctxlog = get_context_logger(ctx)
        self.loop_type = 'once'
        ctxlog.info("Loop type set to 'once'")
        await ctx.respond('Enabled loop for the current song.')

    @commands.slash_command(name='loop_all', description='Loop all songs in queue')
    async def loop_all(self, ctx: discord.ApplicationContext):
        ctxlog = get_context_logger(ctx)
        self.loop_type = 'all'
        ctxlog.info("Loop type set to 'all'")
        await ctx.respond('Enabled loop for the queue.')

    @commands.slash_command(name='loop_off', description='Disable looping')
    async def loop_off(self, ctx: discord.ApplicationContext):
        ctxlog = get_context_logger(ctx)
        self.loop_type = None
        ctxlog.info("Loop type set to 'None'")
        await ctx.respond('Disabled looping.')

    @commands.slash_command(
        name='available_playlists', description='Display all available playlists'
    )
    async def available_playlists(self, ctx: discord.ApplicationContext):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command available_playlists')

        try:
            # Get all .txt files from the playlists directory
            playlist_files = [f for f in os.listdir(self.playlists_dir) if f.endswith('.txt')]

            if not playlist_files:
                await ctx.respond('No playlists available.')
                ctxlog.warning('No playlist files found in directory')
                return

            # Create a formatted message with all playlist names
            playlists_message = 'Available playlists:\n'
            for i, playlist in enumerate(playlist_files, 1):
                # Remove the .txt extension for display
                playlist_name = os.path.splitext(playlist)[0]
                playlists_message += f'{i}. {playlist_name}\n'

            await ctx.respond(playlists_message)
            ctxlog.success(f'Successfully displayed {len(playlist_files)} playlists')

        except Exception as e:
            error_message = f'Error accessing playlists: {str(e)}'
            ctxlog.error(error_message)
            await ctx.respond('Unable to access playlists at this time.')

    @commands.slash_command(name='play_playlist', description='Play songs from a playlist file')
    async def play_playlist(self, ctx: discord.ApplicationContext, playlist_name: str):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used play_playlist command with playlist: {playlist_name}')
        await ctx.defer()

        if ctx.author.voice is None:
            await ctx.respond('You need to join a voice channel first.')
            return

        voice_channel = ctx.author.voice.channel
        playlist_path = os.path.join(self.playlists_dir, f'{playlist_name}.txt')

        if not os.path.exists(playlist_path):
            await ctx.respond(f"Playlist '{playlist_name}' doesn't exist.")
            ctxlog.warning(f'Playlist not found: {playlist_path}')
            return

        try:
            with open(playlist_path, 'r', encoding='utf-8') as file:
                songs = [line.strip() for line in file if line.strip()]

            if not songs:
                await ctx.respond(f"Playlist '{playlist_name}' is empty.")
                return

            # Add all songs to temp queue
            random.shuffle(songs)
            self.queue.add_to_temp_queue(songs)
            total_songs = len(songs)

            # Connect to voice channel if needed
            if ctx.voice_client is None:
                await voice_channel.connect()
                await asyncio.sleep(0.5)

            # Process first song immediately if nothing is playing
            if not ctx.voice_client.is_playing():
                first_song = self.queue.get_next_temp_songs(1)[0]
                url, title, duration = await self.fetch_youtube_url(first_song)

                if url:
                    self.queue.add_song((url, title, duration))
                    ctx.voice_client.play(
                        discord.FFmpegPCMAudio(url, **self.FFMPEG_OPTIONS),
                        after=lambda e: self.bot.loop.create_task(self.play_next_song(ctx)),
                    )
                    ctxlog.success(f'Started playing: {title}')

            # Process initial batch of songs concurrently
            initial_songs = self.queue.get_next_temp_songs(self.INITIAL_SONGS_TO_LOAD)
            await ctx.respond(f'Loading playlist: "{playlist_name}" with {total_songs} songs.')

            # Fetch initial songs concurrently
            fetch_tasks = [self.fetch_youtube_url(song) for song in initial_songs]
            results = await asyncio.gather(*fetch_tasks)

            processed_count = 0
            for url, title, duration in results:
                if url:
                    self.queue.add_song((url, title, duration))
                    processed_count += 1
                    ctxlog.info(f'Added to queue: {title}')

            remaining = self.queue.get_temp_queue_size()
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
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used display_temp_queue command')
        await ctx.defer()

        temp_songs = self.queue.get_temp_queue_songs()

        if not temp_songs:
            await ctx.respond('No songs currently in the temporary queue.')
            return

        # Create formatted message
        message = ['**Songs Waiting to be Processed:**']
        for i, title in temp_songs:
            message.append(f'{i}. {title}')

        # Split message if it's too long
        formatted_message = '\n'.join(message)
        if len(formatted_message) > 1900:  # Discord message limit safety
            chunks = []
            current_chunk = [message[0]]
            current_length = len(message[0])

            for line in message[1:]:
                if current_length + len(line) + 1 > 1900:
                    chunks.append('\n'.join(current_chunk))
                    current_chunk = [line]
                    current_length = len(line)
                else:
                    current_chunk.append(line)
                    current_length += len(line) + 1

            if current_chunk:
                chunks.append('\n'.join(current_chunk))

            for i, chunk in enumerate(chunks):
                if i == 0:
                    await ctx.respond(chunk)
                else:
                    await ctx.followup.send(chunk)
        else:
            await ctx.respond(formatted_message)

        ctxlog.success('Displayed temp queue songs')

    @commands.slash_command(name='skip_multiple', description='Skip multiple songs in the queue.')
    async def skip_multiple(self, ctx: discord.ApplicationContext, number: str):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f"{ctx.author.name} used command 'skip_multiple' with number: {number}")

        # Check if music is playing
        if ctx.voice_client is None or not ctx.voice_client.is_playing():
            await ctx.respond('No music playing to be skipped.')
            ctxlog.warning('Used skip_multiple command without music playback.')
            return

        # Try to convert input to integer
        try:
            skip_count = int(number)
            if skip_count <= 0:
                await ctx.respond('Please provide a positive number.')
                ctxlog.warning(f'Invalid skip count provided: {skip_count}')
                return
        except ValueError:
            await ctx.respond('Please provide a valid number.')
            ctxlog.warning(f'Invalid input provided: {number}')
            return

        # Calculate remaining songs in queue
        remaining_songs = len(self.queue.queue) - (self.queue.current_index + 1)

        # Check if skip count is valid
        if skip_count > remaining_songs:
            await ctx.respond(
                f'Cannot skip {skip_count} songs. Only {remaining_songs} songs remaining in queue.'
            )
            ctxlog.warning(
                f'Attempted to skip more songs than available: {skip_count} > {remaining_songs}'
            )
            return

        # Store current song for message
        _ = self.get_current_song()[1]

        # Adjust the current_index before stopping
        self.queue.current_index += (
            skip_count - 1
        )  # -1 because stop() will trigger play_next_song which increments by 1

        # Stop current song which will trigger play_next_song
        ctxlog.info('Stopping current song...')
        ctx.voice_client.stop()

        await ctx.respond(f'Skipped {skip_count} songs.')
        ctxlog.success(f'Successfully skipped {skip_count} songs')

    @commands.slash_command(
        name='jump', description='Jump to a specific song in the queue by its number.'
    )
    async def jump(self, ctx: discord.ApplicationContext, number: str):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f"{ctx.author.name} used command 'jump' with number: {number}")

        # Check if music is playing
        if ctx.voice_client is None or not ctx.voice_client.is_playing():
            await ctx.respond('No music playing.')
            ctxlog.warning('Used jump command without music playback.')
            return

        # Try to convert input to integer
        try:
            jump_index = int(number)
        except ValueError:
            await ctx.respond('Please provide a valid number.')
            ctxlog.warning(f'Invalid input provided: {number}')
            return

        # Check if the index is within queue bounds
        if jump_index < 0 or jump_index >= len(self.queue.queue):
            await ctx.respond(
                f'Invalid song number. Please use a number between 0 and {len(self.queue.queue) - 1}'
            )
            ctxlog.warning(f'Jump index out of range: {jump_index}')
            return

        # Store target song name for message
        target_song = self.queue.queue[jump_index][1]

        # Store current song for message
        current_song = self.get_current_song()[1]

        # Set the index to one less than target because stop() will trigger play_next_song which increments by 1
        self.queue.current_index = jump_index - 1

        # Stop current song which will trigger play_next_song
        ctxlog.info('Stopping current song...')
        ctx.voice_client.stop()

        await ctx.respond(f'Jumped from "{current_song}" to "{target_song}"')
        ctxlog.success(f'Successfully jumped to index {jump_index}')

    @commands.slash_command(
        name='play_next',
        description='Add a song to play immediately after the current song.',
    )
    async def play_next(self, ctx: discord.ApplicationContext, query: str):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used play_next command with query: {query}')
        await ctx.defer()

        # Check if there's an active queue
        if self.queue.current_index == -1:
            await ctx.respond('No active queue. Use /play_music instead.')
            ctxlog.warning('Used play_next without active queue')
            return

        # Fetch the song info
        url, title, duration = await self.fetch_youtube_url(query)
        if not url:
            await ctx.respond('Failed to fetch the song from YouTube.')
            ctxlog.warning(f'Failed to fetch song info for query: {query}')
            return

        # Insert the song right after the current song
        insert_position = self.queue.current_index + 1
        self.queue.queue.insert(insert_position, (url, title, duration))

        await ctx.respond(f'Added "{title}" ({format_duration(duration)}) to play next')
        ctxlog.success(f'Successfully inserted song at position {insert_position}: {title}')


def setup(bot):
    bot.add_cog(MusicYT(bot))
