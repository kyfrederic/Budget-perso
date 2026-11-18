# Budget personnel

Application web personnelle (PC + téléphone) qui remplace les fichiers `MOIS_SOLO.xlsx`.
Cahier des charges et décisions : [CLAUDE.md](CLAUDE.md). Ce dépôt contient la **V1**.

## Ce que fait la V1

- **Mois** : épargne du mois et matelas en tête, virements par compte à cocher quand ils sont faits, avec le reste du salaire qui descend à chaque case cochée, prévu et réel par poste, part de Laetitia pour information.
- **Matelas** : reste = 500 € − dépassements − imprévus + économies (créditées en fin de mois) ; alerte quand il ne suffit plus.
- **Achats** : un imprévu payé avec le matelas, ou un achat noté sur un poste ; **photo du ticket de caisse** avec lecture automatique du montant, à confirmer.
- **Nouveau mois** : copie du mois précédent, saisie du salaire, du net imposable et du prélèvement à la source.
- **Propositions d'ajustement** (hausse ou baisse), à accepter ou refuser.
- **Analyse** : constats et pistes, 50-30-20, taux d'épargne, crédits.
- **Calendrier** des prélèvements aux couleurs des banques, **chèques** par mois prévu.
- **Crédits** : reste dû mois par mois et objectif de date.

## Import des fichiers Excel

À faire une seule fois, sur une base vide (à la place de `charger-modele`) :

```bash
flask --app budget import-excel /chemin/des/fichiers --annee 2026            # aperçu, rien n'est écrit
flask --app budget import-excel /chemin/des/fichiers --annee 2026 --ecrire   # import
```

Le dossier contient les `MOIS_SOLO.xlsx`. L'aperçu liste les mois, les postes avec leur compte et leur catégorie, et les crédits ; l'import s'arrête si le total d'un mois ne correspond pas à celui d'Excel. Les correspondances (comptes, postes renommés, catégories imposées) se règlent dans le bloc `[import]` de `config/settings.toml`.

## Essai en local

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
export BUDGET_DEV=1                      # autorise http://localhost (jamais en production)
.venv/bin/flask --app budget set-password      # 14 caractères minimum
.venv/bin/flask --app budget charger-modele    # postes de config/modele.toml (montants d'exemple)
.venv/bin/flask --app budget run
.venv/bin/python -m pytest                     # tests
```

## Lecture des tickets

Le ticket est lu **dans le navigateur** (tesseract.js, servi par l'appli depuis `budget/static/ocr/`) : la photo n'est envoyée à aucun service de lecture. Si le navigateur n'y arrive pas et que le programme Tesseract est installé sur le serveur (VPS, essai local), c'est lui qui lit. Sinon, la photo est gardée et le montant se saisit à la main.

Les photos sont réduites dans le navigateur, réencodées sans métadonnées, stockées dans la base (table `ticket_photos`) et servies seulement à l'utilisateur connecté. Formats acceptés : JPEG, PNG, WebP, 10 Mo au plus.

## Configuration

| Fichier | Contenu |
|---|---|
| `config/settings.toml` | matelas, seuils des propositions, saison forte, cible 50-30-20, comptes et couleurs, sécurité |
| `config/modele.toml` | modèle de départ (postes, premier mois, crédits), chargé une seule fois |

Après une modification de `settings.toml` : `docker compose restart app`.

## Mise en ligne sur Vercel (hébergement choisi)

L'appli tourne sur Vercel avec une base Postgres hébergée par Neon. Rien n'est à installer sur ton ordinateur.

1. **Créer le projet**. Sur [vercel.com](https://vercel.com), « Add New… → Project », importe le dépôt GitHub `Budget-perso`. Dans les réglages du projet (« Settings → Git »), mets **`claude/personal-budget-app-l2w4bt`** comme branche de production. Laisse « Framework Preset » sur « Other » : `vercel.json` fait le reste.
2. **Ajouter la base**. Onglet « Storage » → « Create Database » → **Neon** (Postgres), région **Europe (Frankfurt)**, offre gratuite. Rattache-la au projet : la variable `DATABASE_URL` est posée toute seule.
3. **Ajouter deux variables** (« Settings → Environment Variables ») :
   - `BUDGET_SECRET_KEY` : une longue suite aléatoire, par exemple 64 caractères tirés d'un gestionnaire de mots de passe. Ne la change plus ensuite (sinon tout le monde est déconnecté, c'est tout).
   - `BUDGET_SETUP_CODE` : un code de ton choix, qui sert **une seule fois** à la première ouverture.
4. **Déployer** (« Deployments → Redeploy »), puis ouvre l'adresse donnée par Vercel :
   - l'écran « Bienvenue » demande le code de mise en route et ton mot de passe (14 caractères au moins) ;
   - active le **code à 6 chiffres** avec une appli d'authentification et range les codes de secours ;
   - « Réglages → Importer mes fichiers Excel » : sélectionne tes 9 fichiers `MOIS_SOLO.xlsx`, vérifie l'aperçu, confirme.
5. Sur le téléphone : ouvre l'adresse puis « Ajouter à l'écran d'accueil ».

Ensuite, chaque mise à jour poussée sur la branche est mise en ligne automatiquement.

**Sauvegarde** : « Réglages → Télécharger une sauvegarde », à faire régulièrement et à garder hors de Vercel. Le fichier contient tout le budget, mais pas les photos des tickets. Neon garde aussi un historique de la base (7 jours sur l'offre gratuite).

**À savoir** : la base gratuite s'endort après quelques minutes sans visite ; la première page met alors quelques secondes à s'afficher.

## Variante : déploiement sur un VPS

Voie alternative, conservée si tu quittes Vercel un jour. Non testée dans un vrai conteneur (pas de Docker dans l'environnement de développement).

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
   # puis, au choix : le modèle d'exemple…
   docker compose exec app flask --app budget charger-modele
   # …ou tes fichiers Excel, copiés dans ../instance/excel (monté dans /data/excel)
   docker compose exec app flask --app budget import-excel /data/excel --annee 2026 --ecrire
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

## Design

Ambiance « Nature », toujours claire, décrite dans [design-system/budget/MASTER.md](design-system/budget/MASTER.md). Le mouvement (`static/app.js`) est une amélioration progressive : tout fonctionne sans JavaScript.

## Tests

```bash
.venv/bin/python -m pytest                                              # SQLite
TEST_DATABASE_URL=postgresql://utilisateur:mdp@hote/base .venv/bin/python -m pytest   # Postgres (base vidée !)
```

## Sécurité

Mot de passe haché (scrypt), blocage après 5 tentatives par quart d'heure, jeton anti-CSRF sur chaque formulaire, cookie de session `Secure` / `HttpOnly`, politique CSP stricte, conteneur en lecture seule sans privilèges. Second facteur (code à 6 chiffres, codes de secours) activable dans les Réglages, et proposé dès la mise en route.
