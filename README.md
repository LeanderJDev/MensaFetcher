# MensaFetcher

-   Datensammlung und Parsing von Mensa-Speiseplänen der my-mensa.de Plattform.
-   Kompatibel mit allen my-mensa.de/essen.php Seiten

## parse_menu.py

-   Script zum Parsen der Mensa‑HTML (auch komprimierte Einzeiler) und Export als JSON.
-   Unterstützt Eingabe per URL (`--url`) oder lokale Datei (`--file`).
-   Ausgabe als JSON in Datei (`-o/--output`) oder stdout (Standard).
-   Optionales `--date` Argument zur Angabe des Datums des Speiseplans (Format: `YYYYMMDD` oder `today` für aktuelles Datum).
-   Entfernt unsichtbare Zeichen aus Textfeldern.
-   Extrahiert Gerichtsinformationen: `name`, `description`, `category`, `zusatzstoffe`, `tags`, `price_eur`.

## Schnellstart

-   Abhängigkeiten installieren (empfohlen in einem venv):

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
pip install requests beautifulsoup4
```

-   Beispielaufruf (aus Datei):

```bash
python3 mensa/parse_menu.py --file menu_251126.html -o out.json
```

-   Wenn `--date` gesetzt ist und kein `-o/--output` angegeben wurde, wird die Ausgabedatei automatisch als `menu_<date>.json` benannt:

```bash
python3 mensa/parse_menu.py --file menu_251126.html --date 2025329
# -> schreibt in menu_2025329.json
```

## Cron‑Beispiel

-   Tägliches Ausführen um 06:00 Uhr und Ablage pro Datum (systemweit für den Benutzer):

```cron
0 6 * * * cd path_to_project && /usr/bin/python3 ./parse_menu.py --url 'https://example.my-mensa.de/essen.php?mensa=example' --date today
```

Hinweis: Das Script benennt die Datei `menu_<numericDate>.json`, wenn `--date` verwendet wird und kein `-o` gesetzt ist.
