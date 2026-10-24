"""Nexora Dashboard – Backend (FastAPI). Start: uvicorn main:app --reload"""
import json
import os
import time
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

load_dotenv()
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]
REDIRECT_URI = os.environ["REDIRECT_URI"]          # z. B. http://localhost:8000/callback
BOT_TOKEN = os.environ["BOT_TOKEN"]
SESSION_SECRET = os.environ["SESSION_SECRET"]
HTTPS_ONLY = os.getenv("HTTPS_ONLY", "false").lower() == "true"   # online auf true setzen
DB = os.getenv("DB_PATH", "nexora.db")                             # gleiche DB wie dein Bot
BASE = Path(__file__).parent
API = "https://discord.com/api/v10"
MANAGE_GUILD, ADMINISTRATOR = 0x20, 0x8
# Kick, Ban, Rollen, Nachrichten verwalten, Mitglieder timeouten, Senden, Embeds, Verlauf lesen
BOT_PERMISSIONS = 1099780156422

# Befehle pro Modul (muss zu den Modulen im Frontend passen)
MODULES = {
    "eco": ["belohnung", "arbeiten", "kontostand", "einzahlen", "abheben", "geben", "rangliste"],
    "task": ["aufgaben", "aufgaben-abholen"],
    "shop": ["shop", "kaufen", "inventar", "benutzen", "shop-hinzufuegen"],
    "mod": ["kick", "ban", "unban", "mute", "unmute", "warn", "unwarn", "warnings", "clear"],
    "admin": ["einstellungen", "geld-hinzufuegen", "geld-entfernen"],
    "log": ["logkanal"],
}
# Standardwerte = erlaubte Schlüssel. Typ des Werts bestimmt die Validierung.
DEFAULTS = {
    "logch": "", "cur": "Coins", "cursym": "🪙",
    "daily": 100, "streak": 10, "workmin": 20, "workmax": 120, "workcd": 30,
    "tcount": 3, "treward": 50, "tbonus": 100,
    "tmsg": True, "tvoice": True, "treact": True, "tshop": True,
    "confirm": True, "roles": True, "items": True,
    "modlog": True, "warnmute": 3,
}
for _m, _cmds in MODULES.items():
    if _m != "log":
        DEFAULTS[f"{_m}.on"] = True
    for _c in _cmds:
        DEFAULTS[f"c.{_c}"] = True


@asynccontextmanager
async def lifespan(app):
    async with aiosqlite.connect(DB) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS guild_settings "
                         "(guild_id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        await db.commit()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, https_only=HTTPS_ONLY,
                   same_site="lax", max_age=7 * 24 * 3600)

_cache: dict = {}


async def cached(key, ttl, fetch):
    """Kleiner Cache, damit wir Discords Rate-Limits nicht reißen."""
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    data = await fetch()
    _cache[key] = (time.time(), data)
    return data


# ---------------- Seite ----------------
@app.get("/")
async def index():
    return FileResponse(BASE / "static" / "index.html")


# ---------------- Login ----------------
@app.get("/login")
async def login(request: Request):
    state = os.urandom(16).hex()
    request.session["state"] = state
    q = urllib.parse.urlencode({"client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI,
                                "response_type": "code", "scope": "identify guilds",
                                "state": state})
    return RedirectResponse(f"https://discord.com/oauth2/authorize?{q}")


@app.get("/callback")
async def callback(request: Request, code: str = "", state: str = ""):
    if not code or state != request.session.pop("state", None):
        raise HTTPException(400, "Login fehlgeschlagen (State ungültig)")
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{API}/oauth2/token", data={
            "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
            "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI})
        if r.status_code != 200:
            raise HTTPException(400, "Token-Abruf fehlgeschlagen")
        token = r.json()["access_token"]
        u = (await c.get(f"{API}/users/@me", headers={"Authorization": f"Bearer {token}"})).json()
    request.session["token"] = token
    request.session["user"] = {"id": u["id"], "name": u.get("global_name") or u["username"]}
    return RedirectResponse("/")


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")


def current_user(request: Request):
    if "token" not in request.session:
        raise HTTPException(401, "Nicht eingeloggt")
    return request.session


@app.get("/api/me")
async def me(s=Depends(current_user)):
    return s["user"]


# ---------------- Server ----------------
async def user_guilds(s):
    async def fetch():
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{API}/users/@me/guilds",
                            headers={"Authorization": f"Bearer {s['token']}"})
        if r.status_code == 401:
            s.clear()
            raise HTTPException(401, "Sitzung abgelaufen")
        r.raise_for_status()
        return r.json()
    return await cached(("u", s["token"]), 30, fetch)


async def bot_guild_ids():
    async def fetch():
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{API}/users/@me/guilds", params={"limit": 200},
                            headers={"Authorization": f"Bot {BOT_TOKEN}"})
        r.raise_for_status()
        return {g["id"] for g in r.json()}
    return await cached("bot", 30, fetch)


def can_manage(g):
    p = int(g["permissions"])
    return bool(g.get("owner") or p & ADMINISTRATOR or p & MANAGE_GUILD)


@app.get("/api/guilds")
async def guilds(s=Depends(current_user)):
    bots = await bot_guild_ids()
    return [{"id": g["id"], "name": g["name"], "icon": g.get("icon"), "bot": g["id"] in bots}
            for g in await user_guilds(s) if can_manage(g)]


async def guild_access(guild_id: str, s=Depends(current_user)):
    """Wird bei JEDEM Zugriff geprüft – dem Frontend wird nie vertraut."""
    g = next((x for x in await user_guilds(s) if x["id"] == guild_id), None)
    if not g or not can_manage(g):
        raise HTTPException(403, "Keine Rechte auf diesem Server")
    if guild_id not in await bot_guild_ids():
        raise HTTPException(404, "Nexora ist nicht auf diesem Server")
    return guild_id


@app.get("/invite/{guild_id}")
async def invite(guild_id: str, s=Depends(current_user)):
    if not guild_id.isdigit():
        raise HTTPException(400, "Ungültige Server-ID")
    q = urllib.parse.urlencode({"client_id": CLIENT_ID, "scope": "bot applications.commands",
                                "permissions": BOT_PERMISSIONS, "guild_id": guild_id,
                                "disable_guild_select": "true"})
    return RedirectResponse(f"https://discord.com/oauth2/authorize?{q}")


@app.get("/api/guilds/{guild_id}/channels")
async def channels(guild_id: str = Depends(guild_access)):
    async def fetch():
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{API}/guilds/{guild_id}/channels",
                            headers={"Authorization": f"Bot {BOT_TOKEN}"})
        r.raise_for_status()
        return [{"id": x["id"], "name": x["name"]}
                for x in sorted(r.json(), key=lambda x: x.get("position", 0)) if x["type"] == 0]
    return await cached(("ch", guild_id), 30, fetch)


# ---------------- Einstellungen ----------------
async def load(guild_id):
    async with aiosqlite.connect(DB) as db:
        row = await (await db.execute("SELECT data FROM guild_settings WHERE guild_id=?",
                                      (guild_id,))).fetchone()
    return {**DEFAULTS, **(json.loads(row[0]) if row else {})}


def clean(body: dict) -> dict:
    out = {}
    for k, d in DEFAULTS.items():
        if k not in body:
            continue
        v = body[k]
        if isinstance(d, bool):
            if isinstance(v, bool):
                out[k] = v
        elif isinstance(d, int):
            try:
                out[k] = max(0, min(int(v), 1_000_000))
            except (TypeError, ValueError):
                pass
        else:
            v = str(v)[:50]
            if k == "logch" and v and not v.isdigit():
                continue
            out[k] = v
    return out


@app.get("/api/guilds/{guild_id}/settings")
async def get_settings(guild_id: str = Depends(guild_access)):
    return await load(guild_id)


@app.put("/api/guilds/{guild_id}/settings")
async def put_settings(body: dict, guild_id: str = Depends(guild_access)):
    data = {**await load(guild_id), **clean(body)}
    if data["workmin"] > data["workmax"]:
        raise HTTPException(400, "Arbeiten: Minimum darf nicht größer als Maximum sein")
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT INTO guild_settings VALUES (?, ?) "
                         "ON CONFLICT(guild_id) DO UPDATE SET data=excluded.data",
                         (guild_id, json.dumps(data)))
        await db.commit()
    return data
