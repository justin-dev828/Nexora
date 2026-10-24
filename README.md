# Nexora Dashboard

## 1. Discord Developer Portal (https://discord.com/developers/applications)
- Deine Bot-Anwendung öffnen -> **OAuth2**
  - Client ID und **Client Secret** kopieren
  - Unter **Redirects** eintragen: `http://localhost:8000/callback`
- Unter **Bot**: Token kopieren

## 2. Einrichten
```
cd nexora
python -m venv venv
venv\Scripts\activate          # Windows   (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env         # Mac/Linux: cp .env.example .env
```
`.env` öffnen und die Werte eintragen (`SESSION_SECRET` = beliebige lange Zeichenfolge).

## 3. Starten
```
uvicorn main:app --reload
```
Dann im Browser öffnen: http://localhost:8000

## 4. Online stellen
Redirect-URI im Portal und in `.env` auf deine Domain ändern (https) und `HTTPS_ONLY=true` setzen.
Der Bot liest die Einstellungen wie in `bot_example.py` aus derselben Datenbank.
