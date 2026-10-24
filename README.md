# Nexora Dashboard

Dashboard-Website für den Discord-Bot **Nexora** (Python-Backend mit FastAPI, Design im Nexora-Glas-Stil).

## Features
- Login mit Discord, danach Serverauswahl (nur Server, auf denen du „Server verwalten“ darfst)
- Server ohne Bot zeigen „＋ Bot hinzufügen“ – ein Klick öffnet Discord mit dem Server schon vorausgewählt
- Einstellungen pro Server: Economy, Tägliche Aufgaben, Shop & Inventar, Moderation, Admin-Tools, Log-Kanal, Daten & Sicherheit
- Funktionen als anklickbare Kacheln, Befehle per Antippen ein-/ausschalten, Werte werden serverseitig geprüft
- Startseite mit Bot-Status-Tracker (Server, Online/Offline, Ping, Nutzer, Befehle, Laufzeit)
- Theme-Wahl oben rechts: Nexora, Dunkel, Hell
- Glas-/Bubble-Design mit Animationen, passt sich an Handy und Computer an
- Links zu Discord-Server, Bot, Datenschutzerklärung und Nutzungsbedingungen

## Dateien
| Datei | Zweck |
|---|---|
| `main.py` | Backend (Login, Server, Einstellungen, Bot-Status) |
| `static/index.html` | Die Webseite |
| `static/nexora-*.png` | Logo und Banner |
| `bot_example.py` | Code für deinen Bot (Einstellungen lesen + Status senden) |
| `.env.example` | Vorlage für deine geheimen Werte |
| `requirements.txt`, `Procfile` | Python-Pakete und Startbefehl für Hoster |

## Schritt 1: Discord Developer Portal
Öffne https://discord.com/developers/applications und wähle deine Bot-Anwendung.
1. **OAuth2**: Client ID und **Client Secret** kopieren (Secret bei Bedarf neu erzeugen).
2. **OAuth2 → Redirects**: Adresse eintragen, die später genutzt wird:
   - lokal: `http://localhost:8000/callback`
   - online: `https://DEINE-DOMAIN/callback`
3. **Bot**: Token kopieren.

## Schritt 2: Lokal testen
```
python -m venv venv
venv\Scripts\activate          (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env         (Mac/Linux: cp .env.example .env)
```
Die `.env` öffnen und ausfüllen:
| Variable | Bedeutung |
|---|---|
| `CLIENT_ID` | Application/Client ID |
| `CLIENT_SECRET` | Client Secret |
| `BOT_TOKEN` | Bot-Token |
| `REDIRECT_URI` | exakt wie im Developer Portal (siehe Schritt 1) |
| `SESSION_SECRET` | beliebige lange Zufallsfolge |
| `HTTPS_ONLY` | lokal `false`, online `true` |
| `DB_PATH` | Pfad zur Datenbank, die auch dein Bot nutzt |

Starten:
```
uvicorn main:app --reload
```
Dann http://localhost:8000 im Browser öffnen.

## Schritt 3: Bot anbinden
Öffne `bot_example.py` und baue es in deinen Bot ein:
1. `get_cfg(guild_id)` liefert die Einstellungen eines Servers. Frage damit in jedem Befehl ab, ob Modul und Befehl aktiv sind (`command_enabled`) und welche Werte gelten (Belohnung, Streak, Währung …).
2. Ist `logch` leer, soll der Bot gesperrt sein (so wie in deinem Update-Post beschrieben). Moderationsaktionen gehören in diesen Log-Kanal.
3. `heartbeat` schreibt alle 30 Sekunden den Status für den Tracker. Starte ihn mit `heartbeat.start()`, z. B. in `setup_hook`. Ohne diesen Schritt zeigt der Tracker „Offline“.
4. Bot und Dashboard müssen **dieselbe Datenbank** nutzen (`DB_PATH`). Laufen sie auf verschiedenen Rechnern, nimm PostgreSQL statt SQLite und passe die Datenbank-Zugriffe in `main.py` und `bot_example.py` an.

## Schritt 4: Online stellen
Du brauchst einen Hoster, auf dem Python **dauerhaft** läuft (eigener Server/VPS, Railway, Render o. Ä.). Reine Webseiten-Hoster für statische Seiten reichen für diese Version nicht.
1. Code auf GitHub hochladen (die `.env` **nie** hochladen – die `.gitignore` verhindert das).
2. Beim Hoster das Repo verbinden. Startbefehl: `uvicorn main:app --host 0.0.0.0 --port $PORT` (steht in der `Procfile`).
3. Alle Variablen aus der Tabelle oben beim Hoster eintragen. `HTTPS_ONLY=true`, `REDIRECT_URI=https://DEINE-DOMAIN/callback`.
4. Dieselbe Redirect-Adresse im Developer Portal eintragen.
5. Einen Speicher (Volume/Disk) für die Datenbank einrichten, damit Einstellungen Neustarts überstehen, und `DB_PATH` darauf zeigen lassen.

## Checkliste: Das musst du selbst erledigen
- [ ] Client ID, Client Secret und Bot-Token aus dem Developer Portal holen
- [ ] Redirect-URI im Developer Portal eintragen
- [ ] `.env` ausfüllen (lokal) bzw. Variablen beim Hoster setzen
- [ ] Lokal testen: Login, Server wählen, Einstellung speichern, Bot hinzufügen
- [ ] `bot_example.py` in den Bot einbauen und `heartbeat.start()` aufrufen
- [ ] Alle Befehle des Bots auf `get_cfg` / `command_enabled` umstellen
- [ ] Gemeinsame Datenbank für Bot und Dashboard sicherstellen
- [ ] Hoster einrichten und Domain mit https verwenden
- [ ] Befehle in `MODULES` (`main.py`) und `MODS` (`static/index.html`) abgleichen, falls sich Befehle ändern
