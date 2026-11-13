#!/usr/bin/env bash
# Sauvegarde nocturne hors du VPS, avec restic (chiffrée, dédupliquée).
# Prérequis : restic installé, et /etc/budget-backup.env contenant :
#   RESTIC_REPOSITORY=...   (ex. sftp:user@hote:/budget, s3:..., b2:...)
#   RESTIC_PASSWORD=...     (à conserver AUSSI hors du VPS, sinon restauration impossible)
# Cron (root) : 15 3 * * * /opt/budget/scripts/backup.sh >> /var/log/budget-backup.log 2>&1
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
set -a; . /etc/budget-backup.env; set +a

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
# Copie cohérente de la base (sûre même si l'appli est en cours d'utilisation).
python3 - "$APP_DIR/instance/budget.sqlite" "$TMP/budget.sqlite" <<'PY'
import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
assert dst.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
PY
cp -r "$APP_DIR/config" "$TMP/config"

restic backup --tag budget "$TMP"
restic forget --tag budget --keep-daily 14 --keep-weekly 8 --keep-monthly 24 --prune
echo "$(date -Is) sauvegarde terminée"
