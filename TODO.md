## Empfehlungen für Cron/Langzeitbetrieb

-   Logging: Ersetze `print` durch das `logging`‑Modul und rotiere Logs (z. B. `logging.handlers.RotatingFileHandler`).
-   Monitoring: Prüfe Exit‑Codes; bei Fehlern kurze Mail/Benachrichtigung senden.
-   Retention: Bei täglicher Archivierung lohnt sich ein Aufrägeskript (z. B. Dateien älter als 365 Tage löschen).

## Datenbank-Speicherformat

-   Fetch zur Mensa-Öffnung (z. B. 6 Uhr morgens) und speichere in Datenbank
-   Datenbank enthhält Tabellen für Gerichte, Zusatzstoffe
-   Fetch kurz vor Mensa-Schluss (z. B. 14 Uhr) und aktualisiere Verfügbarkeit
-   Ermöglicht Analyse der Verfügbarkeit über Zeit
