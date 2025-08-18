# 🤡 Tæk8 - TFT 8th Place Tracker Bot

Tæk8 is a Discord bot that tracks **Teamfight Tactics** matches using Riot’s API.  
Whenever a tracked player finishes in **8th place**, the bot announces it in Discord.  
It also maintains **daily** and **all-time** scoreboards.

---

## ✨ Features
- Bind **one or more Riot IDs** to your Discord account
- Announces when someone gets **8th place 🤡**
- Daily & all-time scoreboard tracking
- Slash commands:
  - `/t8 add` — Add your Riot ID
  - `/t8 leaderboard` — Show current scores
  - `/t8 me` — Show your stats across all bound Riot IDs
  - `/t8 bind` — Admin only: bind a Riot ID to a Discord member
- Automatic **daily reset** with the previous day’s final scoreboard

---

## 📦 Requirements
- Python **3.10+** (tested on 3.13)
- Libraries:
  - [nextcord](https://pypi.org/project/nextcord/)
  - [aiohttp](https://pypi.org/project/aiohttp/)
  - [python-dotenv](https://pypi.org/project/python-dotenv/)

Install dependencies with:
```bash
pip install -r requirements.txt