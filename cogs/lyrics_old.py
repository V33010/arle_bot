import tomllib

import requests
from bs4 import BeautifulSoup
from discord.ext import commands
from pydantic import ValidationError

from utils.logger import get_context_logger, log
from validators.config import ConfigValidator

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


def search_song_on_genius(song_name):
    log.info(f'Searching genius for {song_name}...')
    base_url = 'https://api.genius.com'
    search_url = f'{base_url}/search'
    params = {'q': song_name}
    headers = {'Authorization': f'Bearer {genius_api_token}'}
    response = requests.get(search_url, params=params, headers=headers)

    if response.status_code == 200:
        log.success('Received response code 200')
        search_results = response.json()
        if search_results['response']['hits']:
            song_info = search_results['response']['hits'][0]['result']
            song_url = song_info['url']
            log.info(f'Song URL: {song_url}')
            return song_url
        else:
            log.warning('Song not found')
            return 'Song not found'
    else:
        log.error(f'Failed to search for song. Status code: {response.status_code}')
        return f'Failed to search for the song. Status code: {response.status_code}'


# def get_lyrics_from_url(url):
#     log.info(f'Fetching lyrics from URL: {url}')
#     response = requests.get(url)
#     if response.status_code == 200:
#         log.success('Received status code 200')
#         soup = BeautifulSoup(response.content, 'html.parser')
#         lyrics_root = soup.find('div', {'id': 'lyrics-root'})
#
#         if lyrics_root:
#             log.debug('lyrics_root exists, finding lyrics containers...')
#             lyrics_containers = lyrics_root.find_all('div', {'data-lyrics-container': 'true'})
#             if lyrics_containers:
#                 log.debug('Lyrics containers found, parsing lyrics...')
#                 formatted_lyrics = []
#                 for container in lyrics_containers:
#                     for br in container.find_all('br'):
#                         br.replace_with('\n')
#
#                     container_text = container.get_text()
#                     lines = [line.strip() for line in container_text.split('\n')]
#                     lines = [line for line in lines if line]
#                     formatted_lyrics.append('\n'.join(lines))
#
#                 log.success('Lyrics parsed successfully!')
#                 return '\n\n'.join(formatted_lyrics)
#             else:
#                 log.error(f'No lyrics containers found on page: {url}')
#                 return 'No lyrics containers found on this page.'
#         else:
#             log.error(f'No lyrics found on page: {url}')
#             return 'Lyrics root not found on this page.'
#     else:
#         log.error(f'Failed to fetch the page: {url}, status code: {response.status_code}')
#         return f'Failed to fetch the page. Status code: {response.status_code}'
#
def get_lyrics_from_url(url):
    log.info(f'Fetching lyrics from URL: {url}')

    # Add a User-Agent header to bypass basic anti-bot protections
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    # Pass the headers into the request
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        log.success('Received status code 200')
        soup = BeautifulSoup(response.content, 'html.parser')
        lyrics_root = soup.find('div', {'id': 'lyrics-root'})

        if lyrics_root:
            log.debug('lyrics_root exists, finding lyrics containers...')
            lyrics_containers = lyrics_root.find_all('div', {'data-lyrics-container': 'true'})
            if lyrics_containers:
                log.debug('Lyrics containers found, parsing lyrics...')
                formatted_lyrics = []
                for container in lyrics_containers:
                    for br in container.find_all('br'):
                        br.replace_with('\n')

                    container_text = container.get_text()
                    lines = [line.strip() for line in container_text.split('\n')]
                    lines = [line for line in lines if line]
                    formatted_lyrics.append('\n'.join(lines))

                log.success('Lyrics parsed successfully!')
                return '\n\n'.join(formatted_lyrics)
            else:
                log.error(f'No lyrics containers found on page: {url}')
                return 'No lyrics containers found on this page.'
        else:
            log.error(f'No lyrics found on page: {url}')
            return 'Lyrics root not found on this page.'
    else:
        log.error(f'Failed to fetch the page: {url}, status code: {response.status_code}')
        return f'Failed to fetch the page. Status code: {response.status_code}'


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
        await ctx.defer()

        ctxlogger.debug("Calling function 'search_song_on_genius'")
        song_url = search_song_on_genius(song_name)
        if song_url != 'Song not found':
            ctxlogger.debug("Calling function 'get_lyrics_from_url'")
            lyrics = get_lyrics_from_url(song_url)

            if lyrics:
                # Split lyrics into chunks to prevent message truncation
                max_length = 2000  # Max length for a single message
                chunks = [lyrics[i : i + max_length] for i in range(0, len(lyrics), max_length)]
                for chunk in chunks:
                    await ctx.followup.send(chunk)
                ctxlogger.success(f'Sent lyrics for song: {song_name}')
            else:
                ctxlogger.error(f'Could not fetch lyrics for song: {song_name}')
                await ctx.followup.send('Could not fetch lyrics.')
        else:
            await ctx.followup.send('Song not found.')


def setup(bot):
    bot.add_cog(LyricsCog(bot))
