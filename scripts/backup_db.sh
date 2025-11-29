#!/usr/bin/env bash
# Simple weekly backup script for the MensaFetcher sqlite DB.
# Usage: scripts/backup_db.sh /path/to/mensa.db /path/to/backup/dir
set -euo pipefail
DB_PATH=${1:-mensa.db}
BACKUP_DIR=${2:-./backups}
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date -u +"%Y%m%dT%H%M%SZ")
BACKUP_FILE="$BACKUP_DIR/$(basename "$DB_PATH")-$TIMESTAMP"
# Copy DB and -wal/-shm if present to ensure a consistent snapshot.
cp "$DB_PATH" "$BACKUP_FILE" || exit 1
if [ -f "$DB_PATH-wal" ]; then
  cp "$DB_PATH-wal" "$BACKUP_FILE-wal" || true
fi
if [ -f "$DB_PATH-shm" ]; then
  cp "$DB_PATH-shm" "$BACKUP_FILE-shm" || true
fi
# Optional: you can gzip backups to save space
# gzip "$BACKUP_FILE"

echo "Backup written to $BACKUP_FILE"
