import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
from discord import app_commands
from playwright.async_api import async_playwright
import asyncio
import logging
import time

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='/', intents=intents)

# Global variables
current_room = None
last_generated_link = None
user_cooldowns = {}

@bot.event
async def on_ready():
    logger.info(f'{bot.user} has connected to Discord!')
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} command(s)")
    except Exception as e:
        logger.exception(f"Error syncing commands: {e}")

@bot.tree.command(name="generate", description="Generate a Skribbl.io room link")
async def generate(interaction: discord.Interaction):
    global current_room, last_generated_link
    logger.info(f"Generate command invoked by {interaction.user}")
    await interaction.response.defer(thinking=True)
    
    if current_room:
        await interaction.followup.send("A room is already active. Please wait for it to close automatically.")
        return
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(permissions=['clipboard-read', 'clipboard-write'])
        page = await context.new_page()
        
        try:
            logger.info("Navigating to Skribbl.io")
            await page.goto("https://skribbl.io/")
            await asyncio.sleep(1)

            logger.info("Zooming out the page to 50%")
            await page.evaluate("document.body.style.zoom = '50%'")
            await asyncio.sleep(1)

            logger.info("Looking for 'Create Private Room' button")
            create_button = page.locator("button:has-text('Create Private Room')")
            if await create_button.is_visible():
                logger.info("Clicking 'Create Private Room' button")
                await create_button.click()
                await asyncio.sleep(3)

                logger.info("Looking for 'Copy' button")
                copy_button = page.locator("#copy-invite")
                if await copy_button.is_visible():
                    logger.info("Clicking 'Copy' button")
                    await copy_button.click()
                    await asyncio.sleep(1)

                    logger.info("Reading room link from clipboard")
                    room_link = await page.evaluate("navigator.clipboard.readText()")

                    if "skribbl.io/?" in room_link:
                        logger.info(f"Room link obtained: {room_link}")
                        current_room = {'link': room_link, 'page': page, 'browser': browser}
                        last_generated_link = room_link
                        
                        await interaction.followup.send(f"Here's your Skribbl.io room link: {room_link}\nThis room will remain active for 90 seconds or until someone joins.")
                        
                        start_time = asyncio.get_event_loop().time()
                        while asyncio.get_event_loop().time() - start_time < 90:
                            try:
                                join_text = page.locator("text=joined the room")
                                if await join_text.count() > 0:
                                    logger.info("Player joined the room. Closing after 1 second.")
                                    await asyncio.sleep(1)
                                    break
                                await asyncio.sleep(1)
                            except Exception as e:
                                logger.exception(f"Error while checking for players: {e}")
                                break
                        
                        logger.info("Closing the room")
                        await browser.close()
                        current_room = None
                        return
                    else:
                        logger.error("Failed to get valid room link from clipboard")
                else:
                    logger.error("'Copy' button not found")
            else:
                logger.error("'Create Private Room' button not found")

        except Exception as e:
            logger.exception(f"An error occurred: {e}")
        
        logger.error("Failed to create Skribbl.io room")
        await interaction.followup.send("Failed to create a Skribbl.io room. Please try again.")
        if browser:
            await browser.close()
        current_room = None

@bot.tree.command(name="spam", description="Spam the previously generated Skribbl.io room link")
@app_commands.describe(
    interval="Time interval between messages (1-10 seconds, default 2)",
    count="Number of times to spam the link (1-20 times, default 7)"
)
async def spam(interaction: discord.Interaction, interval: int = 2, count: int = 7):
    global last_generated_link
    logger.info(f"Spam command invoked by {interaction.user}")
    
    is_admin = interaction.user.guild_permissions.administrator
    user_id = interaction.user.id
    current_time = time.time()
    
    if not is_admin:
        if user_id in user_cooldowns:
            remaining = user_cooldowns[user_id] - current_time
            if remaining > 0:
                await interaction.response.send_message(f"You can only use this command once per minute. Try again in {remaining:.2f} seconds.", ephemeral=True)
                return
        
    if not last_generated_link:
        await interaction.response.send_message("No room link has been generated yet. Use /generate first.")
        return
    
    # Clamp the parameters
    interval = max(1, min(interval, 10))
    count = max(1, min(count, 20))
    
    await interaction.response.send_message(f"Spamming the last generated link {count} times with {interval} second intervals...")
    
    for i in range(count):
        await interaction.channel.send(f"Skribbl.io room link (spam {i+1}/{count}): {last_generated_link}")
        await asyncio.sleep(interval)
    
    await interaction.channel.send("Spam completed.")

    # Set cooldown for non-admin users
    if not is_admin:
        user_cooldowns[user_id] = current_time + 60  # Set cooldown to 1 minute from now

@spam.error
async def spam_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(f"This command is on cooldown. Try again in {error.retry_after:.2f} seconds.", ephemeral=True)

bot.run(TOKEN)    