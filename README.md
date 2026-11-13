# Budget personnel

Application web personnelle (PC + téléphone) qui remplace les fichiers `MOIS_SOLO.xlsx`.
Cahier des charges et décisions : [CLAUDE.md](CLAUDE.md). Ce dépôt contient la **V1**.

## Ce que fait la V1

- **Mois** : prévu et réel par poste, part de Laetitia pour information, virements par compte, épargne du mois.
- **Matelas** : reste = 500 € − dépassements + économies ; alerte quand il ne suffit plus.
- **Nouveau mois** : copie du mois précédent, saisie du salaire, du net imposable et du prélèvement à la source.
- **Propositions d'ajustement** (hausse ou baisse), à accepter ou refuser.
- **Analyse** : constats et pistes, 50-30-20, taux d'épargne, crédits.
- **Calendrier** des prélèvements aux couleurs des banques, **chèques** par mois prévu.
- **Crédits** : reste dû mois par mois et objectif de date.

L'import des fichiers Excel n'est pas encore écrit : il le sera sur les vrais fichiers.

## Essai en local

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
export BUDGET_DEV=1                      # autorise http://localhost (jamais en production)
.venv/bin/flask --app budget set-password      # 14 caractères minimum
.venv/bin/flask --app budget charger-modele    # postes de config/modele.toml (montants d'exemple)
.venv/bin/flask --app budget run
.venv/bin/python -m pytest                     # tests
```

## Configuration

| Fichier | Contenu |
|---|---|
| `config/settings.toml` | matelas, seuils des propositions, saison forte, cible 50-30-20, comptes et couleurs, sécurité |
| `config/modele.toml` | modèle de départ (postes, premier mois, crédits), chargé une seule fois |

Après une modification de `settings.toml` : `docker compose restart app`.

## Déploiement sur un VPS

Non testé dans un vrai conteneur à ce stade (pas de Docker dans l'environnement de développement).

1. **Durcir le serveur avant tout** :
   - connexion SSH par clé uniquement (`PasswordAuthentication no`, `PermitRootLogin no`) ;
   - pare-feu : `ufw default deny incoming && ufw allow 22,80,443/tcp && ufw enable` ;
   - mises à jour automatiques : `apt install unattended-upgrades` ;
   - `apt install fail2ban`.
2. Faire pointer un nom de domaine vers le VPS.
3. Installer Docker, cloner le dépôt dans `/opt/budget`, puis :
   ```bash
   cd /opt/budget/deploy
   cp .env.exemple .env && nano .env            # DOMAINE=...
   mkdir -p ../instance && chown 10001 ../instance
   docker compose up -d --build                 # Caddy obtient le certificat HTTPS tout seul
   docker compose exec app flask --app budget set-password
   docker compose exec app flask --app budget charger-modele
   ```
4. Sur le téléphone : ouvrir le site puis « Ajouter à l'écran d'accueil ».

### Sauvegardes (à mettre en place avant de saisir de vraies données)

- `scripts/backup.sh` : copie cohérente de la base, envoyée chiffrée hors du VPS avec [restic](https://restic.net). Créer `/etc/budget-backup.env` (droits 600) avec `RESTIC_REPOSITORY` et `RESTIC_PASSWORD`, lancer `restic init`, puis ajouter au cron de root :
  ```
  15 3 * * *  /opt/budget/scripts/backup.sh       >> /var/log/budget-backup.log 2>&1
  30 4 1 * *  /opt/budget/scripts/restore_test.sh >> /var/log/budget-backup.log 2>&1
  ```
- `scripts/restore_test.sh` : restaure la dernière sauvegarde et vérifie qu'elle est lisible.
- Garder le mot de passe restic ailleurs que sur le VPS : sans lui, aucune restauration n'est possible.

## Sécurité

Mot de passe haché (scrypt), blocage après 5 tentatives par quart d'heure, jeton anti-CSRF sur chaque formulaire, cookie de session `Secure` / `HttpOnly`, politique CSP stricte, conteneur en lecture seule sans privilèges. Pas de second facteur en V1 (décision du 2026-11-13) : le mot de passe doit être long et unique.
