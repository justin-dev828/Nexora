"""Nexora-Dashboard-Anbindung (eigene Datei, funktioniert mit discord.Client UND commands.Bot).

Diese Datei liegt neben bot.py und hängt nicht von bot.py ab.

EINBAU (nur 2 Zeilen in bot.py):
    oben bei den Imports:                       import nexora_dashboard as dashboard
    direkt vor "if not TOKEN:" (ganz unten):    dashboard.installieren(globals())

UMGEBUNGSVARIABLEN (.env bzw. bot-hosting.net):
    DASHBOARD_URL = https://nexora-sio.pages.dev
    BOT_API_KEY   = derselbe Wert wie bei Cloudflare

WAS DIE DATEI MACHT
 1. Herzschlag alle 30 Sek.  -> Dashboard zeigt "Online"
 2. Web -> Discord: im Dashboard ausgeschaltete Befehle/Module sind auf dem Server gesperrt
 3. Web -> Datenbank: geänderte Werte (Belohnung, Währung, Arbeiten, Log-Kanal) landen in der Bot-Datenbank
 4. Discord -> Web: spiegeln() schickt die Bot-Einstellungen ans Dashboard
"""
import asyncio
import inspect
import os
import time
from typing import Callable, Optional

import aiohttp
import discord
from discord.ext import tasks

START = time.time()

# Befehlsname -> Modul (muss zu den Befehlen im Dashboard passen)
MODULES = {
    "eco": ["belohnung", "arbeiten", "kontostand", "einzahlen", "abheben", "geben", "rangliste",
            "woche", "profil", "erfolge", "casino", "stehlen"],
    "task": ["aufgaben", "aufgaben-abholen", "serverquest", "spenden"],
    "shop": ["shop", "kaufen", "inventar", "benutzen", "verkaufen", "schenken",
             "shop-hinzufuegen", "shop-bearbeiten", "shop-entfernen"],
    "mod": ["kick", "ban", "unban", "mute", "unmute", "warn", "unwarn", "warnings", "clear"],
    "admin": ["einstellungen", "geld-hinzufuegen", "geld-entfernen"],
}
CMD_MODULE = {cmd: mod for mod, cmds in MODULES.items() for cmd in cmds}

# Dashboard-Schlüssel -> Spalte in der Bot-Datenbank (Name, Minimum, Maximum)
ZAHLEN = {
    "daily": ("belohnung_basis", 1, 1_000_000),
    "streak": ("belohnung_streak_bonus", 0, 100_000),  # falls "streak" im Dashboard etwas anderes heißt: Zeile löschen
    "workmin": ("arbeiten_min", 1, 1_000_000),
    "workmax": ("arbeiten_max", 1, 1_000_000),
    "workcd": ("arbeiten_cooldown_min", 1, 1440),
}
TEXTE = {
    "cur": ("waehrung_name", 30),
    "cursym": ("waehrung_emoji", 60),
}

# ---------------------------------------------------------------------------------------------
# Zustand
# ---------------------------------------------------------------------------------------------
URL = ""
KEY = ""
_head: dict = {}
_bot: Optional[discord.Client] = None
_db = None
_log_cb: Optional[Callable[[int, int], None]] = None

_cache: dict = {}       # guild_id -> Einstellungen
_stamp: dict = {}       # guild_id -> Zeitpunkt der letzten Aktualisierung
_defaults: dict = {}    # Standardwerte aus dem Dashboard
_callbacks: list = []   # Funktionen für on_change
_session = None
_loaded = False         # wurde schon einmal alles geladen?
_last_write = 0.0       # Zeitpunkt der letzten eigenen Änderung
_last_warn = ""
_herz_ok = None
_orig_aendern = None  # unveränderte db.einstellungen_aendern (verhindert Rückspiegelung)
_tasks: set = set()


def aktiv() -> bool:
    return bool(URL and KEY)


def _warn(msg: str) -> None:
    """Gleiche Meldung nur einmal ausgeben, damit die Konsole nicht zugemüllt wird."""
    global _last_warn
    if msg != _last_warn:
        print(f"[Nexora-Dashboard] {msg}")
        _last_warn = msg


async def _http():
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8))
    return _session


async def _req(method: str, path: str, **kw):
    """Anfrage an das Dashboard. Gibt die Antwort (JSON) zurück oder None bei Fehlern."""
    try:
        s = await _http()
        async with s.request(method, URL + path, headers=_head, **kw) as r:
            if r.status == 200:
                return await r.json()
            _warn(f"{method} {path}: HTTP {r.status}"
                  + (" (BOT_API_KEY stimmt nicht oder Zugriff blockiert)" if r.status == 403 else ""))
    except Exception as e:
        _warn(f"Dashboard nicht erreichbar: {e}")
    return None


# ---------------------------------------------------------------------------------------------
# Einstellungen lesen / schreiben / Änderungen melden
# ---------------------------------------------------------------------------------------------
def on_change(func):
    """Decorator: func(guild_id, changes, cfg) läuft, wenn sich im Dashboard etwas ändert."""
    _callbacks.append(func)
    return func


async def _notify(guild_id: int, changes: dict, cfg: dict) -> None:
    for cb in _callbacks:
        try:
            res = cb(guild_id, changes, cfg)
            if inspect.isawaitable(res):
                await res
        except Exception as e:
            print(f"[Nexora-Dashboard] Fehler in on_change ({getattr(cb, '__name__', cb)}): {e!r}")


async def _apply(guild_id: int, new: dict, notify: bool = True) -> None:
    old = _cache.get(guild_id, _defaults)
    _cache[guild_id] = new
    _stamp[guild_id] = time.time()
    if notify:
        changes = {k: v for k, v in new.items() if old.get(k) != v}
        if changes:
            await _notify(guild_id, changes, new)


def cfg_cached(guild_id) -> dict:
    """Einstellungen aus dem Zwischenspeicher, ohne Netzwerk (Discord erlaubt nur 3 Sek. Antwortzeit)."""
    return _cache.get(int(guild_id), _defaults)


async def get_cfg(guild_id, fresh: bool = False) -> dict:
    gid = int(guild_id)
    if not fresh and gid in _cache and time.time() - _stamp.get(gid, 0) < 45:
        return _cache[gid]
    cfg = await _req("GET", f"/api/bot/settings/{gid}")
    if cfg is not None:
        await _apply(gid, cfg, notify=gid in _cache)
        return cfg
    return _cache.get(gid, {})  # Dashboard nicht erreichbar -> letzte bekannte Werte


async def update_cfg(guild_id, changes: dict) -> dict:
    """Schreibt Änderungen ins Dashboard, z. B. update_cfg(gid, {"daily": 150})."""
    global _last_write
    gid = int(guild_id)
    _last_write = time.time()
    cfg = await _req("PUT", f"/api/bot/settings/{gid}", json=changes)
    if cfg is None:
        raise RuntimeError("Das Dashboard hat die Änderung nicht angenommen (Details in der Konsole).")
    _cache[gid] = cfg
    _stamp[gid] = time.time()
    return cfg


def command_enabled(cfg: dict, module: str, command: str) -> bool:
    """True, wenn Modul UND Befehl im Dashboard aktiv sind (ohne Daten: aktiv)."""
    return bool(cfg.get(f"{module}.on", True) and cfg.get(f"c.{command}", True))


# ---------------------------------------------------------------------------------------------
# Befehle sperren (aus bot.py in der Zugriffsprüfung aufrufen)
# ---------------------------------------------------------------------------------------------
async def befehl_erlaubt(interaction: discord.Interaction, befehl: Optional[str] = None) -> bool:
    """True = Befehl darf laufen. False = im Dashboard ausgeschaltet (die Antwort ist schon gesendet)."""
    if not aktiv() or interaction.guild_id is None:
        return True
    if befehl is None:
        cmd = interaction.command
        if cmd is None:
            return True
        befehl = (cmd.root_parent or cmd).name
    modul = CMD_MODULE.get(befehl)
    if modul is None:
        return True  # nicht verwaltete Befehle (z. B. /help) laufen immer
    if command_enabled(cfg_cached(interaction.guild_id), modul, befehl):
        return True
    if not interaction.response.is_done():
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🚫 Befehl deaktiviert",
                description="Dieser Befehl ist auf diesem Server im Dashboard ausgeschaltet.",
                color=discord.Color.orange(),
            ),
            ephemeral=True,
        )
    return False


# ---------------------------------------------------------------------------------------------
# Web -> Datenbank
# ---------------------------------------------------------------------------------------------
@on_change
async def _uebernehmen(guild_id: int, changes: dict, cfg: dict) -> None:
    if _db is None:
        return
    felder = {}
    for key, (spalte, lo, hi) in ZAHLEN.items():
        if key in changes:
            try:
                felder[spalte] = max(lo, min(hi, int(float(changes[key]))))
            except (TypeError, ValueError):
                pass
    for key, (spalte, maxlaenge) in TEXTE.items():
        text = str(changes.get(key, "")).strip()
        if text:
            felder[spalte] = discord.utils.escape_mentions(text)[:maxlaenge]
    logch = str(changes.get("logch", "")).strip()
    if logch.isdigit():
        felder["log_kanal_id"] = int(logch)

    aktuell = await _db.einstellungen(guild_id)
    kleinster = felder.get("arbeiten_min", aktuell["arbeiten_min"])
    groesster = felder.get("arbeiten_max", aktuell["arbeiten_max"])
    if kleinster > groesster:  # ungültige Kombination nicht übernehmen
        felder.pop("arbeiten_min", None)
        felder.pop("arbeiten_max", None)
    if felder:
        await (_orig_aendern or _db.einstellungen_aendern)(guild_id, **felder)
        if "log_kanal_id" in felder and _log_cb is not None:
            _log_cb(guild_id, felder["log_kanal_id"])


# ---------------------------------------------------------------------------------------------
# Discord -> Web
# ---------------------------------------------------------------------------------------------
async def spiegeln(guild_id: int, s: Optional[dict] = None) -> None:
    """Schickt die Economy-Einstellungen eines Servers ans Dashboard. Fehler stören den Bot nie."""
    if not aktiv() or _db is None:
        return
    try:
        s = s or await _db.einstellungen(guild_id)
        daten = {
            "daily": s["belohnung_basis"],
            "streak": s["belohnung_streak_bonus"],
            "workmin": s["arbeiten_min"],
            "workmax": s["arbeiten_max"],
            "workcd": s["arbeiten_cooldown_min"],
            "cur": s["waehrung_name"],
            "cursym": s["waehrung_emoji"],
        }
        if s["log_kanal_id"]:
            daten["logch"] = str(s["log_kanal_id"])
        await update_cfg(guild_id, daten)
    except Exception as fehler:
        print(f"[Nexora-Dashboard] Änderung konnte nicht ans Dashboard gesendet werden: {fehler!r}")


# ---------------------------------------------------------------------------------------------
# Hintergrund-Schleifen
# ---------------------------------------------------------------------------------------------
@tasks.loop(seconds=30)
async def _herzschlag():
    global _herz_ok
    b = _bot
    daten = {
        "servers": len(b.guilds),
        "users": sum(g.member_count or 0 for g in b.guilds),
        "ping": round(b.latency * 1000) if b.latency == b.latency else 0,
        "commands": len(b.tree.get_commands()),
        "started": START,
    }
    ok = await _req("POST", "/api/bot/heartbeat", json=daten) is not None
    if ok != _herz_ok:  # nur bei Änderung ausgeben
        print("[Nexora-Dashboard] Herzschlag OK" if ok else
              "[Nexora-Dashboard] Herzschlag fehlgeschlagen (Grund steht oben)")
    _herz_ok = ok


@_herzschlag.before_loop
async def _warten_herzschlag():
    await _bot.wait_until_ready()


_sync_gemeldet = False


@tasks.loop(seconds=60)
async def _sync():
    """Holt die Einstellungen jedes Servers einzeln (/api/bot/settings/<id>) und meldet Änderungen.

    Eine Sammel-Route (/api/bot/settings) gibt es im Dashboard-Backend nicht, deshalb pro Server.
    60 Sek. Takt, damit das Anfrage-Limit von Cloudflare Pages nicht ausgereizt wird.
    """
    for g in list(_bot.guilds):
        t0 = time.time()
        cfg = await _req("GET", f"/api/bot/settings/{g.id}")
        if cfg is None:
            return  # Dashboard nicht erreichbar: nicht jeden Server einzeln versuchen
        if t0 >= _last_write:  # veraltete Antwort nicht über eigene Änderung legen
            # Beim ersten Laden eines Servers nichts melden (sonst würden Dashboard-Standardwerte die Datenbank überschreiben)
            await _apply(g.id, cfg, notify=g.id in _cache)
        await asyncio.sleep(0.25)
    global _sync_gemeldet
    if not _sync_gemeldet:
        _sync_gemeldet = True
        print(f"[Nexora-Dashboard] Einstellungen von {len(_cache)} Server(n) geladen – Befehls-Sperren sind aktiv")


@_sync.before_loop
async def _warten_sync():
    await _bot.wait_until_ready()


# ---------------------------------------------------------------------------------------------
# Start / Ende (aus bot.py aufrufen)
# ---------------------------------------------------------------------------------------------
def starten(bot: discord.Client, db, log_kanal_setzen: Optional[Callable[[int, int], None]] = None) -> None:
    """Startet die Anbindung. Aus setup_hook aufrufen.

    db                 = deine Database-Instanz
    log_kanal_setzen   = optional: Funktion (guild_id, kanal_id), die den Log-Kanal-Zwischenspeicher aktualisiert
    """
    global URL, KEY, _head, _bot, _db, _log_cb
    URL = os.environ.get("DASHBOARD_URL", "").strip().rstrip("/")
    KEY = os.environ.get("BOT_API_KEY", "").strip()
    if not aktiv():
        print("[Nexora-Dashboard] DASHBOARD_URL oder BOT_API_KEY fehlt – Anbindung nicht gestartet.")
        return
    _head = {
        "Authorization": f"Bearer {KEY}",
        "User-Agent": f"NexoraBot/1.0 (+{URL})",  # ohne User-Agent blockt Cloudflare manchmal mit 403
    }
    _bot, _db, _log_cb = bot, db, log_kanal_setzen
    if not _herzschlag.is_running():
        _herzschlag.start()
    if not _sync.is_running():
        _sync.start()


async def beenden() -> None:
    _herzschlag.cancel()
    _sync.cancel()
    if _session is not None and not _session.closed:
        await _session.close()


# ---------------------------------------------------------------------------------------------
# Alles auf einmal einbauen (eine Zeile in bot.py)
# ---------------------------------------------------------------------------------------------
SPIEGEL_FELDER = {spalte for spalte, *_ in ZAHLEN.values()} | {spalte for spalte, _ in TEXTE.values()} | {"log_kanal_id"}


def _besitzer_ausnahme() -> bool:
    """Standard: auch der Bot-Besitzer unterliegt den Dashboard-Sperren (DASHBOARD_BESITZER_AUSNAHME=1 = Besitzer ausgenommen)."""
    return os.environ.get("DASHBOARD_BESITZER_AUSNAHME", "0").strip() == "1"


def installieren(g: dict) -> None:
    """Baut die Anbindung in den Bot ein. In bot.py direkt vor `if not TOKEN:` aufrufen:

        dashboard.installieren(globals())

    Das erledigt automatisch:
      - Befehle sperren (Slash-Befehle und Panel-Buttons)
      - Start und Ende des Herzschlags
      - Einstellungen (/einstellungen aendern, /logkanal) ans Dashboard spiegeln
    """
    global _orig_aendern
    bot, db = g["bot"], g["db"]

    # 1. Slash-Befehle: Dashboard-Sperre nach der normalen Zugriffsprüfung
    orig_pruefe = g["besitzer_pruefe_zugriff"]

    async def pruefe(interaction, befehl=None):
        if not await orig_pruefe(interaction):
            return False
        if _besitzer_ausnahme() and g["besitzer_ist_besitzer"](interaction.user.id):
            return True
        return await befehl_erlaubt(interaction, befehl)

    g["besitzer_pruefe_zugriff"] = pruefe

    # 2. Panel-Buttons: kennen den Befehl nur über den Button-Namen
    orig_knopf = g["_knopf"]

    async def knopf(interaction, befehl):
        if not (_besitzer_ausnahme() and g["besitzer_ist_besitzer"](interaction.user.id)):
            if not await befehl_erlaubt(interaction, befehl):
                return
        await orig_knopf(interaction, befehl)

    g["_knopf"] = knopf

    # 3. Start und Ende
    orig_setup = bot.setup_hook
    orig_close = bot.close
    log_cache = g.get("_cache")

    async def setup_hook():
        await orig_setup()
        starten(bot, db, (lambda gid, kid: log_cache.__setitem__(gid, kid)) if isinstance(log_cache, dict) else None)

    async def close():
        await beenden()
        await orig_close()

    bot.setup_hook = setup_hook
    bot.close = close

    # 4. Discord -> Web: jede Änderung der Einstellungen automatisch spiegeln (im Hintergrund)
    _orig_aendern = db.einstellungen_aendern

    async def aendern(gid, **felder):
        s = await _orig_aendern(gid, **felder)
        if aktiv() and any(k in SPIEGEL_FELDER and v is not None for k, v in felder.items()):
            t = asyncio.create_task(spiegeln(gid, s))
            _tasks.add(t)
            t.add_done_callback(_tasks.discard)
        return s

    db.einstellungen_aendern = aendern
