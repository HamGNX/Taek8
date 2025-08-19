import os
import json
import asyncio
import aiohttp
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import nextcord
from nextcord.ext import commands, tasks
from nextcord import Interaction, SlashOption
from dotenv import load_dotenv
import random
from nextcord import FFmpegPCMAudio

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
RIOT_API_KEY = os.getenv("RIOT_API_KEY")
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID"))

GUILD_ID = int(os.getenv("GUILD_ID"))

TIMEZONE = ZoneInfo("Asia/Bangkok")
CHECK_INTERVAL = 60  # seconds

DATA_FILE = "players.json"
SCORES_FILE = "scores.json"
LAST_MATCH_FILE = "last_matches.json"

AUDIO_PATH_NAMES = "audio/names"
AUDIO_FILE_8TH = "audio/8th_place.mp3"


# Enable intents (no message content since you're only using slash commands)
intents = nextcord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(intents=intents)

# -------- Utility functions --------
def load_json(path, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

players = load_json(DATA_FILE, {})        # {riot_full: {"name": riot_name, "tag": riot_tag, "puuid": puuid, "discord_id": discord_id}}
scores = load_json(SCORES_FILE, {"daily": {}, "all_time": {}})
last_matches = load_json(LAST_MATCH_FILE, {})  # {puuid: last_match_id}

def get_riot_headers():
    return {"X-Riot-Token": RIOT_API_KEY}

async def get_puuid(session, riot_name, riot_tag):
    url = f"https://asia.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{riot_name}/{riot_tag}"
    async with session.get(url, headers=get_riot_headers()) as resp:
        if resp.status == 200:
            return (await resp.json()).get("puuid")
    return None

async def get_latest_match_id(session, puuid):
    url = f"https://sea.api.riotgames.com/tft/match/v1/matches/by-puuid/{puuid}/ids?count=1"
    async with session.get(url, headers=get_riot_headers()) as resp:
        if resp.status == 200:
            ids = await resp.json()
            return ids[0] if ids else None
    return None

async def get_placement(session, match_id, puuid):
    url = f"https://sea.api.riotgames.com/tft/match/v1/matches/{match_id}"
    async with session.get(url, headers=get_riot_headers()) as resp:
        if resp.status == 200:
            data = await resp.json()
            for p in data["info"]["participants"]:
                if p["puuid"] == puuid:
                    return p["placement"]
    return None

def update_score(riot_id):
    today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
    if today not in scores["daily"]:
        scores["daily"][today] = {}
    scores["daily"][today][riot_id] = scores["daily"][today].get(riot_id, 0) + 1
    scores["all_time"][riot_id] = scores["all_time"].get(riot_id, 0) + 1
    save_json(SCORES_FILE, scores)

def reset_daily_scores():
    scores["daily"] = {}
    save_json(SCORES_FILE, scores)

def resolve_display_name(riot_id: str) -> str:
    pdata = players.get(riot_id)
    if pdata:
        discord_id = pdata.get("discord_id")
        if discord_id:
            guild = bot.get_guild(GUILD_ID)
            member = None
            if guild:
                member = guild.get_member(int(discord_id))
            if member:
                return member.display_name
            else:
                return f"<Discord:{discord_id}>"
    return riot_id

def format_scoreboard():
    today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
    daily_scores = scores.get("daily", {}).get(today, {})
    msg = f"**📊 {today} Daily 8th Place Count:**\n"
    if daily_scores:
        for riot_id, count in sorted(daily_scores.items(), key=lambda x: x[1], reverse=True):
            display_name = resolve_display_name(riot_id)
            msg += f"- {display_name}: {count}\n"
    else:
        msg += "No data yet.\n"
    msg += "\n**🏆 All-Time 8th Place Count:**\n"
    all_time_scores = scores.get("all_time", {})
    if all_time_scores:
        for riot_id, count in sorted(all_time_scores.items(), key=lambda x: x[1], reverse=True):
            display_name = resolve_display_name(riot_id)
            msg += f"- {display_name}: {count}\n"
    else:
        msg += "No data yet.\n"
    return msg

def format_scoreboard_for_date(date_str):
    daily_scores = scores.get("daily", {}).get(date_str, {})
    msg = f"**📊 {date_str} Today's 8th Place Count:**\n"
    if daily_scores:
        for riot_id, count in sorted(daily_scores.items(), key=lambda x: x[1], reverse=True):
            display_name = resolve_display_name(riot_id)
            msg += f"- {display_name}: {count}\n"
    else:
        msg += "No data yet.\n"
    msg += "\n**🏆 All-Time 8th Place Count:**\n"
    all_time_scores = scores.get("all_time", {})
    if all_time_scores:
        for riot_id, count in sorted(all_time_scores.items(), key=lambda x: x[1], reverse=True):
            display_name = resolve_display_name(riot_id)
            msg += f"- {display_name}: {count}\n"
    else:
        msg += "No data yet.\n"
    return msg

# New helper function to fetch the target channel
async def get_target_channel():
    try:
        channel = await bot.fetch_channel(TARGET_CHANNEL_ID)
        return channel
    except Exception as e:
        print(f"Error fetching channel {TARGET_CHANNEL_ID}: {e}")
        return None

# -------- Slash Command Group --------
@bot.slash_command(name="t8", description="Tæk8 scoreboard commands", guild_ids=[GUILD_ID])  # Use GUILD_ID from env
async def t8(interaction: Interaction):
    pass  # This won't run directly, only its subcommands will.

@t8.subcommand(description="Add your Riot ID")
async def add(interaction: Interaction, riot_id: str = SlashOption(description="Format: Name#TAG")):
    await interaction.response.defer()
    if "#" not in riot_id:
        await interaction.followup.send("❌ Invalid Riot ID format. Use Name#TAG.")
        return

    name, tag = riot_id.split("#", 1)
    riot_full = f"{name}#{tag}"
    if riot_full in players:
        await interaction.followup.send("❌ Riot ID already added.")
        return

    async with aiohttp.ClientSession() as session:
        puuid = await get_puuid(session, name, tag)

    if not puuid:
        await interaction.followup.send("❌ Could not find that Riot ID.")
        return

    players[riot_full] = {"name": name, "tag": tag, "puuid": puuid, "discord_id": str(interaction.user.id)}
    save_json(DATA_FILE, players)
    await interaction.followup.send(f"✅ Added {riot_full} to the scoreboard!")

@t8.subcommand(description="Show leaderboard")
async def leaderboard(interaction: Interaction):
    await interaction.response.defer()
    msg = format_scoreboard()
    await interaction.followup.send(msg)

@t8.subcommand(description="Show your stats")
async def me(interaction: Interaction):
    uid = str(interaction.user.id)
    # Collect all riot_full IDs bound to this discord user
    riot_full_list = [r_id for r_id, pdata in players.items() if pdata.get("discord_id") == uid]
    if not riot_full_list:
        await interaction.response.send_message("❌ You have not added your Riot ID yet.")
        return

    msg_lines = []
    for riot_full in riot_full_list:
        today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
        daily = scores.get("daily", {}).get(today, {}).get(riot_full, 0)
        all_time = scores.get("all_time", {}).get(riot_full, 0)
        msg_lines.append(f"📊 **{interaction.user.display_name} ({riot_full})**\nDaily 8th: {daily}\nAll-Time 8th: {all_time}")
    await interaction.response.send_message("\n\n".join(msg_lines))

@t8.subcommand(description="Bind a Riot ID to a Discord member (Admin only)")
async def bind(
    interaction: Interaction,
    member: nextcord.Member = SlashOption(description="Discord member to bind"),
    riot_id: str = SlashOption(description="Format: Name#TAG")
):
    if riot_id not in players:
        await interaction.response.send_message("❌ That Riot ID is not registered.", ephemeral=True)
        return

    players[riot_id]["discord_id"] = str(member.id)
    save_json(DATA_FILE, players)
    await interaction.response.send_message(f"✅ Bound {riot_id} to {member.display_name}.")

async def play_audio_for_8th(discord_id: str):
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    candidate_channels = []
    bound_ids = [pdata.get("discord_id") for pdata in players.values() if pdata.get("discord_id")]
    for vc in guild.voice_channels:
        members = vc.members
        bound_members = [m for m in members if str(m.id) in bound_ids]
        if bound_members:
            candidate_channels.append((vc, bound_members))
    if not candidate_channels:
        print("No eligible voice channels found.")
        return
    max_count = max(len(bound) for _, bound in candidate_channels)
    filtered = [(vc, bound) for vc, bound in candidate_channels if len(bound) == max_count]
    target_vc = None
    for vc, bound in filtered:
        if discord_id not in [str(m.id) for m in bound]:
            target_vc = vc
            break
    if not target_vc:
        target_vc, _ = random.choice(filtered)
    try:
        voice = await target_vc.connect()
        name_file = os.path.join(AUDIO_PATH_NAMES, f"{discord_id}.mp3")
        if os.path.exists(name_file):
            voice.play(FFmpegPCMAudio(name_file))
            while voice.is_playing():
                await asyncio.sleep(1)
        if os.path.exists(AUDIO_FILE_8TH):
            voice.play(FFmpegPCMAudio(AUDIO_FILE_8TH))
            while voice.is_playing():
                await asyncio.sleep(1)
        await voice.disconnect()
    except Exception as e:
        print(f"Error playing audio: {e}")

# -------- Background Loop --------
@tasks.loop(seconds=CHECK_INTERVAL)
async def check_matches():
    print("Checking matches...")
    channel = await get_target_channel()
    if channel is None:
        print(f"Channel with ID {TARGET_CHANNEL_ID} not found.")
        return
    print(f"Loaded {len(players)} players to check.")
    async with aiohttp.ClientSession() as session:
        for riot_full, pdata in players.items():
            puuid = pdata.get("puuid")
            if not puuid:
                print(f"Warning: No puuid found for player {riot_full}, skipping.")
                continue

            match_id = await get_latest_match_id(session, puuid)
            if not match_id or last_matches.get(puuid) == match_id:
                print(f"No new match for {riot_full}. Current match_id: {match_id}, last known: {last_matches.get(puuid)}")
                continue  # No new match

            placement = await get_placement(session, match_id, puuid)
            print(f"Player {riot_full} match {match_id} placement: {placement}")
            if placement == 8:
                update_score(riot_full)
                print(f"User {riot_full} got 8th place!")
                try:
                    discord_id = pdata.get("discord_id")
                    if discord_id:
                        mention = f"<@{int(discord_id)}>"
                    else:
                        mention = riot_full
                    await channel.send(f"🤡 {mention} got 8th place! 🤡")
                    if discord_id:
                        await play_audio_for_8th(discord_id)
                except Exception as e:
                    print(f"Error sending message in channel: {e}")
            last_matches[puuid] = match_id
    save_json(LAST_MATCH_FILE, last_matches)

# -------- Daily Reset Tracker --------
last_reset_day = datetime.now(TIMEZONE).strftime("%Y-%m-%d")

@tasks.loop(minutes=1)
async def daily_reset_checker():
    global last_reset_day
    now = datetime.now(TIMEZONE)
    today_str = now.strftime("%Y-%m-%d")
    if last_reset_day != today_str:
        print("Resetting daily scores...")
        channel = await get_target_channel()
        if channel:
            try:
                yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
                final_scoreboard = format_scoreboard_for_date(yesterday)
                await channel.send("🕛 Daily reset! Final scoreboard before reset:\n" + final_scoreboard)
            except Exception as e:
                print(f"Error sending final scoreboard message: {e}")
        reset_daily_scores()
        last_reset_day = today_str

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    if not check_matches.is_running():
        check_matches.start()
    if not daily_reset_checker.is_running():
        daily_reset_checker.start()

bot.run(DISCORD_TOKEN)