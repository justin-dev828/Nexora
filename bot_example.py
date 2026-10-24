"""So arbeitet dein discord.py-Bot mit dem Dashboard zusammen.
1) Einstellungen aus der DB lesen   2) Herzschlag/Statistik fürs Dashboard schreiben"""
import json
import sqlite3
import time

from discord.ext import tasks

DB_PATH = "nexora.db"  # gleiche Datei wie DB_PATH im Dashboard
START = time.time()
DEFAULTS = {"logch": "", "daily": 100, "streak": 10, "cur": "Coins"}  # nur Beispiel


# ---------- 1) Einstellungen lesen ----------
def get_cfg(guild_id: int) -> dict:
    con = sqlite3.connect(DB_PATH)
    row = con.execute("SELECT data FROM guild_settings WHERE guild_id=?",
                      (str(guild_id),)).fetchone()
    con.close()
    return {**DEFAULTS, **(json.loads(row[0]) if row else {})}


def command_enabled(cfg: dict, module: str, command: str) -> bool:
    return cfg.get(f"{module}.on", True) and cfg.get(f"c.{command}", True)


# ---------- 2) Status für den Tracker auf der Startseite ----------
# Unten bei "bot" deine Bot-Instanz verwenden (z. B. commands.Bot oder discord.Client mit CommandTree).
@tasks.loop(seconds=30)
async def heartbeat():
    rows = {
        "heartbeat": time.time(),
        "servers": len(bot.guilds),
        "users": sum(g.member_count or 0 for g in bot.guilds),
        "ping": round(bot.latency * 1000),
        "commands": len(bot.tree.get_commands()),
        "started": START,
    }
    con = sqlite3.connect(DB_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS bot_stats (key TEXT PRIMARY KEY, value TEXT)")
    con.executemany("INSERT INTO bot_stats VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    [(k, str(v)) for k, v in rows.items()])
    con.commit()
    con.close()

# Starten, z. B. in setup_hook oder on_ready:   heartbeat.start()

# Beispiel in einem Slash-Befehl:
#
# @bot.tree.command(name="belohnung")
# async def belohnung(inter: discord.Interaction):
#     cfg = get_cfg(inter.guild_id)
#     if not cfg["logch"]:
#         return await inter.response.send_message("Bitte erst /logkanal einrichten.", ephemeral=True)
#     if not command_enabled(cfg, "eco", "belohnung"):
#         return await inter.response.send_message("Befehl ist hier deaktiviert.", ephemeral=True)
#     betrag = cfg["daily"]
#     ...
