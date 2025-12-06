import os
import json
import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Any

import nextcord
from nextcord.ext import commands, tasks
from nextcord import Interaction, SlashOption
from dotenv import load_dotenv
import random
from nextcord import FFmpegPCMAudio

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv(override=True)
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
RIOT_API_KEY = os.getenv("RIOT_API_KEY")
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID"))
GUILD_ID = int(os.getenv("GUILD_ID"))
TIMEZONE = ZoneInfo("Asia/Bangkok")
CHECK_INTERVAL = 60  # seconds

# File paths
DATA_FILE = "players.json"
SCORES_FILE = "scores.json"
LAST_MATCH_FILE = "last_matches.json"
AUDIO_PATH_NAMES = "audio/names"
AUDIO_FILE_8TH = "audio/8th_place.mp3"

# Enable intents
intents = nextcord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

class TFTTrackerBot(commands.Bot):
    """Main bot class for TFT 8th place tracking with backward compatibility"""
    
    def __init__(self):
        super().__init__(intents=intents)
        
        # Load data using the exact same format as before
        self.players = self.load_json(DATA_FILE, {})
        self.scores = self.load_json(SCORES_FILE, {"daily": {}, "all_time": {}})
        self.last_matches = self.load_json(LAST_MATCH_FILE, {})
        
        # Last reset day
        self.last_reset_day = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
        
        # Background tasks
        self.check_matches_task = tasks.loop(seconds=CHECK_INTERVAL)(self.check_matches)
        self.daily_reset_task = tasks.loop(minutes=1)(self.daily_reset_checker)
        
        # Voice connection tracking
        self.voice_connection_attempts = 0
        self.voice_disabled_until = None
    
    # -------- Utility functions (maintaining exact same behavior) --------
    def load_json(self, path, default):
        """Load JSON data from file (same as original)"""
        try:
            with open(path, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return default

    def save_json(self, path, data):
        """Save JSON data to file (same as original)"""
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def get_riot_headers(self):
        """Get Riot API headers (same as original)"""
        return {"X-Riot-Token": RIOT_API_KEY}

    async def get_puuid(self, session, riot_name, riot_tag):
        """Get PUUID from Riot ID (same as original)"""
        url = f"https://asia.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{riot_name}/{riot_tag}"
        async with session.get(url, headers=self.get_riot_headers()) as resp:
            if resp.status == 200:
                return (await resp.json()).get("puuid")
        return None

    async def get_latest_match_id(self, session, puuid):
        """Get latest match ID (same as original)"""
        url = f"https://sea.api.riotgames.com/tft/match/v1/matches/by-puuid/{puuid}/ids?count=1"
        async with session.get(url, headers=self.get_riot_headers()) as resp:
            if resp.status == 200:
                ids = await resp.json()
                return ids[0] if ids else None
        return None

    async def get_placement(self, session, match_id, puuid):
        """Get placement from match (same as original)"""
        url = f"https://sea.api.riotgames.com/tft/match/v1/matches/{match_id}"
        async with session.get(url, headers=self.get_riot_headers()) as resp:
            if resp.status == 200:
                data = await resp.json()
                for p in data["info"]["participants"]:
                    if p["puuid"] == puuid:
                        return p["placement"]
        return None

    def update_score(self, riot_id):
        """Update score (same as original)"""
        today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
        if today not in self.scores["daily"]:
            self.scores["daily"][today] = {}
        self.scores["daily"][today][riot_id] = self.scores["daily"][today].get(riot_id, 0) + 1
        self.scores["all_time"][riot_id] = self.scores["all_time"].get(riot_id, 0) + 1
        self.save_json(SCORES_FILE, self.scores)

    def reset_daily_scores(self):
        """Reset daily scores (same as original)"""
        self.scores["daily"] = {}
        self.save_json(SCORES_FILE, self.scores)

    def resolve_display_name(self, riot_id: str) -> str:
        """Resolve display name (same as original)"""
        pdata = self.players.get(riot_id)
        if pdata:
            discord_id = pdata.get("discord_id")
            if discord_id:
                guild = self.get_guild(GUILD_ID)
                member = None
                if guild:
                    member = guild.get_member(int(discord_id))
                if member:
                    return member.display_name
                else:
                    return f"<Discord:{discord_id}>"
        return riot_id

    def format_scoreboard(self):
        """Format scoreboard (same as original)"""
        today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
        daily_scores = self.scores.get("daily", {}).get(today, {})
        msg = f"**📊 {today} Daily 8th Place Count:**\n"
        if daily_scores:
            for riot_id, count in sorted(daily_scores.items(), key=lambda x: x[1], reverse=True):
                display_name = self.resolve_display_name(riot_id)
                msg += f"- {display_name}: {count}\n"
        else:
            msg += "No data yet.\n"
        msg += "\n**🏆 All-Time 8th Place Count:**\n"
        all_time_scores = self.scores.get("all_time", {})
        if all_time_scores:
            for riot_id, count in sorted(all_time_scores.items(), key=lambda x: x[1], reverse=True):
                display_name = self.resolve_display_name(riot_id)
                msg += f"- {display_name}: {count}\n"
        else:
            msg += "No data yet.\n"
        return msg

    def format_scoreboard_for_date(self, date_str):
        """Format scoreboard for specific date (same as original)"""
        daily_scores = self.scores.get("daily", {}).get(date_str, {})
        msg = f"**📊 {date_str} Today's 8th Place Count:**\n"
        if daily_scores:
            for riot_id, count in sorted(daily_scores.items(), key=lambda x: x[1], reverse=True):
                display_name = self.resolve_display_name(riot_id)
                msg += f"- {display_name}: {count}\n"
        else:
            msg += "No data yet.\n"
        msg += "\n**🏆 All-Time 8th Place Count:**\n"
        all_time_scores = self.scores.get("all_time", {})
        if all_time_scores:
            for riot_id, count in sorted(all_time_scores.items(), key=lambda x: x[1], reverse=True):
                display_name = self.resolve_display_name(riot_id)
                msg += f"- {display_name}: {count}\n"
        else:
            msg += "No data yet.\n"
        return msg

    async def get_target_channel(self):
        """Get target channel (same as original)"""
        try:
            channel = await self.fetch_channel(TARGET_CHANNEL_ID)
            return channel
        except Exception as e:
            logger.error(f"Error fetching channel {TARGET_CHANNEL_ID}: {e}")
            return None

    async def choose_voice_channel(self, exclude_discord_id):
        """Choose voice channel (same as original)"""
        # If voice is temporarily disabled, don't try to connect
        if self.voice_disabled_until and datetime.now() < self.voice_disabled_until:
            return None
            
        guild = self.get_guild(GUILD_ID)
        if not guild:
            return None
        channel_user_counts = []
        for channel in guild.voice_channels:
            count = 0
            for member in channel.members:
                member_id_str = str(member.id)
                if any(pdata.get("discord_id") == member_id_str for pdata in self.players.values()):
                    count += 1
            if count > 0:
                channel_user_counts.append((channel, count))
        if not channel_user_counts:
            return None
        # Find max count
        max_count = max(count for _, count in channel_user_counts)
        # Filter channels with max count
        candidates = [ch for ch, count in channel_user_counts if count == max_count]
        # Prefer channels that do not contain exclude_discord_id
        filtered = []
        for ch in candidates:
            if all(str(member.id) != str(exclude_discord_id) for member in ch.members):
                filtered.append(ch)
        if filtered:
            candidates = filtered
        # If multiple candidates still, choose randomly
        chosen_channel = random.choice(candidates)
        return chosen_channel

    async def simple_voice_connect(self, channel):
        """Simple voice connection with minimal retry logic"""
        try:
            # Clean up any existing connections to this guild
            for vc in self.voice_clients:
                if vc.guild.id == channel.guild.id:
                    try:
                        await vc.disconnect(force=True)
                    except:
                        pass
            
            # Try to connect with a short timeout
            voice_client = await asyncio.wait_for(
                channel.connect(timeout=10.0),
                timeout=15.0
            )
            return voice_client
        except asyncio.TimeoutError:
            logger.warning(f"Timeout connecting to voice channel {channel.name}")
            return None
        except Exception as e:
            logger.warning(f"Failed to connect to voice channel {channel.name}: {e}")
            return None

    async def play_audio_for_8th(self, discord_id):
        """Play audio for 8th place with simplified approach"""
        # Check if voice is temporarily disabled
        if self.voice_disabled_until and datetime.now() < self.voice_disabled_until:
            logger.info("Voice is temporarily disabled, skipping audio playback")
            return
            
        channel = await self.choose_voice_channel(discord_id)
        if channel is None:
            logger.info("No suitable voice channel found for audio playback")
            return
            
        try:
            voice_client = await self.simple_voice_connect(channel)
            if voice_client is None:
                # If connection fails, disable voice for a while
                self.voice_connection_attempts += 1
                if self.voice_connection_attempts >= 3:
                    disable_minutes = 30  # Disable for 30 minutes after 3 failed attempts
                    self.voice_disabled_until = datetime.now() + timedelta(minutes=disable_minutes)
                    self.voice_connection_attempts = 0
                    logger.warning(f"Voice connections disabled until {self.voice_disabled_until}")
                return
                
            # Reset attempt counter on successful connection
            self.voice_connection_attempts = 0
            
            name_audio_path = os.path.join(AUDIO_PATH_NAMES, f"{discord_id}.mp3")
            
            # Play name audio if exists
            if os.path.isfile(name_audio_path):
                audio_source = FFmpegPCMAudio(name_audio_path)
                voice_client.play(audio_source)
                # Wait for playback to finish
                while voice_client.is_playing():
                    await asyncio.sleep(0.1)
            
            # Play 8th place audio
            if os.path.isfile(AUDIO_FILE_8TH):
                audio_source = FFmpegPCMAudio(AUDIO_FILE_8TH)
                voice_client.play(audio_source)
                # Wait for playback to finish
                while voice_client.is_playing():
                    await asyncio.sleep(0.1)
                    
        except Exception as e:
            logger.error(f"Error during audio playback: {e}")
        finally:
            try:
                await voice_client.disconnect()
            except:
                pass  # Ignore errors during disconnect

    # -------- Background Tasks --------
    async def check_matches(self):
        """Check for new matches (same as original)"""
        logger.info("Checking matches...")
        channel = await self.get_target_channel()
        if channel is None:
            logger.error(f"Channel with ID {TARGET_CHANNEL_ID} not found.")
            return
        logger.info(f"Loaded {len(self.players)} players to check.")
        async with aiohttp.ClientSession() as session:
            for riot_full, pdata in self.players.items():
                puuid = pdata.get("puuid")
                if not puuid:
                    logger.warning(f"Warning: No puuid found for player {riot_full}, skipping.")
                    continue

                match_id = await self.get_latest_match_id(session, puuid)
                if not match_id or self.last_matches.get(puuid) == match_id:
                    logger.info(f"No new match for {riot_full}. Current match_id: {match_id}, last known: {self.last_matches.get(puuid)}")
                    continue  # No new match

                placement = await self.get_placement(session, match_id, puuid)
                logger.info(f"Player {riot_full} match {match_id} placement: {placement}")
                if placement == 8:
                    self.update_score(riot_full)
                    logger.info(f"User {riot_full} got 8th place!")
                    try:
                        discord_id = pdata.get("discord_id")
                        if discord_id:
                            mention = f"<@{int(discord_id)}>"
                        else:
                            mention = riot_full
                        embed = nextcord.Embed(
                            title="💀 8th Place Alert!",
                            description=f"{mention} just finished **8th place** in TFT!",
                            color=nextcord.Color.red()
                        )
                        embed.set_footer(text="Better luck next time...")
                        await channel.send(embed=embed)
                        if discord_id:
                            await self.play_audio_for_8th(discord_id)
                    except Exception as e:
                        logger.error(f"Error sending message in channel: {e}")
                self.last_matches[puuid] = match_id
        self.save_json(LAST_MATCH_FILE, self.last_matches)

    async def daily_reset_checker(self):
        """Check for daily reset (same as original)"""
        now = datetime.now(TIMEZONE)
        today_str = now.strftime("%Y-%m-%d")
        if self.last_reset_day != today_str:
            logger.info("Resetting daily scores...")
            channel = await self.get_target_channel()
            if channel:
                try:
                    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
                    final_scoreboard = self.format_scoreboard_for_date(yesterday)
                    embed = nextcord.Embed(
                        title="🕛 Daily Reset!",
                        description="Final scoreboard before reset:\n" + final_scoreboard,
                        color=nextcord.Color.purple()
                    )
                    await channel.send(embed=embed)
                except Exception as e:
                    logger.error(f"Error sending final scoreboard message: {e}")
            self.reset_daily_scores()
            self.last_reset_day = today_str

    # -------- Events --------
    async def on_ready(self):
        """Bot is ready (same as original)"""
        logger.info(f"Logged in as {self.user}")
        if not self.check_matches_task.is_running():
            self.check_matches_task.start()
        if not self.daily_reset_task.is_running():
            self.daily_reset_task.start()
        # Log opus status for debugging
        try:
            import nextcord.opus as opus
            logger.info(f"Opus loaded: {opus.is_loaded()}")
        except Exception as e:
            logger.error(f"Opus check failed: {e}")

# Create bot instance
bot = TFTTrackerBot()

# -------- Slash Commands (maintaining exact same structure) --------
@bot.slash_command(name="t8", description="Tæk8 scoreboard commands", guild_ids=[GUILD_ID])
async def t8(interaction: Interaction):
    pass  # Base command for subcommands

@t8.subcommand(description="Add your Riot ID")
async def add(interaction: Interaction, riot_id: str = SlashOption(description="Format: Name#TAG")):
    await interaction.response.defer()
    if "#" not in riot_id:
        await interaction.followup.send("❌ Invalid Riot ID format. Use Name#TAG.")
        return

    name, tag = riot_id.split("#", 1)
    riot_full = f"{name}#{tag}"
    if riot_full in bot.players:
        await interaction.followup.send("❌ Riot ID already added.")
        return

    async with aiohttp.ClientSession() as session:
        puuid = await bot.get_puuid(session, name, tag)

    if not puuid:
        await interaction.followup.send("❌ Could not find that Riot ID.")
        return

    bot.players[riot_full] = {"name": name, "tag": tag, "puuid": puuid, "discord_id": str(interaction.user.id)}
    bot.save_json(DATA_FILE, bot.players)
    await interaction.followup.send(f"✅ Added {riot_full} to the scoreboard!")

@t8.subcommand(description="Show leaderboard")
async def leaderboard(interaction: Interaction):
    await interaction.response.defer()
    msg = bot.format_scoreboard()
    embed = nextcord.Embed(
        title="📊 TFT 8th Place Scoreboard",
        description=msg,
        color=nextcord.Color.fuchsia()
    )
    embed.set_footer(text="Tæk8 Score Tracker")
    await interaction.followup.send(embed=embed)

@t8.subcommand(description="Show your stats")
async def me(interaction: Interaction):
    uid = str(interaction.user.id)
    # Collect all riot_full IDs bound to this discord user
    riot_full_list = [r_id for r_id, pdata in bot.players.items() if pdata.get("discord_id") == uid]
    if not riot_full_list:
        await interaction.response.send_message("❌ You have not added your Riot ID yet.")
        return

    msg_lines = []
    for riot_full in riot_full_list:
        today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
        daily = bot.scores.get("daily", {}).get(today, {}).get(riot_full, 0)
        all_time = bot.scores.get("all_time", {}).get(riot_full, 0)
        msg_lines.append(f"📊 **{interaction.user.display_name} ({riot_full})**\nDaily 8th: {daily}\nAll-Time 8th: {all_time}")
    embed = nextcord.Embed(
        title=f"📊 {interaction.user.display_name}'s Stats",
        description="\n\n".join(msg_lines),
        color=nextcord.Color.green()
    )
    await interaction.response.send_message(embed=embed)

@t8.subcommand(description="Bind a Riot ID to a Discord member (Admin only)")
async def bind(
    interaction: Interaction,
    member: nextcord.Member = SlashOption(description="Discord member to bind"),
    riot_id: str = SlashOption(description="Format: Name#TAG")
):
    if riot_id not in bot.players:
        await interaction.response.send_message("❌ That Riot ID is not registered.", ephemeral=True)
        return

    bot.players[riot_id]["discord_id"] = str(member.id)
    bot.save_json(DATA_FILE, bot.players)
    await interaction.response.send_message(f"✅ Bound {riot_id} to {member.display_name}.")

@bot.slash_command(name="testvoice", description="Test audio playback for a user", guild_ids=[GUILD_ID])
async def testvoice(interaction: Interaction, member: nextcord.Member):
    # Defer the response immediately to prevent interaction timeout
    await interaction.response.defer()
    
    discord_id = str(member.id)
    if not member.voice or not member.voice.channel:
        await interaction.followup.send("❌ That user is not in a voice channel.")
        return

    # Ensure opus is loaded (macOS typical brew install path fallback)
    try:
        import nextcord.opus as opus
        if not opus.is_loaded():
            # Try common library names / paths
            tried = []
            for libname in [
                "libopus",  # default lookup
                "opus",
                "/opt/homebrew/opt/opus/lib/libopus.dylib",
                "/opt/homebrew/opt/opus/lib/libopus.0.dylib",
            ]:
                try:
                    opus.load_opus(libname)
                    break
                except Exception as _e:
                    tried.append(f"{libname}: {_e}")
            if not opus.is_loaded():
                await interaction.followup.send(
                    "❌ Opus library not loaded. Install via `brew install opus` and restart bot. Attempts: " + "; ".join(tried)
                )
                return
    except Exception as e:
        await interaction.followup.send(f"❌ Failed loading opus: {e}")
        return

    channel = member.voice.channel
    
    # Send initial response
    await interaction.followup.send(f"🔊 Testing voice for {member.display_name} in {channel.name}...")
    
    try:
        # Use our simple connection method
        voice_client = await bot.simple_voice_connect(channel)
        if voice_client is None:
            await interaction.followup.send("❌ Failed to connect to voice channel. Voice might be temporarily unavailable.")
            return
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to connect to voice channel: {e}")
        return

    try:
        files_to_play = [
            os.path.join(AUDIO_PATH_NAMES, f"{discord_id}.mp3"),
            AUDIO_FILE_8TH
        ]
        
        for file_path in files_to_play:
            if os.path.isfile(file_path):
                audio_source = FFmpegPCMAudio(file_path)
                voice_client.play(audio_source)
                
                # Wait for playback to finish
                while voice_client.is_playing():
                    await asyncio.sleep(0.5)
            else:
                await interaction.followup.send(f"⚠️ Missing file: {file_path}")
    except Exception as e:
        await interaction.followup.send(f"Error during playback: {e}")
    finally:
        try:
            # Add a small delay before disconnecting to ensure audio finishes
            await asyncio.sleep(0.5)
            await voice_client.disconnect()
            await interaction.followup.send("👋 Disconnected after test playback.")
        except:
            await interaction.followup.send("👋 Voice test completed (disconnect may have failed).")

# Run the bot
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN environment variable is required")
        exit(1)
    
    if not RIOT_API_KEY:
        logger.error("RIOT_API_KEY environment variable is required")
        exit(1)
    
    bot.run(DISCORD_TOKEN)