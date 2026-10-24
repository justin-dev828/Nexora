import os
import time
import logging

import aiohttp
from discord.ext import tasks

log = logging.getLogger(__name__)

DASHBOARD_URL = os.getenv(
    "DASHBOARD_URL",
    "https://nexora-sio.pages.dev"
).rstrip("/")

BOT_API_KEY = os.getenv("BOT_API_KEY")

if not BOT_API_KEY:
    raise RuntimeError("BOT_API_KEY fehlt in den Umgebungsvariablen.")

HEAD = {"Authorization": f"Bearer {BOT_API_KEY}"}
START = time.time()

_cache: dict[int, tuple[float, dict]] = {}
_session: aiohttp.ClientSession | None = None
bot = None


async def setup_dashboard(bot_instance):
    """Verbindet das Dashboard mit dem Discord-Bot."""
    global bot, _session

    bot = bot_instance

    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=5)
        )

    if not heartbeat.is_running():
        heartbeat.start()


async def close_dashboard():
    """Schließt die Dashboard-Verbindung."""
    if heartbeat.is_running():
        heartbeat.cancel()

    if _session and not _session.closed:
        await _session.close()


async def get_cfg(guild_id: int) -> dict:
    """Lädt Servereinstellungen mit 30 Sekunden Cache."""
    hit = _cache.get(guild_id)

    if hit and time.time() - hit[0] < 30:
        return hit[1]

    try:
        async with _session.get(
            f"{DASHBOARD_URL}/api/bot/settings/{guild_id}",
            headers=HEAD,
        ) as response:
            if response.status == 200:
                cfg = await response.json()
                _cache[guild_id] = (time.time(), cfg)
                return cfg

            log.warning(
                "Dashboard-Einstellungen: HTTP %s",
                response.status,
            )

    except (aiohttp.ClientError, TimeoutError) as exc:
        log.warning("Dashboard nicht erreichbar: %s", exc)

    return hit[1] if hit else {}


def command_enabled(
    cfg: dict,
    module: str,
    command: str,
) -> bool:
    """Prüft, ob Modul und Befehl aktiviert sind."""
    return (
        cfg.get(f"{module}.on", True)
        and cfg.get(f"c.{command}", True)
    )


@tasks.loop(seconds=30)
async def heartbeat():
    """Sendet Bot-Statistiken an das Dashboard."""
    if bot is None or _session is None or _session.closed:
        return

    data = {
        "servers": len(bot.guilds),
        "users": sum(g.member_count or 0 for g in bot.guilds),
        "ping": round(bot.latency * 1000),
        "commands": len(bot.tree.get_commands()),
        "started": START,
    }

    try:
        async with _session.post(
            f"{DASHBOARD_URL}/api/bot/heartbeat",
            json=data,
            headers=HEAD,
        ) as response:
            if response.status >= 400:
                log.warning(
                    "Heartbeat fehlgeschlagen: HTTP %s",
                    response.status,
                )

    except (aiohttp.ClientError, TimeoutError) as exc:
        log.warning("Heartbeat fehlgeschlagen: %s", exc)


@heartbeat.before_loop
async def before_heartbeat():
    await bot.wait_until_ready()
