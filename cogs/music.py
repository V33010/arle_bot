import discord
from discord.ext import commands
import os
import asyncio
import random
import time
import lyricsgenius
from pydub import AudioSegment
from mutagen.id3 import ID3
from mutagen.mp3 import MP3


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


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = MusicQueue()
        self.loop_type = None  # "once"  # can be "all", "once" or None
        self.now_playing_message = None
        self.song_start_time = None
        self.song_duration = None
        self.message_channel = None

    def get_current_song(self):
        return self.queue.current_song()

    def get_song_duration(self, filename):
        audio = AudioSegment.from_file(filename)
        return len(audio) / 1000

    @commands.slash_command(
        name="play_music", description="Play a music file in your voice channel."
    )
    async def play_music(self, ctx: discord.ApplicationContext, filename: str):
        await ctx.defer()
        await ctx.respond(f"Loop type: {self.loop_type}")
        if ctx.author.voice is None:
            await ctx.respond("You need to join a voice channel first.")
            return
        voice_channel = ctx.author.voice.channel

        if not os.path.isfile(filename):
            await ctx.respond("The specified file does not exist.")
            return

        if ctx.voice_client is None:
            vc = await voice_channel.connect()
        else:
            vc = ctx.voice_client

        await ctx.respond(f"Added {filename} to the queue.")

        self.queue.add_song(filename)
        self.queue.current_index = len(self.queue.queue) - 1
        if vc.is_playing():
            vc.stop()
        else:
            pass
        self.song_start_time = time.time()
        self.song_duration = self.get_song_duration(filename)
        vc.play(
            discord.FFmpegPCMAudio(filename),
            after=lambda e: self.bot.loop.create_task(self.play_next_song(ctx)),
        )
        await self.create_now_playing_message(ctx)

    async def destroy_now_playing_message(self):
        if self.now_playing_message:
            try:
                await self.now_playing_message.delete()
            except discord.errors.HTTPException as e:
                if e.code == 50027:
                    pass
                else:
                    raise e
            finally:
                self.now_playing_message = None

    async def play_next_song(self, ctx):
        print(f"Queue from play_next_song: {self.queue.queue}")
        try:
            await self.destroy_now_playing_message()
            current_song = None
            if self.get_current_song():
                if (
                    self.loop_type == "all"
                    and self.queue.current_index == len(self.queue.queue) - 1
                ):
                    self.queue.current_index = 0
                    current_song = self.get_current_song()
                elif self.loop_type == "once":
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
                    discord.FFmpegPCMAudio(current_song),
                    after=lambda e: self.bot.loop.create_task(self.play_next_song(ctx)),
                )
                await self.create_now_playing_message(ctx)
            else:
                if ctx.voice_client:
                    if (
                        not ctx.voice_client.is_playing()
                        and not ctx.voice_client.is_paused()
                    ):
                        await ctx.voice_client.disconnect()
                else:
                    print("The bot is not connected to a voice channel.")
        except Exception as e:
            print(f"Error in play_next_song: {e}")
            if current_song and ctx.voice_client:
                ctx.voice_client.play(
                    discord.FFmpegPCMAudio(current_song),
                    after=lambda e: self.bot.loop.create_task(self.play_next_song(ctx)),
                )

    async def create_now_playing_message(self, ctx):
        try:
            self.message_channel = ctx.channel
            print(f"current_song: {self.get_current_song()}")
            if self.get_current_song():
                audio = ID3(self.get_current_song())
                song_title = audio.get("TIT2", "Unknown Title")
            else:
                song_title = self.get_current_song()
            queue_length = len(self.queue.queue) - (self.queue.current_index + 1)
            embed = discord.Embed(title="Now playing", color=discord.Color.blue())
            embed.add_field(name="Song", value=song_title, inline=False)
            embed.add_field(
                name="Progress", value=self.create_progress_bar(0), inline=False
            )
            embed.set_footer(text=f"0s / {int(self.song_duration)}s")
            embed.add_field(name="Songs in queue", value=queue_length)

            if hasattr(ctx, "responded") and ctx.responded:
                self.now_playing_message = await self.message_channel.send(embed=embed)
            else:
                self.now_playing_message = await ctx.respond(embed=embed)

            await self.update_now_playing(ctx)

        except Exception as e:
            print(f"Error in create_now_playing_message: {e}")
            pass

    async def update_now_playing(self, ctx):
        if (
            self.get_current_song()
            and self.now_playing_message
            and self.message_channel
        ):
            try:
                elapsed_time = time.time() - self.song_start_time
                progress = elapsed_time / self.song_duration
                queue_length = len(self.queue.queue) - self.queue.current_index - 1
                embed = discord.Embed(title="Now Playing", color=discord.Color.blue())
                if self.get_current_song():
                    audio = ID3(self.get_current_song())
                    song_title = audio.get("TIT2", "Unknown Title")
                    embed.add_field(name="Song", value=song_title, inline=False)
                embed.add_field(
                    name="Progress",
                    value=self.create_progress_bar(progress),
                    inline=False,
                )
                embed.add_field(name="Songs in queue", value=queue_length)

                song_duration_MMSS = time.strftime(
                    "%M:%S", time.gmtime(self.song_duration)
                )
                elapsed_time_MMSS = time.strftime("%M:%S", time.gmtime(elapsed_time))
                embed.set_footer(text=f"{elapsed_time_MMSS} / {song_duration_MMSS}")
                try:
                    await self.now_playing_message.edit(embed=embed)
                except discord.errors.HTTPException as e:
                    if e.code == 50027:
                        await self.destroy_now_playing_message()
                        self.now_playing_message = await self.message_channel.send(
                            embed=embed
                        )
                    else:
                        raise e
                await asyncio.sleep(7.5)
                await self.update_now_playing(ctx)
            except Exception as e:
                print(f"Error in update_now_playing: {e}")
                pass

    def create_progress_bar(self, progress):
        total_blocks = 20
        filled_blocks = int(total_blocks * progress)
        empty_blocks = total_blocks - filled_blocks
        return f"[{'█' * filled_blocks}{'░' * empty_blocks}]"

    @commands.slash_command(
        name="add_to_queue", description="Add a music file to the queue."
    )
    async def add_to_queue(self, ctx: discord.ApplicationContext, filename: str):
        if not os.path.isfile(filename):
            await ctx.respond("The specified file does not exist.")
            return

        self.queue.add_song(filename)
        await ctx.respond(
            f"Added {filename} to the queue.\nSongs in  queue: {len(self.queue.queue) - self.queue.current_index - 1}"
        )

        if not ctx.voice_client or not ctx.voice_client.is_playing():
            await self.play_next_song(ctx)

    @commands.slash_command(
        name="nowplaying", description="Display the currently playing song."
    )
    async def nowplaying(self, ctx: discord.ApplicationContext):
        if not self.get_current_song():
            await ctx.respond("No song is currently playing.")
            return
        else:
            current_song = self.get_current_song()
            audio = ID3(current_song)
            song_title = audio.get("TIT2", "Unknown Title")
            await ctx.respond(f"Now playing {song_title}.")

    @commands.slash_command(
        name="display_queue_long", description="Display the entire queue."
    )
    async def display_queue_long(self, ctx: discord.ApplicationContext):
        total_length = len(self.queue.queue)
        if total_length == 0:
            await ctx.respond("The queue is currently empty.")
        else:
            print(f"current_index from display_queue_long: {self.queue.current_index}")
            queue_message = ""
            for i in range(total_length):
                if i == self.queue.current_index:
                    queue_message += (
                        str(i)
                        + ". "
                        + str(ID3(self.queue.queue[i]).get("TIT2", "Unknown Title"))
                        + " ▶️\n"
                    )
                else:
                    queue_message += (
                        str(i)
                        + ". "
                        + str(ID3(self.queue.queue[i]).get("TIT2", "Unknown Title"))
                        + "\n"
                    )
            queue_message = (
                f"Currently playing {self.queue.current_index + 1} of {total_length}\n"
                + queue_message
            )
            if len(queue_message) > 2000:
                chunks = [
                    queue_message[i : i + 2000]
                    for i in range(0, len(queue_message), 2000)
                ]
                for chunk in chunks:
                    await ctx.send(chunk)
            else:
                await ctx.respond(queue_message)

    @commands.slash_command(
        name="lyrics_from_file",
        description="Fetch and display the lyrics of the currently playing song.",
    )
    async def lyrics(self, ctx: discord.ApplicationContext):
        if not self.get_current_song():
            await ctx.respond("No song is currently playing.")

        try:
            print(f"Fetching Lyrics for {self.get_current_song()}")
            audio_file = MP3(self.get_current_song(), ID3=ID3)
            lyrics = audio_file.tags.getall("USLT")
            if lyrics:
                lyrics_text = lyrics[0].text
                await ctx.respond(f"Lyrics for **{self.get_current_song()}**")

                if len(lyrics_text) > 2000:
                    chunks = [
                        lyrics_text[i : i + 2000]
                        for i in range(0, len(lyrics_text), 2000)
                    ]
                    for chunk in chunks:
                        await ctx.send(chunk)
                elif lyrics_text:
                    await ctx.send(lyrics_text)
            else:
                await ctx.respond("No lyrics found for the currently playing song.")
        except Exception as e:
            await ctx.respond(f"Error fetching lyrics: {e}")

    @commands.slash_command(
        name="past_songs", description="Display the previously played songs."
    )
    async def past_songs(self, ctx: discord.ApplicationContext):
        if self.queue.current_index < 1:
            await ctx.respond("There are no past songs.")
        else:
            past_songs = ""
            for i in range(0, self.queue.current_index):
                past_songs += self.queue.queue[i] + "\n"

            if len(past_songs) > 2000:
                chunks = [
                    past_songs[j : j + 2000] for j in range(0, len(past_songs), 2000)
                ]
                for chunk in chunks:
                    await ctx.send(chunk)
            else:
                await ctx.respond(past_songs)

    @commands.slash_command(name="previous", description="Play the previous song.")
    async def previous(self, ctx: discord.ApplicationContext):
        await ctx.defer()

        if self.queue.current_index < 1:
            await ctx.respond("No previously played songs.")
            return

        # Stop current playback and destroy message
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
        await self.destroy_now_playing_message()

        # Update current index and get previous song
        self.queue.current_index -= 1  # Directly decrement the index
        current_song = self.queue.current_song()  # Get the song at new index

        if not current_song:
            await ctx.respond("Error accessing previous song.")
            return

        # Update timing information for the correct song
        self.song_start_time = time.time()
        self.song_duration = self.get_song_duration(current_song)

        # Connect to voice if needed
        if ctx.voice_client is None:
            voice_channel = ctx.author.voice.channel
            vc = await voice_channel.connect()
        else:
            vc = ctx.voice_client

        # Play the previous song
        vc.play(
            discord.FFmpegPCMAudio(current_song),
            after=lambda e: self.bot.loop.create_task(self.play_next_song(ctx)),
        )

        await self.create_now_playing_message(ctx)

    @commands.slash_command(name="skip", description="Skip the current song.")
    async def skip(self, ctx: discord.ApplicationContext):
        if ctx.voice_client is None or not ctx.voice_client.is_playing():
            await ctx.respond("No music playing to be skipped.")
            return

        if self.queue.current_index < len(self.queue.queue) - 1:
            ctx.voice_client.stop()
        else:
            ctx.voice_client.stop()
            await ctx.voice_client.disconnect()

        current_song_title = ID3(self.get_current_song()).get("TIT2", "Unknown Title")

        await ctx.respond(f"Skipped {current_song_title}")
        if self.queue.current_index < len(self.queue.queue) - 1:
            await self.play_next_song(ctx)

    @commands.slash_command(name="pause", description="Pause the current song.")
    async def pause(self, ctx: discord.ApplicationContext):
        if ctx.voice_client is None or not ctx.voice_client.is_playing():
            await ctx.respond("No music playing.")
            return

        ctx.voice_client.pause()
        await self.destroy_now_playing_message()
        await ctx.respond("Paused the song.")

    @commands.slash_command(name="play", description="Resume playing the paused song.")
    async def play(self, ctx: discord.ApplicationContext):
        if ctx.voice_client is None:
            await ctx.respond("No music queued.")
            return

        if ctx.voice_client.is_playing():
            await ctx.respond("Music already playing.")

        if ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.respond(
                f"Resumed playing {str(ID3(self.get_current_song()).get('TIT2', 'Unknown Title'))}"
            )
            await self.create_now_playing_message(ctx)
        else:
            await ctx.respond("No music queued.")

    @commands.slash_command(
        name="stop", description="Stop the music and clear the queue."
    )
    async def stop(self, ctx: discord.ApplicationContext):
        await self.destroy_now_playing_message()
        self.queue.queue = []
        self.queue.current_index = -1

        if ctx.voice_client is None:
            await ctx.respond("No music playing.")
            return

        ctx.voice_client.stop()
        await ctx.voice_client.disconnect()
        await ctx.respond(
            "Stopped the music, cleared the queue, and disconnected from the voice channel."
        )

    @commands.slash_command(
        name="lyrics_from_genius", description="Fetch lyrics from genius.com"
    )
    async def lyrics_from_genius(self, ctx: discord.ApplicationContext, song: str):
        await ctx.defer()
        api_key = os.getenv("genius_token")
        genius = lyricsgenius.Genius(api_key)
        song_name = song
        song = genius.search_song(song)
        if song:
            await ctx.respond(f"Lyrics for **{song.title}** by **{song.artist}**")
            if len(song.lyrics) > 2000:
                chunks = [
                    song.lyrics[i : i + 2000] for i in range(0, len(song.lyrics), 2000)
                ]
                for chunk in chunks:
                    await ctx.send(chunk)
            else:
                await ctx.send(song.lyrics)
        else:
            await ctx.respond(f"No lyrics found for {song_name}")

    @commands.slash_command(
        name="play_playlist",
        description="Play all audio files in the specified folder.",
    )
    async def play_playlist(self, ctx: discord.ApplicationContext, folder: str):
        if not os.path.isdir(folder):
            await ctx.respond("The specified folder does not exist.")
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
            await ctx.respond("You need to join a voice channel first.")
            return
        voice_channel = ctx.author.voice.channel

        if ctx.voice_client is None:
            vc = await voice_channel.connect()
        else:
            vc = ctx.voice_client

        await ctx.respond(f"Added and shuffled all audio files from {folder} to queue.")
        if self.queue.current_index == 0:
            self.song_start_time = time.time()
            self.song_duration = self.get_song_duration(self.get_current_song())
            vc.play(
                discord.FFmpegPCMAudio(self.get_current_song()),
                after=lambda e: self.bot.loop.create_task(self.play_next_song(ctx)),
            )
            await self.create_now_playing_message(ctx)
        else:  # if the bot is already playing something -> do nothing
            pass

    @commands.slash_command(
        name="display_queue",
        description="Display the next 10 songs and total songs in queue",
    )
    async def display_queue(self, ctx: discord.ApplicationContext):
        if len(self.queue.queue) == 0:
            await ctx.respond("The queue is currently empty.")
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
                next_song_titles.append(
                    str(ID3(next_songs[i]).get("TIT2", "Unknown Title"))
                )
            except Exception:
                next_song_titles.append(next_songs[i])
        n = 10
        if len(next_song_titles) < 10:
            n = len(next_song_titles)
        queue_message = f"Next {n} songs in queue:\n"
        for i in range(len(next_song_titles)):
            queue_message += f"\n{i}. {next_song_titles[i]}"
        total_songs = len(self.queue.queue[self.queue.current_index :])
        queue_message += f"\n\nTotal songs in queue: {total_songs}"

        await ctx.respond(queue_message)

    @commands.slash_command(
        name="shuffle", description="Shuffle all the remaining songs in the queue."
    )
    async def shuffle(self, ctx: discord.ApplicationContext):
        if len(self.queue.queue) == 0:
            await ctx.respond("The queue is empty.")
            return
        remaining_songs = self.queue.queue[self.queue.current_index + 1 :]
        # shuffle the remaining songs
        random.shuffle(remaining_songs)
        # update the queue
        self.queue.queue = (
            self.queue.queue[: self.queue.current_index + 1] + remaining_songs
        )

        await ctx.respond("Shuffled the remaining songs in the queue.")

    @commands.slash_command(name="loop_once", description="Loop the current song")
    async def loop_once(self, ctx: discord.ApplicationContext):
        self.loop_type = "once"
        await ctx.respond("Enabled loop for the current song.")

    @commands.slash_command(name="loop_all", description="Loop all songs in queue")
    async def loop_all(self, ctx: discord.ApplicationContext):
        self.loop_type = "all"
        await ctx.respond("Enabled loop for the queue.")

    @commands.slash_command(name="loop_off", description="Disable looping")
    async def loop_off(self, ctx: discord.ApplicationContext):
        self.loop_type = None
        await ctx.respond("Disabled looping.")


#
#
#
#
#
#
#
#
#
#
#
#
#

print("Hello, ")


def setup(bot):
    bot.add_cog(Music(bot))
    #
    #
    #
    #
    #
    #
    #
    #
    #
    #
    #
    #
    #
    #
    #
    #
    #
    #
