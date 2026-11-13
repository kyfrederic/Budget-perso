#!/usr/bin/env bash
# Test de restauration : récupère la dernière sauvegarde et vérifie qu'elle est lisible.
# À lancer une fois par mois (cron : 30 4 1 * *) et après toute modification des sauvegardes.
set -euo pipefail

set -a; . /etc/budget-backup.env; set +a
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

restic restore latest --tag budget --target "$TMP"
DB="$(find "$TMP" -name budget.sqlite | head -n 1)"
[ -n "$DB" ] || { echo "ÉCHEC : base absente de la sauvegarde"; exit 1; }

python3 - "$DB" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
    sys.exit("ÉCHEC : sauvegarde corrompue")
mois = c.execute("SELECT COUNT(*) FROM months").fetchone()[0]
dernier = c.execute("SELECT year, month FROM months ORDER BY year DESC, month DESC LIMIT 1").fetchone()
print(f"Restauration OK : {mois} mois, dernier = {dernier}")
PY
