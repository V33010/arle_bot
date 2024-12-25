import random

import discord
from discord.ext import commands


class Testing(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(
        name='ping_delay', description="Displays the bot's ping delay in milliseconds."
    )
    async def ping_delay(self, ctx: discord.ApplicationContext):
        delay = round(self.bot.latency * 1000)
        await ctx.respond(f'Ping delay is {delay}ms.')

    @commands.slash_command(
        name='gtn', description='A Slash Command to play a Guess-the-Number game.'
    )
    async def gtn(self, ctx: discord.ApplicationContext):
        number_to_guess = random.randint(1, 10)
        print('Number to guess:', number_to_guess)
        await ctx.respond('Guess a number between 1 and 10.')

        def check(message):
            return message.author == ctx.author and message.channel == ctx.channel

        try:
            guess = await self.bot.wait_for('message', check=check, timeout=30.0)

            if not guess.content.isdigit():
                await ctx.interaction.followup.send('You need to enter a valid number!')
                await ctx.interaction.followup.send(f'You entered: {guess.content}')
                return

            if int(guess.content) == number_to_guess:
                await ctx.interaction.followup.send('You guessed it!')
            else:
                await ctx.interaction.followup.send(
                    f'Nope, the number was {number_to_guess}. Try again.'
                )

        except discord.errors.TimeoutError:
            await ctx.interaction.followup.send('You took too long to respond!')

    @commands.slash_command(
        name='docker_test',
        description='A test command to check if the bot is running in a Docker container.',
    )
    async def docker_test(self, ctx: discord.ApplicationContext):
        await ctx.respond('The bot is running in a Docker container! Code update worked.')


def setup(bot):
    bot.add_cog(Testing(bot))
