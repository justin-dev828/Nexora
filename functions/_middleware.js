// Nexora Dashboard – Backend für Cloudflare Pages (Login, Server, Einstellungen, Bot-Status)
// Speicher: D1-Datenbank mit dem Binding-Namen "DB"

const API = "https://discord.com/api/v10";
const UA = "DiscordBot (https://nexora-bot, 1.0)";
// Kick, Ban, Rollen, Nachrichten verwalten, Mitglieder timeouten, Senden, Embeds, Verlauf lesen
const BOT_PERMISSIONS = "1099780156422";
const REQUIRED = ["CLIENT_ID", "CLIENT_SECRET", "BOT_TOKEN", "SESSION_SECRET", "BOT_API_KEY"];

const MODULES = {
  eco: ["belohnung", "arbeiten", "kontostand", "einzahlen", "abheben", "geben", "rangliste", "woche", "profil", "erfolge"],
  task: ["aufgaben", "aufgaben-abholen", "serverquest", "spenden"],
  shop: ["shop", "kaufen", "inventar", "benutzen", "verkaufen", "schenken", "shop-hinzufuegen", "shop-bearbeiten", "shop-entfernen"],
  casino: ["casino", "stehlen"],
  panel: ["panel"],
  info: ["ping", "wuerfeln", "serverinfo", "nutzerinfo", "avatar"],
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
  casino_on: true, casino_max: 1000, steal_on: false, interest: 1, sellpct: 50, qon: true, sqon: true,
};
for (const [m, cmds] of Object.entries(MODULES)) {
  if (m !== "log") DEFAULTS[`${m}.on`] = true;
  for (const c of cmds) DEFAULTS[`c.${c}`] = true;
}

let E; // Umgebung (Variablen, Secrets, Datenbank) der aktuellen Anfrage

// ---------- Verschlüsselung (Web Crypto) ----------
const enc = new TextEncoder(), dec = new TextDecoder();
const toB64 = (buf) => {
  let s = ""; for (const b of new Uint8Array(buf)) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
};
const fromB64 = (t) => {
  t = t.replace(/-/g, "+").replace(/_/g, "/"); while (t.length % 4) t += "=";
  return Uint8Array.from(atob(t), (c) => c.charCodeAt(0));
};
let _k;
const key = async () => (_k ??= await crypto.subtle.importKey(
  "raw", await crypto.subtle.digest("SHA-256", enc.encode(E.SESSION_SECRET || "")), "AES-GCM", false, ["encrypt", "decrypt"]));
async function seal(obj) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, await key(), enc.encode(JSON.stringify(obj))));
  const out = new Uint8Array(12 + ct.length); out.set(iv); out.set(ct, 12);
  return toB64(out);
}
async function unseal(t) {
  try {
    const b = fromB64(t);
    const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b.slice(0, 12) }, await key(), b.slice(12));
    return JSON.parse(dec.decode(pt));
  } catch { return null; }
}
async function safeEq(a, b) {
  const [x, y] = await Promise.all([a, b].map(async (v) => new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(v)))));
  let d = 0; for (let i = 0; i < 32; i++) d |= x[i] ^ y[i];
  return d === 0;
}
const rand = () => [...crypto.getRandomValues(new Uint8Array(16))].map((b) => b.toString(16).padStart(2, "0")).join("");

// ---------- Hilfsfunktionen ----------
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
const session = async (req) => {
  const t = cookies(req).nx_s; const s = t && await unseal(t);
  return s && s.exp > Date.now() ? s : null;
};
const dc = (path, auth, init = {}) =>
  fetch(API + path, { ...init, headers: { authorization: auth, "user-agent": UA, ...(init.headers || {}) } });
const BOT = () => `Bot ${E.BOT_TOKEN}`;

const memo = new Map(); // kurzer Zwischenspeicher, damit Discord nicht bei jedem Klick abgefragt wird (Rate-Limit)
async function cached(k, ttl, fn) {
  const h = memo.get(k);
  if (h && Date.now() - h.t < ttl) return h.v;
  const v = await fn();
  if (v) {
    memo.set(k, { t: Date.now(), v });
    if (memo.size > 200) memo.delete(memo.keys().next().value);
  }
  return v;
}
async function userGuilds(s) {
  return cached("g:" + s.uid, 20000, async () => {
    const r = await dc("/users/@me/guilds", `Bearer ${s.token}`);
    if (r.status === 401) return null;
    if (!r.ok) throw new Error("discord " + r.status);
    return r.json();
  });
}
const canManage = (g) => {
  const p = BigInt(g.permissions);
  return !!g.owner || (p & 0x8n) !== 0n || (p & 0x20n) !== 0n;
};
async function botIds() {
  return cached("bot", 20000, async () => {
    const r = await dc("/users/@me/guilds?limit=200", BOT());
    if (!r.ok) throw new Error("bot " + r.status);
    return new Set((await r.json()).map((g) => g.id));
  });
}
// ---------- Team-Rollen (Discord-Rollen auf dem Nexora-Server) ----------
const EDIT = new Set(["dev", "admin", "owner"]); // team, sup, mod = nur Ansicht
async function roleOf(uid) {
  if (E.OWNER_ID && uid === E.OWNER_ID) return "owner";
  if (!E.NEXORA_GUILD_ID) return null;
  let r;
  try { r = await cached("r:" + uid, 60000, async () => {
    const x = await dc(`/guilds/${E.NEXORA_GUILD_ID}/members/${uid}`, BOT());
    if (!x.ok) return "none";
    const ids = (await x.json()).roles || []; let best = "none";
    for (const k of ["team", "sup", "mod", "dev", "admin"]) { const id = E["ROLE_" + k.toUpperCase()]; if (id && ids.includes(id)) best = k; }
    return best;
  }); } catch { return null; }
  return r === "none" ? null : r;
}
const audit = (s, role, guild, act) => E.DB.prepare("INSERT INTO audit (t,uid,name,role,guild,act) VALUES (?,?,?,?,?,?)")
  .bind(Date.now(), s.uid, s.name, role, guild, act).run();
const botGuilds = () => cached("bg", 20000, async () => {
  const r = await dc("/users/@me/guilds?limit=200", BOT()); if (!r.ok) throw new Error("bot " + r.status);
  return (await r.json()).map((g) => ({ id: g.id, name: g.name, icon: g.icon, bot: true }));
});

async function access(s, id, rl) {
  if (rl === "owner") return (await botIds()).has(id) ? { via: true } : { err: json({ detail: "Nexora ist nicht auf diesem Server" }, 404) };
  if (s.sup && s.sup.exp > Date.now()) return s.sup.guilds.some((g) => g.id === id) ? { via: true } : { err: json({ detail: "Kein Zugriff" }, 403) };
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
const fmt = (sec) => {
  sec = Math.max(0, Math.floor(sec));
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
  return d ? `${d} Tg ${h} Std` : h ? `${h} Std ${m} Min` : `${m} Min`;
};
const isBot = async (req) => {
  const a = req.headers.get("authorization") || "";
  return !!E.BOT_API_KEY && await safeEq(a, `Bearer ${E.BOT_API_KEY}`);
};

// ---------- Datenbank (D1) ----------
let ready;
const init = () => (ready ??= E.DB.batch([
  E.DB.prepare("CREATE TABLE IF NOT EXISTS settings (guild_id TEXT PRIMARY KEY, data TEXT NOT NULL)"),
  E.DB.prepare("CREATE TABLE IF NOT EXISTS stats (k TEXT PRIMARY KEY, v TEXT NOT NULL)"),
  E.DB.prepare("CREATE TABLE IF NOT EXISTS pins (uid TEXT PRIMARY KEY, pin TEXT, exp INTEGER, name TEXT, guilds TEXT)"),
  E.DB.prepare("CREATE TABLE IF NOT EXISTS audit (t INTEGER, uid TEXT, name TEXT, role TEXT, guild TEXT, act TEXT)"),
  E.DB.prepare("CREATE TABLE IF NOT EXISTS logs (guild TEXT, t INTEGER, lvl TEXT, msg TEXT)"),
  E.DB.prepare("CREATE TABLE IF NOT EXISTS usage (guild TEXT, cmd TEXT, n INTEGER, PRIMARY KEY (guild, cmd))"),
]).catch((e) => { ready = undefined; throw e; }));
const load = async (id) => {
  const row = await E.DB.prepare("SELECT data FROM settings WHERE guild_id = ?").bind(id).first();
  return { ...DEFAULTS, ...(row ? JSON.parse(row.data) : {}) };
};
const saveSettings = (id, data) => E.DB.prepare(
  "INSERT INTO settings (guild_id, data) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET data = excluded.data")
  .bind(id, JSON.stringify(data)).run();
const getStats = async () => {
  const row = await E.DB.prepare("SELECT v FROM stats WHERE k = 'bot'").first();
  return row ? JSON.parse(row.v) : {};
};
const setStats = (d) => E.DB.prepare(
  "INSERT INTO stats (k, v) VALUES ('bot', ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v").bind(JSON.stringify(d)).run();

// ---------- Routen ----------
export async function onRequest(context) {
  E = context.env;
  const req = context.request, url = new URL(req.url), p = url.pathname, m = req.method;
  if (!/^\/(login|callback|logout|invite\/|api\/)/.test(p)) return context.next(); // normale Seiten/Bilder

  try {
    const miss = REQUIRED.filter((k) => !E[k]);
    if (miss.length) return json({ detail: "Fehlende Variablen in Cloudflare: " + miss.join(", ") }, 500);
    if (!E.DB) return json({ detail: "D1-Datenbank mit dem Namen DB ist nicht verbunden" }, 500);
    await init();

    if (p === "/login") {
      const state = rand();
      const q = new URLSearchParams({
        client_id: E.CLIENT_ID, redirect_uri: url.origin + "/callback",
        response_type: "code", scope: "identify guilds", state,
      });
      return go(`https://discord.com/oauth2/authorize?${q}`, [ck("nx_state", state, 600)]);
    }
    if (p === "/callback") {
      const code = url.searchParams.get("code"), state = url.searchParams.get("state");
      if (!code || state !== cookies(req).nx_state) return go("/", [ck("nx_state", "", 0)]);
      const tr = await fetch(`${API}/oauth2/token`, {
        method: "POST", headers: { "content-type": "application/x-www-form-urlencoded", "user-agent": UA },
        body: new URLSearchParams({
          client_id: E.CLIENT_ID, client_secret: E.CLIENT_SECRET,
          grant_type: "authorization_code", code, redirect_uri: url.origin + "/callback",
        }),
      });
      if (!tr.ok) return go("/", [ck("nx_state", "", 0)]);
      const { access_token } = await tr.json();
      const u = await (await dc("/users/@me", `Bearer ${access_token}`)).json();
      const s = { uid: u.id, name: u.global_name || u.username, token: access_token, exp: Date.now() + 7 * 864e5 };
      return go("/", [ck("nx_s", await seal(s), 7 * 86400), ck("nx_state", "", 0)]);
    }
    if (p === "/logout") return go("/", [ck("nx_s", "", 0)]);

    // Öffentlich: Bot-Status für den Tracker
    if (p === "/api/stats") {
      const d = await getStats();
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
      if (!(await isBot(req))) return json({ detail: "Nicht erlaubt" }, 403);
      const b = await req.json(), n = (x) => Number(x) || 0;
      await setStats({ heartbeat: Date.now(), servers: n(b.servers), users: n(b.users),
        ping: n(b.ping), commands: n(b.commands), started: n(b.started) });
      return json({ ok: true });
    }
    if (p === "/api/bot/settings" && m === "GET") { // alle Server auf einmal (eine Anfrage statt eine pro Server)
      if (!(await isBot(req))) return json({ detail: "Nicht erlaubt" }, 403);
      const rows = await E.DB.prepare("SELECT guild_id, data FROM settings").all();
      const guilds = {};
      for (const r of rows.results || []) guilds[r.guild_id] = { ...DEFAULTS, ...JSON.parse(r.data) };
      return json({ defaults: DEFAULTS, guilds });
    }
    if (p === "/api/bot/events" && m === "POST") { // Bot -> Dashboard: Fehler-Konsole und Befehls-Tracker
      if (!(await isBot(req))) return json({ detail: "Nicht erlaubt" }, 403);
      const b = await req.json().catch(() => ({})), st = [];
      for (const l of (b.logs || []).slice(0, 200)) if (/^\d+$/.test(String(l.g)))
        st.push(E.DB.prepare("INSERT INTO logs (guild,t,lvl,msg) VALUES (?,?,?,?)").bind(String(l.g), Number(l.t) || Date.now(), String(l.l).slice(0, 8), String(l.m).slice(0, 300)));
      for (const [g, cmds] of Object.entries(b.usage || {})) if (/^\d+$/.test(g))
        for (const [c, n] of Object.entries(cmds).slice(0, 80))
          st.push(E.DB.prepare("INSERT INTO usage (guild,cmd,n) VALUES (?,?,?) ON CONFLICT(guild,cmd) DO UPDATE SET n = n + excluded.n").bind(g, String(c).slice(0, 40), Math.max(0, Number(n) || 0)));
      st.push(E.DB.prepare("DELETE FROM logs WHERE t < ?").bind(Date.now() - 7 * 864e5));
      await E.DB.batch(st);
      return json({ ok: true });
    }
    const bs = p.match(/^\/api\/bot\/settings\/(\d+)$/);
    if (bs) {
      if (!(await isBot(req))) return json({ detail: "Nicht erlaubt" }, 403);
      if (m === "PUT") { // Bot -> Dashboard: Einstellungen aus Discord (/einstellungen, /logkanal) speichern
        const body = await req.json();
        const data = { ...(await load(bs[1])), ...clean(body && typeof body === "object" ? body : {}) };
        if (data.workmin > data.workmax) return json({ detail: "Arbeiten: Minimum darf nicht größer als Maximum sein" }, 400);
        await saveSettings(bs[1], data);
        return json(data);
      }
      return json(await load(bs[1]));
    }

    // Ab hier: nur eingeloggte Nutzer
    const s = await session(req);
    if (!s) return json({ detail: "Nicht eingeloggt" }, 401);
    const rl = await roleOf(s.uid), sup = s.sup && s.sup.exp > Date.now() ? s.sup : null;
    if (p === "/api/me") return json({ id: s.uid, name: s.name, role: rl, sup: sup && sup.name, edit: !(sup && !EDIT.has(rl)) });
    if (p === "/api/pin") { // jeder Nutzer hat einen Support-PIN, der alle 5 Minuten wechselt
      const gs = await userGuilds(s), bots = await botIds();
      if (!gs) return json({ detail: "Sitzung abgelaufen" }, 401, [ck("nx_s", "", 0)]);
      const mine = gs.filter(canManage).filter((g) => bots.has(g.id)).slice(0, 15).map((g) => ({ id: g.id, name: g.name.slice(0, 30) }));
      let row = await E.DB.prepare("SELECT pin, exp FROM pins WHERE uid = ?").bind(s.uid).first();
      if (!row || row.exp < Date.now()) {
        row = { pin: String(crypto.getRandomValues(new Uint32Array(1))[0] % 1000000).padStart(6, "0"), exp: Date.now() + 300000 };
        await E.DB.prepare("INSERT INTO pins (uid,pin,exp,name,guilds) VALUES (?,?,?,?,?) ON CONFLICT(uid) DO UPDATE SET pin=excluded.pin, exp=excluded.exp, name=excluded.name, guilds=excluded.guilds")
          .bind(s.uid, row.pin, row.exp, s.name, JSON.stringify(mine)).run();
      }
      return json({ pin: row.pin, left: Math.max(0, Math.floor((row.exp - Date.now()) / 1000)) });
    }
    if (p === "/api/support" && m === "POST") { // Team löst einen PIN ein
      if (!rl) return json({ detail: "Nur für das Nexora-Team" }, 403);
      const b = await req.json().catch(() => ({}));
      const bad = await E.DB.prepare("SELECT COUNT(*) AS n FROM audit WHERE uid = ? AND act = 'PIN falsch' AND t > ?").bind(s.uid, Date.now() - 60000).first();
      if (bad && bad.n >= 8) return json({ detail: "Zu viele Fehlversuche, bitte eine Minute warten" }, 429);
      const row = await E.DB.prepare("SELECT uid, name, guilds FROM pins WHERE pin = ? AND exp > ?").bind(String(b.pin || "").replace(/\D/g, ""), Date.now()).first();
      if (!row) { await audit(s, rl, "-", "PIN falsch"); return json({ detail: "PIN ungültig oder abgelaufen" }, 404); }
      await audit(s, rl, "-", "Support-PIN von " + row.name + " eingelöst");
      return json({ ok: true }, 200, [ck("nx_s", await seal({ ...s, sup: { uid: row.uid, name: row.name, guilds: JSON.parse(row.guilds), exp: Date.now() + 3600000 } }), 7 * 86400)]);
    }
    if (p === "/api/support" && m === "DELETE") { const { sup: _x, ...rest } = s; return json({ ok: true }, 200, [ck("nx_s", await seal(rest), 7 * 86400)]); }
    if (p === "/api/audit") {
      if (rl !== "owner" && rl !== "admin") return json({ detail: "Keine Rechte" }, 403);
      return json((await E.DB.prepare("SELECT t, name, role, guild, act FROM audit ORDER BY t DESC LIMIT 40").all()).results || []);
    }

    if (p === "/api/guilds") {
      const gs = await userGuilds(s);
      if (!gs) return json({ detail: "Sitzung abgelaufen" }, 401, [ck("nx_s", "", 0)]);
      const bots = await botIds();
      if (sup) return json(sup.guilds.map((g) => ({ id: g.id, name: g.name + " (Support)", icon: null, bot: true })));
      const list = gs.filter(canManage).map((g) => ({ id: g.id, name: g.name, icon: g.icon, bot: bots.has(g.id) }));
      if (rl === "owner") for (const g of await botGuilds()) if (!list.some((x) => x.id === g.id)) list.push({ ...g, name: g.name + " (Besitzer)" });
      return json(list);
    }
    const inv = p.match(/^\/invite\/(\d+)$/);
    if (inv) {
      const q = new URLSearchParams({
        client_id: E.CLIENT_ID, scope: "bot applications.commands", permissions: BOT_PERMISSIONS,
        guild_id: inv[1], disable_guild_select: "true",
      });
      return go(`https://discord.com/oauth2/authorize?${q}`);
    }
    const gm = p.match(/^\/api\/guilds\/(\d+)\/(settings|channels|usage|console)$/);
    if (gm) {
      const [, id, what] = gm;
      const a = await access(s, id, rl); if (a.err) return a.err;
      if (what === "usage") return json((await E.DB.prepare("SELECT cmd, n FROM usage WHERE guild = ? ORDER BY n DESC LIMIT 20").bind(id).all()).results || []);
      if (what === "console") { // nur mit Support-PIN (oder als Besitzer)
        if (!a.via) return json({ detail: "Die Konsole ist nur mit einem Support-PIN sichtbar" }, 403);
        return json((await E.DB.prepare("SELECT t, lvl, msg FROM logs WHERE guild = ? ORDER BY t DESC LIMIT 100").bind(id).all()).results || []);
      }
      if (what === "channels") {
        const r = await dc(`/guilds/${id}/channels`, BOT());
        if (!r.ok) return json([]);
        return json((await r.json()).filter((c) => c.type === 0)
          .sort((x, y) => (x.position || 0) - (y.position || 0)).map((c) => ({ id: c.id, name: c.name })));
      }
      if (m === "GET") return json(await load(id));
      if (m === "PUT") {
        if (a.via && !EDIT.has(rl)) return json({ detail: "Nur Ansicht: deine Team-Rolle darf nicht bearbeiten" }, 403);
        if (a.via && !(await userGuilds(s) || []).some((g) => g.id === id && canManage(g))) await audit(s, rl, id, "Einstellungen geändert");
        const body = await req.json();
        const data = { ...(await load(id)), ...clean(body && typeof body === "object" ? body : {}) };
        if (data.workmin > data.workmax) return json({ detail: "Arbeiten: Minimum darf nicht größer als Maximum sein" }, 400);
        await saveSettings(id, data);
        return json(data);
      }
    }
    return json({ detail: "Nicht gefunden" }, 404);
  } catch (e) {
    console.error(e);
    return json({ detail: "Serverfehler: " + String((e && e.message) || e).slice(0, 120) }, 500);
  }
}
