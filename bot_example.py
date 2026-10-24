"""So liest dein discord.py-Bot die Einstellungen aus dem Dashboard."""
import json
import sqlite3

DB_PATH = "nexora.db"  # gleiche Datei wie im Dashboard (DB_PATH)

DEFAULTS = {"logch": "", "daily": 100, "streak": 10, "cur": "Coins"}  # nur Beispiel


def get_cfg(guild_id: int) -> dict:
    con = sqlite3.connect(DB_PATH)
    row = con.execute("SELECT data FROM guild_settings WHERE guild_id=?",
                      (str(guild_id),)).fetchone()
    con.close()
    return {**DEFAULTS, **(json.loads(row[0]) if row else {})}


def command_enabled(cfg: dict, module: str, command: str) -> bool:
    return cfg.get(f"{module}.on", True) and cfg.get(f"c.{command}", True)


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
