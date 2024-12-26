# TODO: implement clearing queue after bot disconnects
# WARN: play_playlist command bugged
import asyncio
import random
import traceback

import discord
from discord.ext import commands
from yt_dlp import YoutubeDL

from utils.logger import get_context_logger, log


class MusicQueue:
    def __init__(self):
        self.queue = []
        self.current_index = -1

    def add_song(self, song):
        self.queue.append(song)
        if self.current_index == -1:
            self.current_index = 0

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

    def get_current_song(self):
        return self.queue.current_song()

    async def fetch_youtube_url(self, query):
        with YoutubeDL(self.ydl_opts) as ydl:
            try:
                search_query = f'ytsearch:{query}' if not query.startswith('http') else query
                log.debug(f"Fetching '{search_query}' from YouTube.")
                info = ydl.extract_info(search_query, download=False)
                if 'entries' in info:
                    video = info['entries'][0]
                else:
                    video = info

                # Store the video ID or webpage URL for refreshing
                self.current_url_info = {
                    'webpage_url': video.get('webpage_url') or video.get('url'),
                    'title': video.get('title', 'Unknown Title'),
                }
                log.success('Found video!')
                log.info(
                    f"Video URL: {video.get('url')}, Video TITLE: {video.get('title', 'Unknown Title')}"
                )
                return video.get('url'), video.get('title', 'Unknown Title')

            except Exception as e:
                log.error(f'Error fetching YouTube URL: {e}')
                return None, None

    async def refresh_url(self, stored_info):
        """Refresh the streaming URL for a video"""
        log.debug('Function refresh_url invoked')
        try:
            if stored_info and stored_info['webpage_url']:
                with YoutubeDL(self.ydl_opts) as ydl:
                    info = ydl.extract_info(stored_info['webpage_url'], download=False)
                    log.success(f"URL refreshed successfully: {info.get('url')}")
                    return info.get('url'), stored_info['title']
        except Exception as e:
            log.error(f'Error refreshing URL: {e}')
        return None, None

    async def play_audio(self, ctx, url, title, after=None):
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
                new_url, _ = await self.refresh_url(self.current_url_info)
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
        queue = [elem[1] for elem in self.queue.queue]

        ctxlog.info(f'Queue from play_next_song: {queue}')
        try:
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
                url, title = current_song

                # Only try to connect if we're not already connected
                if ctx.voice_client is None:
                    voice_channel = ctx.author.voice.channel
                    await voice_channel.connect()
                    await asyncio.sleep(0.5)

                if ctx.voice_client and not ctx.voice_client.is_playing():
                    success = await self.play_audio(
                        ctx,
                        url,
                        title,
                        after=lambda e: self.bot.loop.create_task(self.play_next_song(ctx)),
                    )
                    ctxlog.success('play_next_song ran successfully')

                    if success:
                        await ctx.followup.send(f'Now playing: {title}')
                    else:
                        await ctx.followup.send('Failed to play the current song, skipping...')
                        await self.play_next_song(ctx)
            else:
                if ctx.voice_client and not ctx.voice_client.is_playing():
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

        url, title = await self.fetch_youtube_url(query)
        if not url:
            await ctx.respond(f"Failed to fetch the song '{query}' from YouTube.")
            return

        self.queue.add_song((url, title))
        await ctx.respond(f'Added {title} to the queue.')
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
                    url, title = current_song

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
        url, title = await self.fetch_youtube_url(query)
        if not url:
            await ctx.respond('Failed to fetch the song from YouTube.')
            return

        self.queue.add_song((url, title))
        await ctx.respond(f'Added {title} to the queue.')
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
            song_title = current_song[1]
            await ctx.respond(f'Now playing {song_title}.')
            ctxlog.success(f'Now playing {song_title}.')

    @commands.slash_command(name='display_queue_long', description='Display the entire queue.')
    async def display_queue_long(self, ctx: discord.ApplicationContext):
        ctxlog = get_context_logger(ctx)
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
                    queue_message += str(i) + '. ' + str(self.queue.queue[i][1]) + ' ▶️\n'
                else:
                    queue_message += str(i) + '. ' + str(self.queue.queue[i][1]) + '\n'
            queue_message = (
                f'Currently playing {self.queue.current_index + 1} of {total_length}\n'
                + queue_message
            )
            if len(queue_message) > 2000:
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
        n = 10
        if len(next_song_titles) < 10:
            n = len(next_song_titles)
        queue_message = f'Next {n} songs in queue:\n'
        for i in range(len(next_song_titles)):
            queue_message += f'\n{i}. {next_song_titles[i]}'
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
        ctxlog.success('Shuffled the songs and updated the queue.')

        await ctx.respond('Shuffled the remaining songs in the queue.')

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


def setup(bot):
    bot.add_cog(MusicYT(bot))
