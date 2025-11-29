# MensaFetcher

-   Datensammlung und Parsing von Mensa-Speiseplänen der my-mensa.de Plattform.
-   Kompatibel mit allen my-mensa.de/essen.php Seiten

## parser.py

-   Modul zum Parsen der Mensa‑HTML (auch komprimierte Einzeiler) und Export als JSON.
-   Entfernt unsichtbare Zeichen aus Textfeldern.
-   Extrahiert Gerichtsinformationen: `name`, `description`, `category`, `zusatzstoffe`, `tags`, `price_eur`.

### fetch_menu.py

-   Wrapper für parser.py zum Abrufen und Parsen von Menüs
-   Unterstützt Eingabe per URL (`--url`) oder lokale Datei (`--file`).
-   Ausgabe als JSON in Datei (`-o/--output`)
-   Optionales `--date` Argument zur Angabe des Datums des Speiseplans (Format: `YYYYMMDD` oder `today` für aktuelles Datum).

## ingest.py

Das Projekt enthält eine Ingest‑Pipeline, die Snapshots in eine
SQLite‑Datenbank schreibt und beim zweiten Lauf (attempt=2) automatisch
berechnet, welche Gerichte seit dem ersten Lauf leer waren.

Wichtigste Dateien:

-   `src/ingest.py` — CLI zum Ausführen eines Ingest‑Laufs
-   `src/db.py` — DB‑Initialisierung und Helfer: `init_db`, `store_snapshot`, `compute_empties`
-   `scripts/backup_db.sh` — einfaches Backup‑Skript für die DB‑Datei

Benachrichtigungen:

-   `src.ingest` unterstützt `--notify-cmd` oder die Umgebungsvariable
    `MENSA_NOTIFY_CMD` — wird mit `subject` und `body` aufgerufen.

Hinweis: für die Langzeit‑Auswertung lade die relevanten Tabellen nach Pandas
mit `pd.read_sql()` und verwende `merge`/`explode` für Tag‑Analysen.

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
15 11 * * 1-5 cd /path/to/MensaFetcher/ && /usr/bin/python3 src.ingest --url "https://example.my-mensa.de/essen.php?mensa=123" --db /path/to/MensaFetcher/menus/mensa.db --attempt 1

45 12 * * 1-5 cd /path/to/MensaFetcher/ && /usr/bin/python3 -m src.ingest --url "https://example.my-mensa.de/essen.php?mensa=123" --db /path/to/MensaFetcher/menus/mensa.db --attempt 2

0 3 * * 6 /bin/bash /path/to/MensaFetcher/scripts/backup_db.sh /path/to/MensaFetcher/mensa.db /path/to/MensaFetcher/backups
```

Hinweis: Das Script benennt die Datei `menu_<numericDate>.json`, wenn `--date` verwendet wird und kein `-o` gesetzt ist.
