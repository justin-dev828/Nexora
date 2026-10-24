"""So arbeitet dein discord.py-Bot mit dem Nexora-Dashboard auf Netlify zusammen.
Der Bot kann überall laufen, er spricht nur per Internet mit deiner Dashboard-Seite.

Umgebungsvariablen beim Bot:
  DASHBOARD_URL = https://DEINE-SEITE.pages.dev (oder deine eigene Domain)
  BOT_API_KEY   = derselbe geheime Schlüssel wie bei der Webseite (BOT_API_KEY)
"""
import os
import time

import aiohttp
from discord.ext import tasks

DASHBOARD_URL = os.environ["DASHBOARD_URL"].rstrip("/")
HEAD = {"Authorization": f"Bearer {os.environ['BOT_API_KEY']}"}
START = time.time()
_cache: dict = {}


# ---------- 1) Einstellungen eines Servers holen (30 Sek. zwischengespeichert) ----------
async def get_cfg(guild_id: int) -> dict:
    hit = _cache.get(guild_id)
    if hit and time.time() - hit[0] < 30:
        return hit[1]
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{DASHBOARD_URL}/api/bot/settings/{guild_id}", headers=HEAD,
                             timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status == 200:
                    cfg = await r.json()
                    _cache[guild_id] = (time.time(), cfg)
                    return cfg
    except Exception:
        pass
    return hit[1] if hit else {}  # Dashboard nicht erreichbar -> letzte bekannte Werte


def command_enabled(cfg: dict, module: str, command: str) -> bool:
    return cfg.get(f"{module}.on", True) and cfg.get(f"c.{command}", True)


# ---------- 2) Status für den Tracker (alle 30 Sekunden) ----------
# Unten "bot" durch deine Bot-Instanz ersetzen (commands.Bot oder discord.Client mit CommandTree).
@tasks.loop(seconds=30)
async def heartbeat():
    data = {
        "servers": len(bot.guilds),
        "users": sum(g.member_count or 0 for g in bot.guilds),
        "ping": round(bot.latency * 1000),
        "commands": len(bot.tree.get_commands()),
        "started": START,
    }
    try:
        async with aiohttp.ClientSession() as s:
            await s.post(f"{DASHBOARD_URL}/api/bot/heartbeat", json=data, headers=HEAD,
                         timeout=aiohttp.ClientTimeout(total=5))
    except Exception:
        pass

# Starten, z. B. in setup_hook oder on_ready:   heartbeat.start()

# Beispiel in einem Slash-Befehl:
#
# @bot.tree.command(name="belohnung")
# async def belohnung(inter: discord.Interaction):
#     cfg = await get_cfg(inter.guild_id)
#     if not cfg.get("logch"):
#         return await inter.response.send_message("Bitte erst /logkanal einrichten.", ephemeral=True)
#     if not command_enabled(cfg, "eco", "belohnung"):
#         return await inter.response.send_message("Befehl ist hier deaktiviert.", ephemeral=True)
#     betrag = cfg["daily"]
#     ...
