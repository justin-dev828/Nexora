# Nexora Dashboard


## Checkliste: Das musst du selbst erledigen
- [x] Client ID, Client Secret und Bot-Token aus dem Developer Portal holen
- [x] Redirect-URI im Developer Portal eintragen
- [x] `.env` ausfüllen (lokal) bzw. Variablen beim Hoster setzen
- [x] Lokal testen: Login, Server wählen, Einstellung speichern, Bot hinzufügen
- [x] `bot_example.py` in den Bot einbauen und `heartbeat.start()` aufrufen
- [x] Alle Befehle des Bots auf `get_cfg` / `command_enabled` umstellen
- [x] Gemeinsame Datenbank für Bot und Dashboard sicherstellen
- [x] Hoster einrichten und Domain mit https verwenden
- [x] Befehle in `MODULES` (`main.py`) und `MODS` (`static/index.html`) abgleichen, falls sich Befehle ändern
