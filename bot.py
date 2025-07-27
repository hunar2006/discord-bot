# ---- User Limit Decorator ----
def user_limit_check(func):
    async def wrapper(interaction, *args, **kwargs):
        uid = interaction.user.id
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow('SELECT subscribed FROM user_settings WHERE user_id=$1', uid)
            user_count = await conn.fetchval('SELECT COUNT(*) FROM user_settings WHERE subscribed=TRUE')
        if (not row or not row["subscribed"]) and user_count >= 18:
            await interaction.response.send_message("❌ No more than 18 users can be subscribed at a time.", ephemeral=True)
            return
        return await func(interaction, *args, **kwargs)
    return wrapper


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


# ---- User Limit Decorator ----

# (Moved outside class definition for correct indentation)

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
                user_id BIGINT PRIMARY KEY,
                keywords TEXT[],
                location TEXT,
                country TEXT,
                days INT,
                s_id BIGINT,
                updates_enabled BOOLEAN DEFAULT FALSE,
                last_sent TEXT,
                channel_id BIGINT,
                subscribed BOOLEAN DEFAULT TRUE
            )
        ''')
client = MyClient()
# ---- Supported Countries ----
COUNTRY_CHOICES = {
    'us': 'United States',
    'in': 'India',
    'ca': 'Canada',
    'gb': 'United Kingdom',
    'au': 'Australia',
    'de': 'Germany',
    'fr': 'France',
    'sg': 'Singapore',
    'jp': 'Japan',
    'za': 'South Africa',
    'br': 'Brazil',
    'ae': 'United Arab Emirates',
    'it': 'Italy',
    'es': 'Spain',
    'nl': 'Netherlands',
    'se': 'Sweden',
    'ch': 'Switzerland',
    'mx': 'Mexico',
    'ie': 'Ireland',
    'ru': 'Russia',
    'cn': 'China',
    'kr': 'South Korea',
    'hk': 'Hong Kong',
    'fi': 'Finland',
    'be': 'Belgium',
    'pl': 'Poland',
    'tr': 'Turkey',
    'ar': 'Argentina',
    'dk': 'Denmark',
    'no': 'Norway',
    'nz': 'New Zealand',
    'pt': 'Portugal',
    'cz': 'Czech Republic',
    'il': 'Israel',
    'my': 'Malaysia',
    'th': 'Thailand',
    'ph': 'Philippines',
    'id': 'Indonesia',
    'sa': 'Saudi Arabia',
    'cl': 'Chile',
    'co': 'Colombia',
    'at': 'Austria',
    'hu': 'Hungary',
    'gr': 'Greece',
    'ro': 'Romania',
    'ua': 'Ukraine',
    'sk': 'Slovakia',
    'bg': 'Bulgaria',
    'hr': 'Croatia',
    'si': 'Slovenia',
    'lt': 'Lithuania',
    'lv': 'Latvia',
    'ee': 'Estonia',
}
# ---- Slash Command: setcountry ----
@client.tree.command(name="setcountry", description="Set your preferred country for job search")
@discord.app_commands.describe(country="Choose a country code (e.g. us, in, ca)")
@user_limit_check
async def setcountry(interaction: discord.Interaction, country: str):
    country = country.lower()
    if country not in COUNTRY_CHOICES:
        country_list = ", ".join(f"{k} ({v})" for k, v in COUNTRY_CHOICES.items())
        await interaction.response.send_message(
            f"❌ Invalid country code. Please choose from the following:\n{country_list}", ephemeral=True)
        return
    uid = interaction.user.id
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO user_settings (user_id, country)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET country = $2
        ''', uid, country)
    await interaction.response.send_message(f"🌍 Country set to: **{COUNTRY_CHOICES[country]}** ({country})", ephemeral=True)

# ---- Slash Command: showcountry ----
@client.tree.command(name="showcountry", description="Show your currently selected country for job search")
@user_limit_check
async def showcountry(interaction: discord.Interaction):
    uid = interaction.user.id
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow('SELECT country FROM user_settings WHERE user_id=$1', uid)
    if not row or not row["country"]:
        await interaction.response.send_message("You haven't set a country yet. Use /setcountry to pick one.", ephemeral=True)
        return
    code = row["country"]
    name = COUNTRY_CHOICES.get(code, code)
    await interaction.response.send_message(f"Your job search country: **{name}** ({code})", ephemeral=True)


# ---- Slash Commands ----
@client.tree.command(name="unsubscribe", description="Unsubscribe from job updates and remove your settings")
@user_limit_check
async def unsubscribe(interaction: discord.Interaction):
    uid = interaction.user.id
    async with db_pool.acquire() as conn:
        await conn.execute('UPDATE user_settings SET subscribed=FALSE, updates_enabled=FALSE WHERE user_id=$1', uid)
    await interaction.response.send_message("You have been unsubscribed from job updates.", ephemeral=True)

@client.tree.command(name="ping", description="Check if the bot is alive")
@user_limit_check
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!", ephemeral=True)

@client.tree.command(name="setkeywords", description="Set keywords to track (comma-separated)")
@discord.app_commands.describe(keywords="Enter keywords separated by commas, e.g. ai, ml, internship")
@user_limit_check
async def setkeywords(interaction: discord.Interaction, keywords: str):
    uid = interaction.user.id
    keyword_list = [k.strip() for k in keywords.split(",")]
    async with db_pool.acquire() as conn:
        # Check if user is already registered and if they are currently subscribed
        row = await conn.fetchrow('SELECT subscribed FROM user_settings WHERE user_id=$1', uid)
        user_count = await conn.fetchval('SELECT COUNT(*) FROM user_settings WHERE subscribed=TRUE')
        # If user is not currently subscribed and limit is reached, block resubscription
        if (not row or not row["subscribed"]) and user_count >= 18:
            await interaction.response.send_message("❌ Sorry, the bot has reached the maximum number of users (18). Please try again later or ask someone to unsubscribe.", ephemeral=True)
            return
        await conn.execute('''
            INSERT INTO user_settings (user_id, keywords, subscribed)
            VALUES ($1, $2, TRUE)
            ON CONFLICT (user_id) DO UPDATE SET keywords = $2, subscribed = TRUE
        ''', uid, keyword_list)
    msg = ("✅ Keywords saved (comma-separated, e.g. ai, ml, internship):\n" +
           "\n".join(f"• {k}" for k in keyword_list))
    await interaction.response.send_message(msg, ephemeral=True)

@client.tree.command(name="showkeywords", description="Show your currently saved keywords")
@user_limit_check
async def showkeywords(interaction: discord.Interaction):
    uid = interaction.user.id
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow('SELECT keywords FROM user_settings WHERE user_id=$1', uid)
    if not row or not row["keywords"]:
        await interaction.response.send_message("📭 You haven't set any keywords yet.", ephemeral=True)
        return
    keywords = row["keywords"]
    await interaction.response.send_message("Your saved keywords:\n• " + "\n• ".join(keywords), ephemeral=True)

@client.tree.command(name="clearkeywords", description="Clear your saved keywords")
@user_limit_check
async def clearkeywords(interaction: discord.Interaction):
    uid = interaction.user.id
    async with db_pool.acquire() as conn:
        await conn.execute('UPDATE user_settings SET keywords=NULL WHERE user_id=$1', uid)
    await interaction.response.send_message("Your keywords have been cleared.", ephemeral=True)

@client.tree.command(name="setlocation", description="Set your preferred job location")
@discord.app_commands.describe(location="City, State or 'Remote'")
@user_limit_check
async def setlocation(interaction: discord.Interaction, location: str):
    uid = interaction.user.id
    # Only take the first argument (before any comma or space)
    loc = location.split(",")[0].split()[0].strip()
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO user_settings (user_id, location)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET location = $2
        ''', uid, loc)
    await interaction.response.send_message(f"📍 Location saved: **{loc}**", ephemeral=True)

@client.tree.command(name="clearlocation", description="Clear your saved location")
@user_limit_check
async def clearlocation(interaction: discord.Interaction):
    uid = interaction.user.id
    async with db_pool.acquire() as conn:
        await conn.execute('UPDATE user_settings SET location=NULL WHERE user_id=$1', uid)
    await interaction.response.send_message("Your location has been cleared.", ephemeral=True)

@client.tree.command(name="showlocation", description="Show your currently saved location")
@user_limit_check
async def showlocation(interaction: discord.Interaction):
    uid = interaction.user.id
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow('SELECT location FROM user_settings WHERE user_id=$1', uid)
    if not row or not row["location"]:
        await interaction.response.send_message("� You haven't set a location yet.", ephemeral=True)
        return
    location = row["location"]
    await interaction.response.send_message(f"Your saved location: **{location}**", ephemeral=True)


# ---- Background Job Task ----
async def job_update_task():
    await client.wait_until_ready()
    while not client.is_closed():
        now = datetime.now(UTC)
        for guild in client.guilds:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch('SELECT user_id, keywords, location, last_sent FROM user_settings WHERE keywords IS NOT NULL AND updates_enabled=TRUE AND subscribed=TRUE')
            for row in rows:
                last_sent_str = row["last_sent"]
                last_sent = None
                if last_sent_str:
                    try:
                        last_sent = datetime.fromisoformat(last_sent_str)
                    except Exception:
                        last_sent = None
                if not last_sent or (now - last_sent).total_seconds() >= 4 * 24 * 60 * 60:
                    # Find the user's channel and guild
                    user_id = row["user_id"]
                    channel_id = None
                    for g in client.guilds:
                        member = g.get_member(user_id)
                        if member:
                            async with db_pool.acquire() as conn:
                                ch_row = await conn.fetchrow('SELECT channel_id FROM user_settings WHERE user_id=$1', user_id)
                            channel_id = ch_row["channel_id"] if ch_row else None
                            break
                    if channel_id:
                        channel = None
                        for g in client.guilds:
                            ch = g.get_channel(channel_id)
                            if ch:
                                channel = ch
                                break
                        if channel:
                            success = await send_job_results(channel.guild, user_id, row["keywords"], row["location"], 4)
                            if success:
                                async with db_pool.acquire() as conn:
                                    await conn.execute('UPDATE user_settings SET last_sent=$1 WHERE user_id=$2', now.isoformat(), user_id)
        await asyncio.sleep(60 * 10)  # Check every 10 minutes

# ---- Helper: Send Job Results ----
async def send_job_results(guild, user_id, keywords, location, days_limit=4):
    try:
        # Fetch channel_id and country from DB
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow('SELECT channel_id, country, subscribed FROM user_settings WHERE user_id=$1', user_id)
        if not row or not row.get("subscribed", True):
            print(f"[INFO] User {user_id} is not subscribed. Skipping job delivery.")
            return False
        channel_id = row["channel_id"] if row else None
        country = row["country"] if row and row["country"] else "us"
        channel = None
        if channel_id:
            # Find the channel in any guild
            for g in client.guilds:
                ch = g.get_channel(channel_id)
                if ch:
                    channel = ch
                    break
        if not channel or not channel.permissions_for(channel.guild.me).send_messages:
            print(f"[ERROR] No valid channel set for user {user_id}")
            return False
        keywords = keywords or []
        location = location or ""
        days_limit = 4
        query_parts = keywords + ([location] if location else [])
        query = "+".join(query_parts)
        url = f"https://jsearch.p.rapidapi.com/search?query={query}&page=1&num_pages=1&country={country}"
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
                    if len(recent_jobs) >= 20:
                        break
                if not recent_jobs:
                    print(f"[INFO] No recent jobs found for user {user_id}")
                    return True
                msg = f"<@{user_id}> Top Recent Job Results:\n"
                for job in recent_jobs:
                    # Use plain links in < > to suppress Discord embeds
                    msg += f"• {job['job_title']} at {job['employer_name']}: <{job['job_apply_link']}>\n"
                try:
                    await channel.send(msg)
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
@user_limit_check
async def searchnow(interaction: discord.Interaction):
    uid = interaction.user.id
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow('SELECT keywords, location, channel_id, updates_enabled, subscribed FROM user_settings WHERE user_id=$1', uid)
        user_count = await conn.fetchval('SELECT COUNT(*) FROM user_settings WHERE subscribed=TRUE')
    if not row or not row["keywords"] or not row.get("subscribed", True):
        await interaction.response.send_message(
            "You haven't set any keywords yet. Use /setkeywords first.\n\n"
            "Format: Enter keywords separated by commas, e.g. ai, ml, internship",
            ephemeral=True)
        return
    if not row["channel_id"]:
        await interaction.response.send_message(
            "You haven't set a channel to receive job results. Use /setchannel first.", ephemeral=True)
        return
    if row["updates_enabled"]:
        await interaction.response.send_message(
            "You have already started job updates. You will receive results every 4 days automatically.\n"
            "Only jobs posted within the last 4 days will be sent.",
            ephemeral=True)
        return
    # Enforce strict 18-user limit for enabling updates (resubscription)
    if not row["subscribed"] and user_count >= 18:
        await interaction.response.send_message(
            "❌ Sorry, the bot has reached the maximum number of users (18). Please try again later or ask someone to unsubscribe.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    # Find the channel in any guild
    channel = None
    for g in client.guilds:
        ch = g.get_channel(row["channel_id"])
        if ch:
            channel = ch
            break
    if not channel:
        await interaction.followup.send("Sorry, I couldn't find your selected channel in any server.", ephemeral=True)
        return
    success = await send_job_results(channel.guild, uid, row["keywords"], row["location"], 4)
    if success:
        # Enable periodic updates for this user and set last_sent to now, and resubscribe if needed
        now = datetime.now(UTC)
        async with db_pool.acquire() as conn:
            await conn.execute('UPDATE user_settings SET updates_enabled=TRUE, last_sent=$1, subscribed=TRUE WHERE user_id=$2', now.isoformat(), uid)
        await interaction.followup.send(
            "Done! You will now receive job results in your selected channel every 4 days (from now).\n"
            "Only jobs posted within the last 4 days will be sent.",
            ephemeral=True)
    else:
        await interaction.followup.send("Sorry, I couldn't send your job results in the selected channel. Please check my permissions or try again later.", ephemeral=True)
# ---- Slash Command: setchannel ----
@client.tree.command(name="setchannel", description="Set the channel where you want to receive job results")
@discord.app_commands.describe(channel="Select a text channel")
@user_limit_check
async def setchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    uid = interaction.user.id
    # Check bot permissions
    if not channel.permissions_for(interaction.guild.me).send_messages:
        await interaction.response.send_message("❌ I don't have permission to send messages in that channel.", ephemeral=True)
        return
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO user_settings (user_id, channel_id)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET channel_id = $2
        ''', uid, channel.id)
    await interaction.response.send_message(f"✅ Channel set! You'll receive job results in {channel.mention}.", ephemeral=True)

# ---- Slash Command: clearchannel ----
@client.tree.command(name="clearchannel", description="Clear your selected job results channel")
@user_limit_check
async def clearchannel(interaction: discord.Interaction):
    uid = interaction.user.id
    async with db_pool.acquire() as conn:
        await conn.execute('UPDATE user_settings SET channel_id=NULL WHERE user_id=$1', uid)
    await interaction.response.send_message("Your job results channel has been cleared.", ephemeral=True)

# ---- Slash Command: showchannel ----
@client.tree.command(name="showchannel", description="Show your currently selected job results channel")
@user_limit_check
async def showchannel(interaction: discord.Interaction):
    uid = interaction.user.id
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow('SELECT channel_id FROM user_settings WHERE user_id=$1', uid)
    if not row or not row["channel_id"]:
        await interaction.response.send_message("You haven't set a channel yet. Use /setchannel to pick one.", ephemeral=True)
        return
    channel = None
    for g in client.guilds:
        ch = g.get_channel(row["channel_id"])
        if ch:
            channel = ch
            break
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
