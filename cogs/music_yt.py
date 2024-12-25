import asyncio
import random
import time

import discord
from discord.ext import commands
from yt_dlp import YoutubeDL

from utils.logger import log


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
        self.song_start_time = None
        self.song_duration = None
        self.FFMPEG_OPTIONS = {
            "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            "options": '-vn -af "aresample=44100:filter_size=64:phase_shift=8"',
        }

        self.ydl_opts = {
            "format": "bestaudio",
            "noplaylist": True,
            "quiet": True,
            "extract_flat": False,
            # Add these options to help with stream stability
            "socket_timeout": 10,
            "retries": 5,
            "nocheckcertificate": True,
        }
        self.current_url_info = None

    def get_current_song(self):
        return self.queue.current_song()

    async def fetch_youtube_url(self, query):
        with YoutubeDL(self.ydl_opts) as ydl:
            try:
                search_query = (
                    f"ytsearch:{query}" if not query.startswith("http") else query
                )
                info = ydl.extract_info(search_query, download=False)
                if "entries" in info:
                    video = info["entries"][0]
                else:
                    video = info

                # Store the video ID or webpage URL for refreshing
                self.current_url_info = {
                    "webpage_url": video.get("webpage_url") or video.get("url"),
                    "title": video.get("title", "Unknown Title"),
                }

                return video.get("url"), video.get("title", "Unknown Title")
            except Exception as e:
                log.error(f"Error fetching YouTube URL: {e}")
                return None, None

    async def refresh_url(self, stored_info):
        """Refresh the streaming URL for a video"""
        try:
            if stored_info and stored_info["webpage_url"]:
                with YoutubeDL(self.ydl_opts) as ydl:
                    info = ydl.extract_info(stored_info["webpage_url"], download=False)
                    return info.get("url"), stored_info["title"]
        except Exception as e:
            log.error(f"Error refreshing URL: {e}")
        return None, None

    async def play_audio(self, ctx, url, title, after=None):
        """Helper function to handle audio playback with error recovery"""
        try:
            if ctx.voice_client:
                ctx.voice_client.play(
                    discord.FFmpegPCMAudio(url, **self.FFMPEG_OPTIONS), after=after
                )
                return True
        except Exception as e:
            log.error(f"Playback error: {e}")
            # Try to refresh the URL and play again
            if self.current_url_info:
                new_url, _ = await self.refresh_url(self.current_url_info)
                if new_url:
                    try:
                        ctx.voice_client.play(
                            discord.FFmpegPCMAudio(new_url, **self.FFMPEG_OPTIONS),
                            after=after,
                        )
                        return True
                    except Exception as e2:
                        log.error(f"Error after URL refresh: {e2}")
        return False

    async def play_next_song(self, ctx):
        try:
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

            if current_song and ctx.voice_client:
                url, title = current_song
                self.song_start_time = time.time()

                # Only try to connect if we're not already connected
                if ctx.voice_client is None:
                    voice_channel = ctx.author.voice.channel
                    await voice_channel.connect()
                    await asyncio.sleep(1)

                if ctx.voice_client and not ctx.voice_client.is_playing():
                    success = await self.play_audio(
                        ctx,
                        url,
                        title,
                        after=lambda e: self.bot.loop.create_task(
                            self.play_next_song(ctx)
                        ),
                    )

                    if success:
                        await ctx.followup.send(f"Now playing: {title}")
                    else:
                        await ctx.followup.send(
                            "Failed to play the current song, skipping..."
                        )
                        await self.play_next_song(ctx)
            else:
                if ctx.voice_client and not ctx.voice_client.is_playing():
                    await ctx.voice_client.disconnect()
        except Exception as e:
            log.error(f"Error in play_next_song: {e}")
            import traceback

            log.error(traceback.format_exc())

    @commands.slash_command(
        name="play_music", description="Play a music file in your voice channel."
    )
    async def play_music(self, ctx: discord.ApplicationContext, query: str):
        await ctx.defer()

        if ctx.author.voice is None:
            await ctx.respond("You need to join a voice channel first.")
            return

        voice_channel = ctx.author.voice.channel

        url, title = await self.fetch_youtube_url(query)
        if not url:
            await ctx.respond(f"Failed to fetch the song '{query}' from YouTube.")
            return

        self.queue.add_song((url, title))
        await ctx.respond(f"Added {title} to the queue.")

        # Connect if not already connected
        if ctx.voice_client is None:
            await voice_channel.connect()
            # Add a small delay to ensure connection is stable
            await asyncio.sleep(1)

        # Check if we need to start playing
        if not ctx.voice_client.is_playing():
            try:
                current_song = self.get_current_song()
                if current_song:
                    url, title = current_song
                    self.song_start_time = time.time()
                    self.song_duration = 180  # Placeholder duration for streams

                    ctx.voice_client.play(
                        discord.FFmpegPCMAudio(url, **self.FFMPEG_OPTIONS),
                        after=lambda e: self.bot.loop.create_task(
                            self.play_next_song(ctx)
                        ),
                    )
            except Exception as e:
                log.error(f"Error starting playback: {e}")
                if ctx.voice_client:
                    await ctx.voice_client.disconnect()

    @commands.slash_command(
        name="add_to_queue", description="Add a music file to the queue."
    )
    async def add_to_queue(self, ctx: discord.ApplicationContext, query: str):
        await ctx.defer()
        url, title = await self.fetch_youtube_url(query)
        if not url:
            await ctx.respond("Failed to fetch the song from YouTube.")
            return

        self.queue.add_song((url, title))
        await ctx.respond(f"Added {title} to the queue.")

    @commands.slash_command(
        name="play_playlist", description="Play all songs in a YouTube playlist."
    )
    async def play_playlist(self, ctx: discord.ApplicationContext, playlist_url: str):
        await ctx.defer()

        with YoutubeDL({**self.ydl_opts, "extract_flat": True}) as ydl:
            try:
                info = ydl.extract_info(playlist_url, download=False)
                entries = info.get("entries", [])
                for entry in entries:
                    url = entry.get("url")
                    title = entry.get("title", "Unknown Title")
                    self.queue.add_song((url, title))

                await ctx.respond(
                    f"Added {len(entries)} songs from the playlist to the queue."
                )

                if ctx.author.voice and ctx.voice_client is None:
                    vc = await ctx.author.voice.channel.connect()

                if not ctx.voice_client.is_playing():
                    await self.play_next_song(ctx)

            except Exception as e:
                await ctx.respond("Failed to fetch the playlist.")
                log.error(f"Error fetching playlist: {e}")

    @commands.slash_command(name="skip", description="Skip the current song.")
    async def skip(self, ctx: discord.ApplicationContext):
        if ctx.voice_client is None or not ctx.voice_client.is_playing():
            await ctx.respond("No music playing to be skipped.")
            log.warning("Used skip command without music playback.")
            return

        current_song = self.get_current_song()
        ctx.voice_client.stop()

        await ctx.respond(f"Skipped {current_song}")


def setup(bot):
    bot.add_cog(Music(bot))
