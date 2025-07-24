
import asyncpg

PG_DSN = os.environ.get("PG_DSN")
db_pool = None


@client.tree.command(name="unsubscribe", description="Unsubscribe from job updates and remove your settings")
async def unsubscribe(interaction: discord.Interaction):
    gid = interaction.guild.id
    uid = interaction.user.id
    async with db_pool.acquire() as conn:
        await conn.execute('DELETE FROM user_settings WHERE guild_id=$1 AND user_id=$2', gid, uid)
    await interaction.response.send_message("You have been unsubscribed from job updates.", ephemeral=True)
        
import os
from dotenv import load_dotenv
load_dotenv("api.env")
import discord
from discord import app_commands



class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

    async def on_ready(self):
        print(f"✅ Logged in as {self.user} (ID: {self.user.id})")

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(PG_DSN)
    async with db_pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS user_settings (
                guild_id BIGINT,
                user_id BIGINT,
                keywords TEXT[],
                location TEXT,
                days INT,
                PRIMARY KEY (guild_id, user_id)
            )
        ''')

client = MyClient()

@client.tree.command(name="ping", description="Check if the bot is alive")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!", ephemeral=True)

@client.tree.command(name="setkeywords", description="Set keywords to track (comma-separated)")
@discord.app_commands.describe(keywords="e.g. internship, remote, summer 2025")
async def setkeywords(interaction: discord.Interaction, keywords: str):
    gid = interaction.guild.id
    uid = interaction.user.id
    keyword_list = [k.strip() for k in keywords.split(",")]
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO user_settings (guild_id, user_id, keywords)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, user_id) DO UPDATE SET keywords = $3
        ''', gid, uid, keyword_list)
    msg = "✅ Keywords saved:\n" + "\n".join(f"• {k}" for k in keyword_list)
    await interaction.response.send_message(msg, ephemeral=True)

@client.tree.command(name="showkeywords", description="Show your currently saved keywords")
async def showkeywords(interaction: discord.Interaction):
    gid = interaction.guild.id
    uid = interaction.user.id
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow('SELECT keywords FROM user_settings WHERE guild_id=$1 AND user_id=$2', gid, uid)
    if not row or not row["keywords"]:
        await interaction.response.send_message("📭 You haven't set any keywords yet.", ephemeral=True)
        return
    keywords = row["keywords"]
    await interaction.response.send_message("Your saved keywords:\n• " + "\n• ".join(keywords), ephemeral=True)

@client.tree.command(name="clearkeywords", description="Clear your saved keywords")
async def clearkeywords(interaction: discord.Interaction):
    gid = interaction.guild.id
    uid = interaction.user.id
    async with db_pool.acquire() as conn:
        await conn.execute('UPDATE user_settings SET keywords=NULL WHERE guild_id=$1 AND user_id=$2', gid, uid)
    await interaction.response.send_message("Your keywords have been cleared.", ephemeral=True)


@client.tree.command(name="setlocation", description="Set your preferred job location")
@discord.app_commands.describe(location="City, State or 'Remote'")
async def setlocation(interaction: discord.Interaction, location: str):
    gid = interaction.guild.id
    uid = interaction.user.id
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO user_settings (guild_id, user_id, location)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, user_id) DO UPDATE SET location = $3
        ''', gid, uid, location.strip())
    await interaction.response.send_message(f"📍 Location saved: **{location}**", ephemeral=True)

@client.tree.command(name="setdays", description="Set how many recent days of job postings to search")
@app_commands.describe(days="Number of recent days (e.g. 7 for past week)")
async def setdays(interaction: discord.Interaction, days: int):
    if days < 1:
        await interaction.response.send_message("❌ Days must be at least 1.", ephemeral=True)
        return
    gid = interaction.guild.id
    uid = interaction.user.id
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO user_settings (guild_id, user_id, days)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, user_id) DO UPDATE SET days = $3
        ''', gid, uid, days)
    await interaction.response.send_message(f"✅ Job posting age filter set to the past {days} day(s).", ephemeral=True)


import aiohttp


# Load API key from environment variable
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")


from datetime import datetime, timedelta, UTC
import asyncio


async def job_update_task():
    await client.wait_until_ready()
    while not client.is_closed():
        for guild in client.guilds:
            channel = next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
            if not channel:
                continue
            gid = guild.id
            async with db_pool.acquire() as conn:
                rows = await conn.fetch('SELECT user_id, keywords, location, days FROM user_settings WHERE guild_id=$1 AND keywords IS NOT NULL', gid)
            for row in rows:
                uid = row["user_id"]
                keywords = row["keywords"] or []
                location = row["location"] or ""
                days_limit = row["days"] or 7
                query_parts = keywords + ([location] if location else [])
                query = "+".join(query_parts)
                url = f"https://jsearch.p.rapidapi.com/search?query={query}&page=1&num_pages=1&country=us"
                headers = {
                    "X-RapidAPI-Key": RAPIDAPI_KEY,
                    "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
                }
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url, headers=headers) as response:
                            if response.status != 200:
                                continue
                            data = await response.json()
                            jobs = data.get("data", [])
                            cutoff = datetime.now(UTC) - timedelta(days=days_limit)
                            recent_jobs = [
                                job for job in jobs
                                if datetime.strptime(job["job_posted_at_datetime_utc"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC) > cutoff
                            ][:5]
                            if not recent_jobs:
                                continue
                            msg = f"<@{uid}>\nTop Recent Job Results:\n"
                            for job in recent_jobs:
                                msg += f"• [{job['job_title']}]({job['job_apply_link']}) at **{job['employer_name']}**\n"
                            await channel.send(msg)
                except Exception:
                    continue
        await asyncio.sleep(4 * 24 * 60 * 60)


@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user} (ID: {client.user.id})")
    if db_pool is None:
        await init_db()
    client.loop.create_task(job_update_task())


# Run your bot using the token from environment variable
client.run(os.environ.get("DISCORD_TOKEN"))
