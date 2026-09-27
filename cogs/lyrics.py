import asyncio
import tomllib

import lyricsgenius
from discord.ext import commands
from pydantic import ValidationError

from utils.logger import get_context_logger, log
from validators.config import ConfigValidator

# Load Configuration
with open('config.toml', 'rb') as f:
    data = tomllib.load(f)

try:
    arle_config: ConfigValidator = ConfigValidator.model_validate(data)
except ValidationError as v:
    log.error('Encountered error in lyrics.py')
    log.error(v)
    log.warning('shutting down . . .')
    log.debug('Goodbye :(')
    exit(1)

genius_api_token = arle_config.secrets.genius_token

# Initialize the lyricsgenius client
genius = lyricsgenius.Genius(genius_api_token)
genius.verbose = (
    False  # Turns off the library's internal print statements to keep your console clean
)
genius.remove_section_headers = False
genius.skip_non_songs = True


class LyricsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(name='lyrics_from_genius')
    async def lyrics_from_genius(self, ctx, song_name: str):
        """Fetches lyrics from Genius and sends them to the Discord channel."""
        ctxlogger = get_context_logger(ctx)
        ctxlogger.info(
            f"{ctx.author.name} used command 'lyrics_from_genius' with song name: {song_name}"
        )

        # Defer response so the interaction doesn't time out while searching
        await ctx.defer()

        try:
            ctxlogger.debug(f"Searching for '{song_name}' using lyricsgenius...")

            # Use asyncio.to_thread so the synchronous library doesn't block the bot's event loop
            song = await asyncio.to_thread(genius.search_song, song_name)

            if song and song.lyrics:
                ctxlogger.success(f'Found lyrics for song: {song.title} by {song.artist}')
                lyrics = song.lyrics

                # Split lyrics into chunks to prevent hitting Discord's 2000 character message limit
                max_length = 2000
                chunks = [lyrics[i : i + max_length] for i in range(0, len(lyrics), max_length)]

                for chunk in chunks:
                    await ctx.followup.send(chunk)

                ctxlogger.success(f'Sent lyrics for song: {song_name}')
            else:
                ctxlogger.warning(f'Song not found or lyrics unavailable for: {song_name}')
                await ctx.followup.send(f'Sorry, I could not find the lyrics for "{song_name}".')

        except Exception as e:
            ctxlogger.error(f'Error fetching lyrics for {song_name}: {e}')
            await ctx.followup.send(
                'An error occurred while fetching the lyrics. Please try again later.'
            )


def setup(bot):
    bot.add_cog(LyricsCog(bot))
