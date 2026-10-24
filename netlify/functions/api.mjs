// Nexora Dashboard – Backend als Netlify Function (Login, Server, Einstellungen, Bot-Status)
import { getStore } from "@netlify/blobs";
import crypto from "node:crypto";

export const config = { path: ["/login", "/callback", "/logout", "/invite/*", "/api/*"] };

const API = "https://discord.com/api/v10";
const env = (k) => (globalThis.Netlify ? Netlify.env.get(k) : process.env[k]);
// Kick, Ban, Rollen, Nachrichten verwalten, Mitglieder timeouten, Senden, Embeds, Verlauf lesen
const BOT_PERMISSIONS = "1099780156422";

const MODULES = {
  eco: ["belohnung", "arbeiten", "kontostand", "einzahlen", "abheben", "geben", "rangliste"],
  task: ["aufgaben", "aufgaben-abholen"],
  shop: ["shop", "kaufen", "inventar", "benutzen", "shop-hinzufuegen"],
  mod: ["kick", "ban", "unban", "mute", "unmute", "warn", "unwarn", "warnings", "clear"],
  admin: ["einstellungen", "geld-hinzufuegen", "geld-entfernen"],
  log: ["logkanal"],
};
const DEFAULTS = {
  logch: "", cur: "Coins", cursym: "🪙",
  daily: 100, streak: 10, workmin: 20, workmax: 120, workcd: 30,
  tcount: 3, treward: 50, tbonus: 100,
  tmsg: true, tvoice: true, treact: true, tshop: true,
  confirm: true, roles: true, items: true,
  modlog: true, warnmute: 3,
};
for (const [m, cmds] of Object.entries(MODULES)) {
  if (m !== "log") DEFAULTS[`${m}.on`] = true;
  for (const c of cmds) DEFAULTS[`c.${c}`] = true;
}

// ---------- Hilfsfunktionen ----------
let _key;
const key = () => (_key ??= crypto.scryptSync(env("SESSION_SECRET") || "", "nexora-salt", 32));
const b64 = (b) => Buffer.from(b).toString("base64url");
function seal(obj) {
  const iv = crypto.randomBytes(12);
  const c = crypto.createCipheriv("aes-256-gcm", key(), iv);
  const enc = Buffer.concat([c.update(JSON.stringify(obj), "utf8"), c.final()]);
  return b64(Buffer.concat([iv, c.getAuthTag(), enc]));
}
function unseal(t) {
  try {
    const b = Buffer.from(t, "base64url");
    const d = crypto.createDecipheriv("aes-256-gcm", key(), b.subarray(0, 12));
    d.setAuthTag(b.subarray(12, 28));
    return JSON.parse(Buffer.concat([d.update(b.subarray(28)), d.final()]).toString("utf8"));
  } catch { return null; }
}
const cookies = (req) => Object.fromEntries((req.headers.get("cookie") || "").split(/;\s*/).filter(Boolean)
  .map((c) => { const i = c.indexOf("="); return [c.slice(0, i), c.slice(i + 1)]; }));
const ck = (n, v, age) => `${n}=${v}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${age}`;
const json = (d, s = 200, extra = []) => {
  const h = new Headers({ "content-type": "application/json", "cache-control": "no-store" });
  extra.forEach((x) => h.append("set-cookie", x));
  return new Response(JSON.stringify(d), { status: s, headers: h });
};
const go = (loc, extra = []) => {
  const h = new Headers({ location: loc });
  extra.forEach((x) => h.append("set-cookie", x));
  return new Response(null, { status: 302, headers: h });
};
const session = (req) => {
  const t = cookies(req).nx_s; const s = t && unseal(t);
  return s && s.exp > Date.now() ? s : null;
};
const dc = (path, auth, init = {}) =>
  fetch(API + path, { ...init, headers: { authorization: auth, ...(init.headers || {}) } });
const BOT = () => `Bot ${env("BOT_TOKEN")}`;

async function userGuilds(s) {
  const r = await dc("/users/@me/guilds", `Bearer ${s.token}`);
  if (r.status === 401) return null;
  if (!r.ok) throw new Error("discord");
  return r.json();
}
const canManage = (g) => {
  const p = BigInt(g.permissions);
  return !!g.owner || (p & 0x8n) !== 0n || (p & 0x20n) !== 0n;
};
async function botIds() {
  const r = await dc("/users/@me/guilds?limit=200", BOT());
  if (!r.ok) throw new Error("bot");
  return new Set((await r.json()).map((g) => g.id));
}
async function access(s, id) {
  const gs = await userGuilds(s);
  if (!gs) return { err: json({ detail: "Sitzung abgelaufen" }, 401, [ck("nx_s", "", 0)]) };
  const g = gs.find((x) => x.id === id);
  if (!g || !canManage(g)) return { err: json({ detail: "Keine Rechte auf diesem Server" }, 403) };
  if (!(await botIds()).has(id)) return { err: json({ detail: "Nexora ist nicht auf diesem Server" }, 404) };
  return {};
}
function clean(body) {
  const o = {};
  for (const [k, d] of Object.entries(DEFAULTS)) {
    if (!(k in body)) continue;
    const v = body[k];
    if (typeof d === "boolean") { if (typeof v === "boolean") o[k] = v; }
    else if (typeof d === "number") {
      const n = parseInt(v, 10);
      if (Number.isFinite(n)) o[k] = Math.max(0, Math.min(n, 1000000));
    } else {
      const t = String(v).slice(0, 50);
      if (k === "logch" && t && !/^\d+$/.test(t)) continue;
      o[k] = t;
    }
  }
  return o;
}
const load = async (id) => ({ ...DEFAULTS, ...((await getStore("settings").get(id, { type: "json" })) || {}) });
const fmt = (sec) => {
  sec = Math.max(0, Math.floor(sec));
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
  return d ? `${d} Tg ${h} Std` : h ? `${h} Std ${m} Min` : `${m} Min`;
};
const isBot = (req) => {
  const k = env("BOT_API_KEY"); if (!k) return false;
  const a = Buffer.from(req.headers.get("authorization") || ""), e = Buffer.from(`Bearer ${k}`);
  return a.length === e.length && crypto.timingSafeEqual(a, e);
};

// ---------- Routen ----------
export default async (req) => {
  const url = new URL(req.url), p = url.pathname, m = req.method;
  try {
    // Login mit Discord
    if (p === "/login") {
      const state = crypto.randomBytes(16).toString("hex");
      const q = new URLSearchParams({
        client_id: env("CLIENT_ID"), redirect_uri: url.origin + "/callback",
        response_type: "code", scope: "identify guilds", state,
      });
      return go(`https://discord.com/oauth2/authorize?${q}`, [ck("nx_state", state, 600)]);
    }
    if (p === "/callback") {
      const code = url.searchParams.get("code"), state = url.searchParams.get("state");
      if (!code || state !== cookies(req).nx_state) return go("/", [ck("nx_state", "", 0)]);
      const tr = await fetch(`${API}/oauth2/token`, {
        method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          client_id: env("CLIENT_ID"), client_secret: env("CLIENT_SECRET"),
          grant_type: "authorization_code", code, redirect_uri: url.origin + "/callback",
        }),
      });
      if (!tr.ok) return go("/", [ck("nx_state", "", 0)]);
      const { access_token } = await tr.json();
      const u = await (await dc("/users/@me", `Bearer ${access_token}`)).json();
      const s = { uid: u.id, name: u.global_name || u.username, token: access_token, exp: Date.now() + 7 * 864e5 };
      return go("/", [ck("nx_s", seal(s), 7 * 86400), ck("nx_state", "", 0)]);
    }
    if (p === "/logout") return go("/", [ck("nx_s", "", 0)]);

    // Öffentlich: Bot-Status für den Tracker
    if (p === "/api/stats") {
      const d = (await getStore("stats").get("bot", { type: "json" })) || {};
      const online = Date.now() - (d.heartbeat || 0) < 90000;
      let servers = d.servers || 0;
      if (!servers) {
        try {
          const r = await dc("/applications/@me", BOT());
          if (r.ok) servers = (await r.json()).approximate_guild_count || 0;
        } catch {}
      }
      return json({
        online, servers, users: d.users || 0, ping: d.ping || 0, commands: d.commands || 29,
        uptime: online && d.started ? fmt(Date.now() / 1000 - d.started) : "–",
      });
    }

    // Nur für deinen Bot (geheimer Schlüssel BOT_API_KEY)
    if (p === "/api/bot/heartbeat" && m === "POST") {
      if (!isBot(req)) return json({ detail: "Nicht erlaubt" }, 403);
      const b = await req.json();
      const n = (x) => Number(x) || 0;
      await getStore("stats").setJSON("bot", {
        heartbeat: Date.now(), servers: n(b.servers), users: n(b.users),
        ping: n(b.ping), commands: n(b.commands), started: n(b.started),
      });
      return json({ ok: true });
    }
    const bs = p.match(/^\/api\/bot\/settings\/(\d+)$/);
    if (bs) {
      if (!isBot(req)) return json({ detail: "Nicht erlaubt" }, 403);
      return json(await load(bs[1]));
    }

    // Ab hier: nur eingeloggte Nutzer
    const s = session(req);
    if (!s) return json({ detail: "Nicht eingeloggt" }, 401);
    if (p === "/api/me") return json({ id: s.uid, name: s.name });

    if (p === "/api/guilds") {
      const gs = await userGuilds(s);
      if (!gs) return json({ detail: "Sitzung abgelaufen" }, 401, [ck("nx_s", "", 0)]);
      const bots = await botIds();
      return json(gs.filter(canManage).map((g) => ({ id: g.id, name: g.name, icon: g.icon, bot: bots.has(g.id) })));
    }
    const inv = p.match(/^\/invite\/(\d+)$/);
    if (inv) {
      const q = new URLSearchParams({
        client_id: env("CLIENT_ID"), scope: "bot applications.commands", permissions: BOT_PERMISSIONS,
        guild_id: inv[1], disable_guild_select: "true",
      });
      return go(`https://discord.com/oauth2/authorize?${q}`);
    }
    const gm = p.match(/^\/api\/guilds\/(\d+)\/(settings|channels)$/);
    if (gm) {
      const [, id, what] = gm;
      const a = await access(s, id); if (a.err) return a.err;
      if (what === "channels") {
        const r = await dc(`/guilds/${id}/channels`, BOT());
        if (!r.ok) return json([]);
        return json((await r.json()).filter((c) => c.type === 0)
          .sort((x, y) => (x.position || 0) - (y.position || 0)).map((c) => ({ id: c.id, name: c.name })));
      }
      if (m === "GET") return json(await load(id));
      if (m === "PUT") {
        const body = await req.json();
        const data = { ...(await load(id)), ...clean(body && typeof body === "object" ? body : {}) };
        if (data.workmin > data.workmax) return json({ detail: "Arbeiten: Minimum darf nicht größer als Maximum sein" }, 400);
        await getStore("settings").setJSON(id, data);
        return json(data);
      }
    }
    return json({ detail: "Nicht gefunden" }, 404);
  } catch (e) {
    console.error(e);
    return json({ detail: "Serverfehler" }, 500);
  }
};
