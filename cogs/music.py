import asyncio
import os
import random
import time
import tomllib

import discord
from discord.ext import commands
from mutagen.id3 import ID3
from mutagen.mp3 import MP3
from pydub import AudioSegment

from utils.logger import get_context_logger, log
from validators.config import ConfigValidator

with open(os.path.join('config.toml'), 'rb') as f:
    data = tomllib.load(f)
arle_config: ConfigValidator = ConfigValidator.model_validate(data)


class MusicQueue:
    def __init__(self):
        self.queue = []
        self.current_index = -1
        log.warning('NO LOGS FOR MUSIC COG')

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


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = MusicQueue()
        self.loop_type = None  # "once"  # can be "all", "once" or None
        self.now_playing_message = None
        self.song_start_time = None
        self.song_duration = None
        self.message_channel = None
        self.FFMPEG_OPTIONS = {
            'options': '-vn -af "atempo=0.97,aresample=44100:filter_size=64:phase_shift=8"',
        }

    def get_current_song(self):
        return self.queue.current_song()

    def get_song_duration(self, filename):
        audio = AudioSegment.from_file(filename)
        return len(audio) / 1000

    @commands.slash_command(
        name='play_music', description='Play a music file in your voice channel.'
    )
    async def play_music(self, ctx: discord.ApplicationContext, filename: str):
        ctxlog = get_context_logger(ctx)
        ctxlog.info('Got play_music request.')
        await ctx.defer()
        await ctx.respond(f'Loop type: {self.loop_type}')
        if ctx.author.voice is None:
            await ctx.respond('You need to join a voice channel first.')
            return
        voice_channel = ctx.author.voice.channel

        if not os.path.isfile(filename):
            await ctx.respond('The specified file does not exist.')
            return

        if ctx.voice_client is None:
            vc = await voice_channel.connect()
        else:
            vc = ctx.voice_client

        await ctx.respond(f'Added {filename} to the queue.')
        ctxlog.info(f'Added {filename} to the queue.')

        self.queue.add_song(filename)
        self.queue.current_index = len(self.queue.queue) - 1
        if vc.is_playing():
            vc.stop()
        else:
            pass
        self.song_start_time = time.time()
        self.song_duration = self.get_song_duration(filename)
        vc.play(
            discord.FFmpegPCMAudio(filename, **self.FFMPEG_OPTIONS),
            after=lambda e: self.bot.loop.create_task(self.play_next_song(ctx)),
        )
        ctxlog.success(f'Music started in {voice_channel}.')
        await self.create_now_playing_message(ctx)
        ctxlog.info('Created now_playing_message through play_music command.')

    async def destroy_now_playing_message(self):
        if self.now_playing_message:
            try:
                await self.now_playing_message.delete()
            except discord.errors.NotFound:
                log.error('Now playing message not found, skipping deletion.')
            except discord.errors.HTTPException as e:
                log.error(
                    'Received discord.errors.HTTPException with code 50027 in destroy_now_playing_message.'
                )
                if e.code == 50027:
                    pass
                else:
                    raise e
            finally:
                self.now_playing_message = None

    async def play_next_song(self, ctx):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'Queue from play_next_song: {self.queue.queue}')
        try:
            await self.destroy_now_playing_message()
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

            if current_song:
                self.song_start_time = time.time()
                self.song_duration = self.get_song_duration(current_song)

                if ctx.voice_client is None:
                    voice_channel = ctx.author.voice.channel
                    vc = await voice_channel.connect()
                else:
                    vc = ctx.voice_client
                if vc.is_playing():
                    vc.stop()
                vc.play(
                    discord.FFmpegPCMAudio(current_song, **self.FFMPEG_OPTIONS),
                    after=lambda e: self.bot.loop.create_task(self.play_next_song(ctx)),
                )
                await self.create_now_playing_message(ctx)
            else:
                if ctx.voice_client:
                    if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
                        await ctx.voice_client.disconnect()
                else:
                    print('The bot is not connected to a voice channel.')
        except Exception as e:
            ctxlog.error(f'Error in play_next_song: {e}')
            if ctx.voice_client:
                current_song = self.get_current_song()
                ctx.voice_client.play(
                    discord.FFmpegPCMAudio(current_song, **self.FFMPEG_OPTIONS),
                    after=lambda e: self.bot.loop.create_task(self.play_next_song(ctx)),
                )

    async def create_now_playing_message(self, ctx):
        ctxlog = get_context_logger(ctx)
        ctxlog.info('create_now_playing_message invoked')
        try:
            self.message_channel = ctx.channel
            ctxlog.info(f'current_song: {self.get_current_song()}')
            if self.get_current_song():
                audio = ID3(self.get_current_song())
                song_title = audio.get('TIT2', 'Unknown Title')
            else:
                song_title = self.get_current_song()
            queue_length = len(self.queue.queue) - (self.queue.current_index + 1)
            embed = discord.Embed(title='Now playing', color=discord.Color.blue())
            embed.add_field(name='Song', value=song_title, inline=False)
            embed.add_field(name='Progress', value=self.create_progress_bar(0), inline=False)
            embed.set_footer(text=f'0s / {int(self.song_duration)}s')
            embed.add_field(name='Songs in queue', value=queue_length)

            if hasattr(ctx, 'responded') and ctx.responded:
                self.now_playing_message = await self.message_channel.send(embed=embed)
            else:
                self.now_playing_message = await ctx.respond(embed=embed)

            await self.update_now_playing(ctx)

        except Exception as e:
            ctxlog.error(f'Error in create_now_playing_message: {e}')
            pass

    async def update_now_playing(self, ctx):
        ctxlog = get_context_logger(ctx)
        ctxlog.info('update_now_playing invoked')
        if self.get_current_song() and self.now_playing_message and self.message_channel:
            try:
                elapsed_time = time.time() - self.song_start_time
                progress = elapsed_time / self.song_duration
                queue_length = len(self.queue.queue) - self.queue.current_index - 1
                embed = discord.Embed(title='Now Playing', color=discord.Color.blue())
                if self.get_current_song():
                    audio = ID3(self.get_current_song())
                    song_title = audio.get('TIT2', 'Unknown Title')
                    embed.add_field(name='Song', value=song_title, inline=False)
                embed.add_field(
                    name='Progress',
                    value=self.create_progress_bar(progress),
                    inline=False,
                )
                embed.add_field(name='Songs in queue', value=queue_length)

                song_duration_MMSS = time.strftime('%M:%S', time.gmtime(self.song_duration))
                elapsed_time_MMSS = time.strftime('%M:%S', time.gmtime(elapsed_time))
                embed.set_footer(text=f'{elapsed_time_MMSS} / {song_duration_MMSS}')
                try:
                    await self.now_playing_message.edit(embed=embed)
                    ctxlog.success('now_playing_message edited successfully!')
                except discord.errors.HTTPException as e:
                    if e.code == 50027:
                        ctxlog.error(
                            'Received discord.errors.HTTPException with code 50027 in update_now_playing.'
                        )
                        await self.destroy_now_playing_message()
                        self.now_playing_message = await self.message_channel.send(embed=embed)
                    else:
                        raise e
                await asyncio.sleep(7.5)
                await self.update_now_playing(ctx)
            except Exception as e:
                ctxlog.error(f'Error in update_now_playing: {e}')
                pass

    def create_progress_bar(self, progress):
        total_blocks = 20
        filled_blocks = int(total_blocks * progress)
        empty_blocks = total_blocks - filled_blocks
        return f"[{'█' * filled_blocks}{'░' * empty_blocks}]"

    @commands.slash_command(name='add_to_queue', description='Add a music file to the queue.')
    async def add_to_queue(self, ctx: discord.ApplicationContext, filename: str):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used add_to_queue command.')
        if not os.path.isfile(filename):
            await ctx.respond('The specified file does not exist.')
            return

        self.queue.add_song(filename)
        ctxlog.success(f'{filename} added to queue by {ctx.author.name}.')
        await ctx.respond(
            f'Added {filename} to the queue.\nSongs in  queue: {len(self.queue.queue) - self.queue.current_index - 1}'
        )

        if not ctx.voice_client or not ctx.voice_client.is_playing():
            ctxlog.warning(f'{ctx.author.name} added song to empty queue.')
            await self.play_next_song(ctx)

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
            audio = ID3(current_song)
            song_title = audio.get('TIT2', 'Unknown Title')
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
                    queue_message += (
                        str(i)
                        + '. '
                        + str(ID3(self.queue.queue[i]).get('TIT2', 'Unknown Title'))
                        + ' ▶️\n'
                    )
                else:
                    queue_message += (
                        str(i)
                        + '. '
                        + str(ID3(self.queue.queue[i]).get('TIT2', 'Unknown Title'))
                        + '\n'
                    )
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

    @commands.slash_command(
        name='lyrics_from_file',
        description='Fetch and display the lyrics of the currently playing song.',
    )
    async def lyrics(self, ctx: discord.ApplicationContext):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used lyrics_from_file command.')
        if not self.get_current_song():
            await ctx.respond('No song is currently playing.')

        try:
            print(f'Fetching Lyrics for {self.get_current_song()}')
            audio_file = MP3(self.get_current_song(), ID3=ID3)
            lyrics = audio_file.tags.getall('USLT')
            if lyrics:
                lyrics_text = lyrics[0].text
                await ctx.respond(f'Lyrics for **{self.get_current_song()}**')

                if len(lyrics_text) > 2000:
                    chunks = [lyrics_text[i : i + 2000] for i in range(0, len(lyrics_text), 2000)]
                    for chunk in chunks:
                        await ctx.send(chunk)
                    ctxlog.success('Lyrics sent successfully with chunking.')
                elif lyrics_text:
                    await ctx.send(lyrics_text)
                    ctxlog.success('Lyrics sent successfully without chunking.')
            else:
                ctxlog.warning('No lyrics found for the currently playing song.')
                await ctx.respond('No lyrics found for the currently playing song.')
        except Exception as e:
            ctxlog.error(f'Error in fetching lyrics: {e}')
            await ctx.respond(f'Error fetching lyrics: {e}')

    @commands.slash_command(name='past_songs', description='Display the previously played songs.')
    async def past_songs(self, ctx: discord.ApplicationContext):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command past_songs.')
        if self.queue.current_index < 1:
            await ctx.respond('There are no past songs.')
        else:
            past_songs = ''
            for i in range(0, self.queue.current_index):
                past_songs += self.queue.queue[i] + '\n'

            if len(past_songs) > 2000:
                chunks = [past_songs[j : j + 2000] for j in range(0, len(past_songs), 2000)]
                for chunk in chunks:
                    await ctx.send(chunk)
                ctxlog.success('Past songs displayed with chunking.')
            else:
                ctxlog.success('Past songs displayed without chunking.')
                await ctx.respond(past_songs)

    @commands.slash_command(
        name='previous', description='Play the previous song.'
    )  # BUG: Using this command causes Error in update_now_playing: 404 Not Found (Error code: 10008)
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
            self.queue.current_index = 0  # TODO fix the need to use this approach. The current method does not allow the first song from the queue to be played.
        ctxlog.debug(f'Current index after manual update: {self.queue.current_index}')
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            ctxlog.success('Current song stopped successfully.')
            ctx.respond('Playing previous song.')

    @commands.slash_command(name='skip', description='Skip the current song.')
    async def skip(self, ctx: discord.ApplicationContext):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command skip')
        if ctx.voice_client is None or not ctx.voice_client.is_playing():
            await ctx.respond('No music playing to be skipped.')
            return

        current_song_title = ID3(self.get_current_song()).get('TIT2', 'Unknown Title')
        ctxlog.info('Stopping current song...')
        ctx.voice_client.stop()

        await ctx.respond(f'Skipped {current_song_title}')
        ctxlog.success('Skipped current song.')

    @commands.slash_command(
        name='pause', description='Pause the current song.'
    )  # BUG: time does not pause when using this command leading to unusual behaviour in create_progress_bar
    async def pause(self, ctx: discord.ApplicationContext):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command pause.')
        if ctx.voice_client is None or not ctx.voice_client.is_playing():
            ctxlog.warning('No music playing')
            await ctx.respond('No music playing.')
            return

        ctx.voice_client.pause()
        await self.destroy_now_playing_message()
        ctxlog.debug('Destroyed now_playing_message')
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
            await ctx.respond(
                f"Resumed playing {str(ID3(self.get_current_song()).get('TIT2', 'Unknown Title'))}"
            )
            ctxlog.success('Resumed music playback.')
            await self.create_now_playing_message(ctx)
            ctxlog.success('Created now_playing_message')
        else:
            await ctx.respond('No music queued.')

    @commands.slash_command(name='stop', description='Stop the music and clear the queue.')
    async def stop(self, ctx: discord.ApplicationContext):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command stop')
        await self.destroy_now_playing_message()
        ctxlog.debug('Destroyed now_playing_message')
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
        name='play_playlist',
        description='Play all audio files in the specified folder.',
    )
    async def play_playlist(self, ctx: discord.ApplicationContext, folder: str):
        ctxlog = get_context_logger(ctx)
        ctxlog.info(f'{ctx.author.name} used command play_playlist.')
        if not os.path.isdir(folder):
            await ctx.respond('The specified folder does not exist.')
            ctxlog.warning(f'Specified folder does not exist: {folder}')
            return

        temp_queue = []
        for file in os.listdir(folder):
            file_path = os.path.join(folder, file)
            if os.path.isfile(file_path):
                temp_queue.append(file_path)

        random.shuffle(temp_queue)

        for song in temp_queue:
            self.queue.add_song(song)

        if ctx.author.voice is None:
            ctxlog.warning('Used command without joining a voice channel')
            await ctx.respond('You need to join a voice channel first.')
            return
        voice_channel = ctx.author.voice.channel

        if ctx.voice_client is None:
            vc = await voice_channel.connect()
        else:
            vc = ctx.voice_client

        ctxlog.debug('Added songs to queue.')
        await ctx.respond(f'Added and shuffled all audio files from {folder} to queue.')
        if self.queue.current_index == 0:
            self.song_start_time = time.time()
            self.song_duration = self.get_song_duration(self.get_current_song())
            vc.play(
                discord.FFmpegPCMAudio(self.get_current_song(), **self.FFMPEG_OPTIONS),
                after=lambda e: self.bot.loop.create_task(self.play_next_song(ctx)),
            )
            await self.create_now_playing_message(ctx)
        else:  # if the bot is already playing something -> do nothing
            pass

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
        next_song_titles = []
        for i in range(len(next_songs)):
            try:
                next_song_titles.append(str(ID3(next_songs[i]).get('TIT2', 'Unknown Title')))
                ctxlog.debug(f'Title found for {next_songs[i]}')
            except Exception:
                ctxlog.debug(f'Title not found for {next_songs[i]}, using filename for display')
                next_song_titles.append(next_songs[i])
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
        # shuffle the remaining songs
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
    bot.add_cog(Music(bot))
