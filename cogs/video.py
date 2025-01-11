import logging
import mimetypes
import os
from logging.handlers import RotatingFileHandler

import aiofiles
import discord
from aiohttp import web
from discord import ApplicationContext, Option
from discord.ext import commands
from pyngrok import ngrok

# Set up basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VideoPlayerCog(commands.Cog):
    """A cog that handles video playback through a web interface"""

    def __init__(self, bot):
        self.bot = bot
        self.video_dir = 'videos'
        self.web_app = web.Application()
        self.setup_routes()
        self.server = None
        self.port = 8080
        self.ngrok_tunnel = None

        # Setup logging
        self.logger = logging.getLogger('VideoPlayerCog')
        self.logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(
            'video_player.log',
            maxBytes=1024 * 1024,
            backupCount=5,  # 1MB
        )
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

        # Create videos directory
        os.makedirs(self.video_dir, exist_ok=True)

        # Start web server
        self.bot.loop.create_task(self.start_server())

    def setup_routes(self):
        """Setup web server routes"""
        self.web_app.router.add_get('/', self.handle_home)
        self.web_app.router.add_get('/play/{filename}', self.handle_player)
        self.web_app.router.add_get('/video/{filename}', self.handle_video)

    async def start_server(self):
        """Start the web server and ngrok tunnel"""
        try:
            # Start web server
            runner = web.AppRunner(self.web_app)
            await runner.setup()
            self.server = web.TCPSite(runner, 'localhost', self.port)
            await self.server.start()

            # Configure and start ngrok
            # If you have an authtoken, uncomment and add it here:
            # ngrok.set_auth_token('your_ngrok_auth_token')

            # Create ngrok tunnel
            self.ngrok_tunnel = ngrok.connect(self.port)
            public_url = self.ngrok_tunnel.public_url

            self.logger.info(f'Video server started locally at http://localhost:{self.port}')
            self.logger.info(f'Ngrok tunnel created at {public_url}')
            logger.info(f'Video server accessible at {public_url}')

        except Exception as e:
            self.logger.error(f'Failed to start video server: {e}')
            raise

    async def cleanup(self):
        """Cleanup resources when cog is unloaded"""
        if self.ngrok_tunnel:
            ngrok.disconnect(self.ngrok_tunnel.public_url)
            self.logger.info('Ngrok tunnel closed')

    def cog_unload(self):
        """Handle cog unload"""
        if self.server:
            self.bot.loop.create_task(self.cleanup())

    async def handle_home(self, request: web.Request):
        """Handle home page request"""
        return web.Response(text='Video Player Server Running', content_type='text/plain')

    async def handle_player(self, request: web.Request):
        """Handle video player page request"""
        filename = request.match_info['filename']

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Video Player - {filename}</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    margin: 0;
                    padding: 20px;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    min-height: 100vh;
                    background: #1a1a1a;
                    font-family: Arial, sans-serif;
                }}
                .video-container {{
                    max-width: 1000px;
                    width: 100%;
                    padding: 20px;
                }}
                video {{
                    width: 100%;
                    height: auto;
                    box-shadow: 0 0 20px rgba(0,0,0,0.5);
                    border-radius: 8px;
                }}
                h1 {{
                    color: white;
                    text-align: center;
                    margin-bottom: 20px;
                    word-break: break-word;
                }}
            </style>
        </head>
        <body>
            <div class="video-container">
                <h1>{filename}</h1>
                <video controls autoplay>
                    <source src="/video/{filename}" type="video/mp4">
                    Your browser does not support the video tag.
                </video>
            </div>
        </body>
        </html>
        """
        return web.Response(text=html, content_type='text/html')

    async def handle_video(self, request: web.Request):
        """Handle video file streaming"""
        try:
            filename = request.match_info['filename']
            filepath = os.path.join(self.video_dir, filename)

            if not os.path.exists(filepath):
                return web.Response(status=404, text='Video not found')

            file_size = os.path.getsize(filepath)

            headers = {
                'Accept-Ranges': 'bytes',
                'Content-Type': mimetypes.guess_type(filepath)[0] or 'application/octet-stream',
            }

            range_header = request.headers.get('Range')

            if range_header is not None:
                try:
                    range_match = range_header.replace('bytes=', '').split('-')
                    start = int(range_match[0]) if range_match[0] else 0
                    end = int(range_match[1]) if range_match[1] else file_size - 1

                    if start >= file_size:
                        return web.Response(status=416)

                    chunk_size = end - start + 1

                    headers['Content-Range'] = f'bytes {start}-{end}/{file_size}'
                    headers['Content-Length'] = str(chunk_size)

                    async with aiofiles.open(filepath, 'rb') as f:
                        await f.seek(start)
                        chunk = await f.read(chunk_size)

                    return web.Response(body=chunk, status=206, headers=headers)

                except (ValueError, IndexError):
                    pass

            return web.FileResponse(filepath, headers=headers)

        except Exception as e:
            self.logger.error(f'Error handling video request: {e}')
            return web.Response(status=500, text='Internal server error')

    @commands.slash_command(
        name='playvideo', description='Play a video file from the videos directory'
    )
    async def playvideo(
        self,
        ctx: ApplicationContext,
        filename: Option(str, 'Name of the video file to play', required=True),
    ):
        """Play a video file from the videos directory"""
        await ctx.defer()

        try:
            filepath = os.path.join(self.video_dir, filename)
            if not os.path.exists(filepath):
                await ctx.respond(
                    embed=discord.Embed(
                        title='❌ Error',
                        description=f"File '{filename}' not found in videos directory.",
                        color=discord.Color.red(),
                    )
                )
                return

            if not self.ngrok_tunnel:
                await ctx.respond(
                    embed=discord.Embed(
                        title='❌ Error',
                        description='Video server is not ready. Please try again later.',
                        color=discord.Color.red(),
                    )
                )
                return

            player_url = f'{self.ngrok_tunnel.public_url}/play/{filename}'

            embed = discord.Embed(
                title='🎥 Video Player Ready',
                description=f'Click [here]({player_url}) to watch the video!',
                color=discord.Color.blue(),
            )
            embed.add_field(name='File', value=filename, inline=False)

            await ctx.respond(embed=embed)
            self.logger.info(f'Started playing video: {filename}')

        except Exception as e:
            self.logger.error(f'Error in playvideo command: {e}')
            await ctx.respond(
                embed=discord.Embed(
                    title='❌ Error',
                    description='An error occurred while processing your request.',
                    color=discord.Color.red(),
                )
            )

    @commands.slash_command(name='available_videos', description='List all available videos')
    async def available_videos(self, ctx: ApplicationContext):
        """List all videos in the videos directory"""
        await ctx.defer()

        try:
            videos = [
                f
                for f in os.listdir(self.video_dir)
                if os.path.isfile(os.path.join(self.video_dir, f))
            ]

            if not videos:
                await ctx.respond(
                    embed=discord.Embed(
                        title='📋 Video List',
                        description='No videos available.',
                        color=discord.Color.blue(),
                    )
                )
                return

            embed = discord.Embed(title='📋 Available Videos', color=discord.Color.blue())

            # Split videos into chunks of 10 for fields
            for i in range(0, len(videos), 10):
                chunk = videos[i : i + 10]
                embed.add_field(
                    name=f'Videos {i+1}-{i+len(chunk)}',
                    value='\n'.join(f'{v}' for v in chunk),
                    inline=False,
                )

            await ctx.respond(embed=embed)

        except Exception as e:
            self.logger.error(f'Error in listvideo command: {e}')
            await ctx.respond(
                embed=discord.Embed(
                    title='❌ Error',
                    description='An error occurred while listing videos.',
                    color=discord.Color.red(),
                )
            )


def setup(bot):
    bot.add_cog(VideoPlayerCog(bot))
