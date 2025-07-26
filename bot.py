

# ---- Imports ----
import os
import asyncpg
import discord
import aiohttp
import asyncio
from dotenv import load_dotenv
from discord import app_commands
from datetime import datetime, timedelta, UTC

# ---- Load environment variables ----
load_dotenv("api.env")

# ---- Globals ----
PG_DSN = os.environ.get("PG_DSN")
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")
db_pool = None

# ---- Discord Client ----

# ---- Intents ----
intents = discord.Intents.default()
intents.members = True

class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await init_db()
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
                channel_id BIGINT,
                PRIMARY KEY (guild_id, user_id)
            )
        ''')

client = MyClient()

# ---- Slash Commands ----
@client.tree.command(name="unsubscribe", description="Unsubscribe from job updates and remove your settings")
async def unsubscribe(interaction: discord.Interaction):
    gid = interaction.guild.id
    uid = interaction.user.id
    async with db_pool.acquire() as conn:
        await conn.execute('DELETE FROM user_settings WHERE guild_id=$1 AND user_id=$2', gid, uid)
    await interaction.response.send_message("You have been unsubscribed from job updates.", ephemeral=True)

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
    # Only take the first argument (before any comma or space)
    loc = location.split(",")[0].split()[0].strip()
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO user_settings (guild_id, user_id, location)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, user_id) DO UPDATE SET location = $3
        ''', gid, uid, loc)
    await interaction.response.send_message(f"📍 Location saved: **{loc}**", ephemeral=True)

@client.tree.command(name="clearlocation", description="Clear your saved location")
async def clearlocation(interaction: discord.Interaction):
    gid = interaction.guild.id
    uid = interaction.user.id
    async with db_pool.acquire() as conn:
        await conn.execute('UPDATE user_settings SET location=NULL WHERE guild_id=$1 AND user_id=$2', gid, uid)
    await interaction.response.send_message("Your location has been cleared.", ephemeral=True)

@client.tree.command(name="showlocation", description="Show your currently saved location")
async def showlocation(interaction: discord.Interaction):
    gid = interaction.guild.id
    uid = interaction.user.id
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow('SELECT location FROM user_settings WHERE guild_id=$1 AND user_id=$2', gid, uid)
    if not row or not row["location"]:
        await interaction.response.send_message("� You haven't set a location yet.", ephemeral=True)
        return
    location = row["location"]
    await interaction.response.send_message(f"Your saved location: **{location}**", ephemeral=True)
@client.tree.command(name="setdays", description="Set how many recent days of job postings to search")
@app_commands.describe(days="Number of recent days (e.g. 7 for past week)")
async def setdays(interaction: discord.Interaction, days: int):
    # Ensure days is always an integer
    try:
        days_int = int(days)
    except Exception:
        await interaction.response.send_message("❌ Please enter a valid integer for days.", ephemeral=True)
        return
    if days_int < 4:
        await interaction.response.send_message("❌ Days must be at least 4.", ephemeral=True)
        return
    gid = interaction.guild.id
    uid = interaction.user.id
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO user_settings (guild_id, user_id, days)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, user_id) DO UPDATE SET days = $3
        ''', gid, uid, days_int)
    await interaction.response.send_message(f"✅ Job posting age filter set to the past {days_int} day(s).", ephemeral=True)


# ---- Background Job Task ----
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
                await send_job_results(guild, row["user_id"], row["keywords"], row["location"], row["days"])
        await asyncio.sleep(4 * 24 * 60 * 60)

# ---- Helper: Send Job Results ----
async def send_job_results(guild, user_id, keywords, location, days_limit):
    try:
        # Fetch channel_id from DB
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow('SELECT channel_id FROM user_settings WHERE guild_id=$1 AND user_id=$2', guild.id, user_id)
        channel_id = row["channel_id"] if row else None
        channel = None
        if channel_id:
            channel = guild.get_channel(channel_id)
        if not channel or not channel.permissions_for(guild.me).send_messages:
            print(f"[ERROR] No valid channel set for user {user_id} in guild {guild.id}")
            return False
        keywords = keywords or []
        location = location or ""
        days_limit = days_limit or 7
        query_parts = keywords + ([location] if location else [])
        query = "+".join(query_parts)
        url = f"https://jsearch.p.rapidapi.com/search?query={query}&page=1&num_pages=1&country=us"
        headers = {
            "X-RapidAPI-Key": RAPIDAPI_KEY,
            "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    print(f"[ERROR] API returned status {response.status} for user {user_id}")
                    try:
                        text = await response.text()
                        print(f"[ERROR] API response: {text[:500]}")
                    except Exception:
                        pass
                    return False
                try:
                    data = await response.json()
                except Exception as e:
                    print(f"[ERROR] Failed to parse JSON for user {user_id}: {e}")
                    text = await response.text()
                    print(f"[ERROR] API response (non-JSON): {text[:500]}")
                    return False
                jobs = data.get("data", [])
                cutoff = datetime.now(UTC) - timedelta(days=days_limit)
                recent_jobs = []
                for job in jobs:
                    posted_at = job.get("job_posted_at_datetime_utc")
                    if not posted_at:
                        continue
                    try:
                        posted_dt = datetime.strptime(posted_at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
                    except Exception as e:
                        print(f"[ERROR] Invalid date format for job: {posted_at} ({e})")
                        continue
                    if posted_dt > cutoff:
                        recent_jobs.append(job)
                    if len(recent_jobs) >= 5:
                        break
                if not recent_jobs:
                    print(f"[INFO] No recent jobs found for user {user_id}")
                    return True
                msg = "Top Recent Job Results:\n"
                for job in recent_jobs:
                    msg += f"• [{job['job_title']}]({job['job_apply_link']}) at **{job['employer_name']}**\n"
                try:
                    await channel.send(f"<@{user_id}> {msg}")
                except discord.Forbidden:
                    print(f"[ERROR] Cannot send message in channel {channel.id} for user {user_id} (forbidden)")
                    return False
                except Exception as e:
                    print(f"[ERROR] Failed to send message in channel {channel.id} for user {user_id}: {e}")
                    return False
        return True
    except Exception as e:
        print(f"[ERROR] Unexpected error in send_job_results for user {user_id}: {e}")
        return False

# ---- Slash Command: searchnow ----
@client.tree.command(name="searchnow", description="Get your latest job results now!")
async def searchnow(interaction: discord.Interaction):
    gid = interaction.guild.id
    uid = interaction.user.id
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow('SELECT keywords, location, days, channel_id FROM user_settings WHERE guild_id=$1 AND user_id=$2', gid, uid)
    if not row or not row["keywords"]:
        await interaction.response.send_message("You haven't set any keywords yet. Use /setkeywords first.", ephemeral=True)
        return
    if not row["channel_id"]:
        await interaction.response.send_message("You haven't set a channel to receive job results. Use /setchannel first.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    success = await send_job_results(interaction.guild, uid, row["keywords"], row["location"], row["days"])
    if success:
        await interaction.followup.send("Done! Your job results have been posted in your selected channel.", ephemeral=True)
    else:
        await interaction.followup.send("Sorry, I couldn't send your job results in the selected channel. Please check my permissions or try again later.", ephemeral=True)
# ---- Slash Command: setchannel ----
@client.tree.command(name="setchannel", description="Set the channel where you want to receive job results")
@discord.app_commands.describe(channel="Select a text channel")
async def setchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    gid = interaction.guild.id
    uid = interaction.user.id
    # Check bot permissions
    if not channel.permissions_for(interaction.guild.me).send_messages:
        await interaction.response.send_message("❌ I don't have permission to send messages in that channel.", ephemeral=True)
        return
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO user_settings (guild_id, user_id, channel_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, user_id) DO UPDATE SET channel_id = $3
        ''', gid, uid, channel.id)
    await interaction.response.send_message(f"✅ Channel set! You'll receive job results in {channel.mention}.", ephemeral=True)

# ---- Slash Command: clearchannel ----
@client.tree.command(name="clearchannel", description="Clear your selected job results channel")
async def clearchannel(interaction: discord.Interaction):
    gid = interaction.guild.id
    uid = interaction.user.id
    async with db_pool.acquire() as conn:
        await conn.execute('UPDATE user_settings SET channel_id=NULL WHERE guild_id=$1 AND user_id=$2', gid, uid)
    await interaction.response.send_message("Your job results channel has been cleared.", ephemeral=True)

# ---- Slash Command: showchannel ----
@client.tree.command(name="showchannel", description="Show your currently selected job results channel")
async def showchannel(interaction: discord.Interaction):
    gid = interaction.guild.id
    uid = interaction.user.id
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow('SELECT channel_id FROM user_settings WHERE guild_id=$1 AND user_id=$2', gid, uid)
    if not row or not row["channel_id"]:
        await interaction.response.send_message("You haven't set a channel yet. Use /setchannel to pick one.", ephemeral=True)
        return
    channel = interaction.guild.get_channel(row["channel_id"])
    if not channel:
        await interaction.response.send_message("The previously set channel no longer exists. Please set a new one with /setchannel.", ephemeral=True)
        return
    await interaction.response.send_message(f"Your job results will be sent to: {channel.mention}", ephemeral=True)

# ---- on_ready Event ----
@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user} (ID: {client.user.id})")
    client.loop.create_task(job_update_task())

# ---- Run Bot ----
client.run(os.environ.get("DISCORD_TOKEN"))
