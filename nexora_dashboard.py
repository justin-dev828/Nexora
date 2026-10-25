"""Nexora-Dashboard-Anbindung als discord.py-Erweiterung.

Einbauen (eine Zeile, z. B. in setup_hook):
    await bot.load_extension("nexora_dashboard")

Umgebungsvariablen beim Bot:
    DASHBOARD_URL = https://nexora-sio.pages.dev/
    BOT_API_KEY   = derselbe Wert wie bei Cloudflare

Was die Datei macht:
 1. Heartbeat: meldet alle 30 Sek. "ich bin online" + Serverzahl -> Dashboard zeigt "Online"
 2. Schaltet Befehle pro Server ab, wenn du sie im Dashboard deaktivierst (ohne deine Befehle zu ändern)
 3. get_cfg(guild_id) liefert die Einstellungen eines Servers (siehe Beispiel ganz unten)
 4. command_enabled(cfg, modul, befehl) prüft von Hand, ob ein Befehl aktiv ist

Damit ist alles aus bot_example.py enthalten – du brauchst diese Datei nicht mehr.
"""
import os
import time

import aiohttp
from discord.ext import commands, tasks

URL = os.environ.get("DASHBOARD_URL", "").rstrip("/")
KEY = os.environ.get("BOT_API_KEY", "")
HEAD = {"Authorization": f"Bearer {KEY}"}
START = time.time()

# Befehlsname -> Modul (muss zu den Befehlen im Dashboard passen)
MODULES = {
    "eco": ["belohnung", "arbeiten", "kontostand", "einzahlen", "abheben", "geben", "rangliste"],
    "task": ["aufgaben", "aufgaben-abholen"],
    "shop": ["shop", "kaufen", "inventar", "benutzen", "shop-hinzufuegen"],
    "mod": ["kick", "ban", "unban", "mute", "unmute", "warn", "unwarn", "warnings", "clear"],
    "admin": ["einstellungen", "geld-hinzufuegen", "geld-entfernen"],
}
CMD_MODULE = {cmd: mod for mod, cmds in MODULES.items() for cmd in cmds}

_cache: dict = {}
_session: aiohttp.ClientSession | None = None


async def _http() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8))
    return _session


async def get_cfg(guild_id: int) -> dict:
    """Einstellungen eines Servers (30 Sek. zwischengespeichert). Bei Fehlern: letzte bekannte Werte."""
    hit = _cache.get(guild_id)
    if hit and time.time() - hit[0] < 30:
        return hit[1]
    try:
        s = await _http()
        async with s.get(f"{URL}/api/bot/settings/{guild_id}", headers=HEAD) as r:
            if r.status == 200:
                cfg = await r.json()
                _cache[guild_id] = (time.time(), cfg)
                return cfg
            print(f"[Nexora-Dashboard] Einstellungen: HTTP {r.status} (BOT_API_KEY richtig?)")
    except Exception as e:
        print(f"[Nexora-Dashboard] Einstellungen nicht erreichbar: {e}")
    return hit[1] if hit else {}


def command_enabled(cfg: dict, module: str, command: str) -> bool:
    """True, wenn Modul UND Befehl im Dashboard aktiv sind (ohne Daten: aktiv)."""
    return bool(cfg.get(f"{module}.on", True) and cfg.get(f"c.{command}", True))


class NexoraDashboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._ok = None
        self._orig_check = None

    async def cog_load(self):
        # Befehle pro Server sperren, wenn sie im Dashboard ausgeschaltet sind
        tree = self.bot.tree
        self._orig_check = tree.interaction_check

        async def check(interaction):
            if not await self._orig_check(interaction):
                return False
            cmd = interaction.command
            if cmd is None or interaction.guild_id is None:
                return True
            mod = CMD_MODULE.get(cmd.name)
            if mod is None:
                return True  # nicht verwaltete Befehle (z. B. /help) laufen immer
            cfg = await get_cfg(interaction.guild_id)
            if cfg.get(f"{mod}.on", True) and cfg.get(f"c.{cmd.name}", True):
                return True
            await interaction.response.send_message(
                "Dieser Befehl ist auf diesem Server deaktiviert.", ephemeral=True)
            return False

        tree.interaction_check = check
        self.heartbeat.start()

    async def cog_unload(self):
        self.heartbeat.cancel()
        if self._orig_check:
            self.bot.tree.interaction_check = self._orig_check
        if _session and not _session.closed:
            await _session.close()

    @tasks.loop(seconds=30)
    async def heartbeat(self):
        b = self.bot
        data = {
            "servers": len(b.guilds),
            "users": sum(g.member_count or 0 for g in b.guilds),
            "ping": round(b.latency * 1000) if b.latency == b.latency else 0,
            "commands": len(b.tree.get_commands()),
            "started": START,
        }
        try:
            s = await _http()
            async with s.post(f"{URL}/api/bot/heartbeat", json=data, headers=HEAD) as r:
                ok = r.status == 200
                if ok != self._ok:  # nur bei Änderung ausgeben
                    print("[Nexora-Dashboard] Herzschlag OK" if ok else
                          f"[Nexora-Dashboard] Herzschlag fehlgeschlagen: HTTP {r.status} "
                          f"(403 = BOT_API_KEY stimmt nicht)")
                self._ok = ok
        except Exception as e:
            if self._ok is not False:
                print(f"[Nexora-Dashboard] Dashboard nicht erreichbar: {e}")
            self._ok = False

    @heartbeat.before_loop
    async def _wait(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    if not URL or not KEY:
        print("[Nexora-Dashboard] DASHBOARD_URL oder BOT_API_KEY fehlt – Anbindung nicht gestartet.")
        return
    await bot.add_cog(NexoraDashboard(bot))


# ---------------------------------------------------------------------------------------------
# Beispiel in einem Slash-Befehl (aus bot_example.py übernommen).
# Das Sperren ausgeschalteter Befehle passiert schon automatisch (siehe oben); hier geht es
# um die Werte aus dem Dashboard und den Log-Kanal:
#
# from nexora_dashboard import get_cfg, command_enabled
#
# @bot.tree.command(name="belohnung")
# async def belohnung(inter: discord.Interaction):
#     cfg = await get_cfg(inter.guild_id)
#     if not cfg.get("logch"):
#         return await inter.response.send_message("Bitte erst /logkanal einrichten.", ephemeral=True)
#     if not command_enabled(cfg, "eco", "belohnung"):
#         return await inter.response.send_message("Befehl ist hier deaktiviert.", ephemeral=True)
#     betrag = cfg["daily"]      # Höhe der täglichen Belohnung aus dem Dashboard
#     ...
#
# Weitere Werte: cfg["streak"], cfg["cur"] (Währungsname), cfg["cursym"], cfg["workmin"], cfg["workmax"],
# cfg["workcd"], cfg["tcount"], cfg["treward"], cfg["tbonus"], cfg["warnmute"], cfg["logch"] (Kanal-ID)
