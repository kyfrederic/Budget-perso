# Appli de gestion de budget personnel — Cahier des charges

> Remplace les fichiers Excel mensuels (`MOIS_SOLO.xlsx`).
> Statut : issu de la session de cadrage du 2026-11-13. Les points marqués **À CONFIRMER** n'ont pas été tranchés.

## 1. Objectif

Une application web personnelle (PC + téléphone) pour :
1. Planifier chaque mois le budget et les virements à faire vers chaque compte.
2. Suivre le réel par rapport au prévu et proposer des ajustements.
3. Simuler l'impôt sur le revenu du foyer (avec scénarios sur le nombre d'enfants).
4. Avoir une vue globale : ce qui rentre, ce qui sort, ce que je dois.
5. Recevoir chaque mois une analyse du mois écoulé avec des axes d'amélioration.

## 2. Périmètre et utilisateurs

- **Un seul utilisateur** (Fred). Pas de compte pour Laetitia en V1.
- Les montants de Laetitia sont saisis **à titre d'information** (part commune) ; seuls les montants de Fred entrent dans les calculs.
- Le modèle de données doit permettre d'ajouter des utilisateurs plus tard.

## 3. Modèle métier (tel qu'utilisé aujourd'hui dans Excel)

Principe « paie-toi d'abord » avec enveloppes par compte :

1. **Salaire reçu − budget fixé = différence virée en épargne** dès réception.
2. Le budget est réparti par **poste** (emprunt immobilier, nourriture, électricité, Navigo, abonnements, crédits, épargne, etc.). Chaque poste a un **compte de destination**.
3. Les postes d'un même compte sont additionnés en **un virement** par compte :
   - Boursorama (prélèvements : factures, crédits, abonnements…)
   - Compte joint (courses)
   - Revolut (argent de poche, 200 €)
   - N26 (matelas, cantine du boulot)
   - LCL (assurances, carburant, épargne, emprunt…)
4. Un **matelas de 500 €** (poste « Réserve », compte N26) fait partie du budget chaque mois et absorbe les écarts entre prévu et réel.
5. Autres onglets Excel à reprendre : répartition 50-30-20, suivi des crédits (avec objectif de date), suivi orthodontie (devient un « projet d'achat », voir section 10 bis).

### Règles de fin de mois (validées)

Le matelas est un **montant fixe de 500 € alloué chaque mois** ; il ne s'accumule pas d'un mois à l'autre.

- **Dépassement** d'un poste → pris dans le matelas.
- **Fin de mois** : tout ce qui reste du matelas part **immédiatement sur le compte d'épargne**. S'il ne reste rien, rien n'est viré.
- **Mois suivant** : le matelas est **renouvelé à 500 €** depuis le budget, quel que soit le reste du mois précédent.
- L'épargne du mois = (salaire − budget) + reste du matelas.
- Alerte si les dépassements du mois dépassent 500 € (le matelas ne suffit plus, risque de découvert).

## 4. Saisie du réel (validé)

- **V1 : un total réel par poste et par mois** (option A). Pas de saisie transaction par transaction.
- Import CSV des banques et catégorisation automatique : **plus tard** (V1.5 ou après).
- Limite assumée : on voit qu'un poste dérape, pas pourquoi.

## 5. Nouveau mois (validé)

- L'appli **copie le mois précédent** (postes, montants, comptes).
- Fred saisit : salaire net, **net imposable**, montant du prélèvement à la source, ajustements.
- L'appli génère la **liste des virements** par compte et le montant d'épargne.
- **Migration Excel :** octobre sert de modèle de départ ; import unique depuis les 9 fichiers des salaires mensuels et des soldes de crédits. Les prévus passés ne sont pas importés (quasi identiques). Les fichiers n'ont pas d'historique de réel.

## 6. Propositions d'ajustement du budget (V1, règles)

- Pas de proposition avant **2 mois de réel** saisis.
- Un poste qui entame le matelas **2 mois de suite** → proposition d'augmenter son prévu vers la valeur réelle.
- Les propositions sont **acceptées ou refusées par Fred**, jamais appliquées automatiquement.
- **Seuils (validés, dans un fichier de configuration modifiable)** : aucune proposition sous 10 % **et** sous 10 € d'écart ; déclenchement après 2 mois de suite au-dessus du seuil ; nouvelle valeur = médiane des 3 derniers mois, arrondie aux 5 € ; postes contractuels (emprunt, assurances…) exclus.
- **Saisonnalité** : certains postes varient fortement selon la saison (électricité, énergie : +50 € voire le double en hiver). Pour ces postes, marqués « saisonniers » :
  - **Décision de Fred : un montant fixe toute l'année** (ex. électricité à 150 € chaque mois), réajusté selon le réel. Pas de profil mensuel ni de lissage.
  - L'économie des mois calmes n'est pas perdue : elle retourne dans le matelas puis part en épargne (règle du matelas).
  - Pour éviter l'effet yo-yo (baisse au printemps, hausse à l'automne), l'appli **ne propose pas de baisse** pour un poste saisonnier ; elle propose seulement une **hausse** si le réel dépasse durablement le montant fixé.
  - **Alerte préventive** à l'approche de la saison forte (« l'hiver arrive, électricité habituellement plus haute : vérifier que 150 € suffisent »), en s'appuyant sur le même mois de l'année précédente quand l'historique existe.
  - Fred peut modifier ce montant fixe à tout moment.

## 7. Analyse mensuelle (V1, règles)

- Générée en fin de mois ou début du suivant, avant le nouveau mois.
- Contenu : prévu vs réel par poste, état du matelas, répartition 50-30-20, taux d'épargne, évolution des crédits, pistes (épargner/investir plus, réajuster, gagner en pouvoir d'achat).
- **Moteur à règles**, sans service externe. Une reformulation par IA (avec totaux anonymisés) est envisagée dans une version ultérieure.

## 8. Simulateur d'impôt (V2)

- Base : **net imposable cumulé** + moyenne des mois saisis pour les mois restants + **salaire annuel approximatif de Laetitia** (configuré en début d'année).
- **Parts** : couple marié + curseur « nombre d'enfants » (1, 2, 3…) pour comparer les scénarios.
- Comparaison avec le **prélèvement à la source déjà payé** → « reste à payer » ou « remboursement estimé ».
- **Réductions et crédits d'impôt optionnels**, ajoutables à tout moment avec recalcul immédiat : dons, frais de garde (règles et plafonds distincts, dépendent de l'âge de l'enfant), champ libre « autres réductions ». Chaque ligne est supprimable.
- Barème, taux et plafonds dans un **fichier de configuration** mis à jour chaque année et vérifiés à la mise en œuvre.
- Précision visée : estimation à quelques dizaines d'euros, pas une déclaration officielle.
- Acompte de début d'année sur certains crédits (garde) à prendre en compte dans la comparaison.

## 9. Dettes, impayés, vue globale (V3)

- Liste **« À payer »** : libellé, montant, échéance, statut payé/non payé, sans lien bancaire.
- **Crédits** : reste dû, objectif de date (ex. renouvelable soldé avant le 31/12/2026) ; l'appli dit si le rythme actuel permet de tenir la date.
- **Vue globale** : revenus, dépenses, épargne, total dû (impayés + crédits), impôt estimé.
- Échéances à moins de 7 jours en haut de l'accueil. Pas de notifications mail/push demandées.

## 10. Calendrier mensuel

- Chaque poste a un **jour de prélèvement** et un compte ; le calendrier se remplit automatiquement.
- Chaque prélèvement prend la **couleur de la banque** (une couleur par compte).
- **Chèques** : une ligne = montant, bénéficiaire, **mois prévu du dépôt**, note. Pas de date exacte.
  - Le mois concerné affiche « chèque à passer : X € », retranché du disponible.
  - Chèque toujours « en attente » après son mois → signalé en rouge (« as-tu oublié de le déposer ? »).
  - Passage à « débité » d'un clic.
- Solde projeté par compte avec alerte de découvert : **version ultérieure** (suppose de saisir les soldes réels).

## 10 bis. Projets d'achat (V2)

L'onglet « Orthodontie » d'Excel est un exemple de projet d'achat ; une télévision en est un autre. Un seul mécanisme couvre deux cas : **épargner avant d'acheter** et **étaler un paiement** (avec remboursements qui réduisent le reste à charge).

- Saisie : nom, montant total, remboursements attendus (optionnel, ex. mutuelle), période (nombre de mois ou date cible), compte concerné.
- Mensualité calculée : (montant − remboursements) ÷ nombre de mois.
- La mensualité est ajoutée **automatiquement comme poste du budget** chaque mois pendant la durée du projet, avec son compte de destination. Elle apparaît dans les virements, et disparaît à la fin du projet.
- Barre de progression (déjà mis de côté ou payé) et date de fin.
- Avant validation, l'appli indique si le budget du mois a encore la marge pour absorber la mensualité.
- Un seul écran pour les deux cas ; pas de distinction « épargner » / « payer en plusieurs fois ».

## 11. Technique et hébergement

- Hébergement : **VPS** (OVH ou autre), accès web sur PC et téléphone (page adaptée à l'écran, installable sur l'écran d'accueil).
- Stack : **laissée au choix de Claude Code**. Contraintes : securisé, peu de dépendances, un seul utilisateur, déploiement simple sur VPS (idéalement un conteneur et HTTPS automatique), sauvegarde simple, paramètres en fichiers de configuration. Piste initiale : Python (Flask) + SQLite + pages côté serveur.
- Exigences :
  - HTTPS obligatoire, mot de passe solide (idéalement 2e facteur), serveur durci (SSH par clé, pare-feu, mises à jour).
  - **Sauvegarde automatique nocturne hors du VPS**, avec test de restauration.
  - Paramètres (barème, seuils, couleurs de banques, matelas) dans des fichiers de configuration.
- Données financières : pas de service tiers en V1.

## 12. Découpage

| Version | Contenu |
|---|---|
| **V1** | Budget mensuel (modèle, copie du mois, virements par compte, règles du matelas), réel par poste, propositions d'ajustement, analyse mensuelle à règles, calendrier des prélèvements et chèques, import initial des Excel |
| **V2** | Simulateur d'impôt (parts, prélèvement à la source, réductions optionnelles), projets d'achat |
| **V3** | Liste « À payer », suivi des crédits avec objectifs, vue globale |
| Plus tard | Import CSV bancaire, détail des transactions, solde projeté, analyse par IA, accès pour Laetitia |

## 13. Risques et points ouverts

- Sans historique de réel, les propositions démarrent après 2 mois de saisie.
- La saisie manuelle du réel demande de la discipline : si elle est abandonnée, les propositions et l'analyse perdent leur valeur.
- Le simulateur d'impôt est exigeant (barème annuel, cas particuliers, plafonnements) : estimation, pas calcul officiel.
- Le salaire varie d'un mois à l'autre : l'extrapolation par moyenne peut être imprécise (primes, variations).
- Postes saisonniers : sans historique d'un an, la première année repose sur le montant fixe choisi à la main ; l'hiver peut consommer tout le matelas de 500 € si le montant fixé est trop bas.
- Sécurité du VPS et sauvegardes à prévoir dès la V1.

## 13 bis. Décisions de la session du 2026-11-13 (clarifications avant la V1)

| Sujet | Décision |
|---|---|
| Seuil des propositions | Un écart ne compte que s'il dépasse **10 % ET 10 €**. |
| Économies d'un poste | Elles **compensent** les dépassements : reste du matelas = 500 € − dépassements + économies. L'alerte se déclenche quand ce reste devient négatif. |
| Propositions de baisse | **Oui** pour les postes ni saisonniers ni contractuels, avec les mêmes seuils. |
| Proposition acceptée | Le nouveau prévu s'applique au **mois en cours**, puis il est copié dans les mois suivants. |
| Rattachement du salaire | Le salaire reçu fin du mois M finance le budget du **mois M+1**. |
| Comptes | Salaire sur **LCL** ; matelas sur **N26** ; épargne (salaire − budget, puis reste du matelas) sur le **Livret A LCL**. |
| Second facteur | **Non** en V1 : mot de passe long + limitation des tentatives. |
| 50-30-20 | Classement repris de l'onglet Excel, modifiable poste par poste. |
| Laetitia | Colonne facultative **par poste**, affichée, jamais additionnée. |
| Fichiers Excel | Fournis par Fred pendant une session, **jamais commités** (dossier `import/` ignoré par git). Le dépôt ne contient que du code et des montants d'exemple. |

## 13 ter. État de la V1

- Stack : Flask + SQLite + pages côté serveur (voir `README.md` pour lancer, configurer et déployer).
- Règles métier dans `budget/rules.py` (fonctions pures, testées dans `tests/test_rules.py`). Montants stockés en centimes.
- **Reste à faire en V1** : import des Excel (en attente des fichiers), premier déploiement réel sur le VPS avec test de restauration.

## 14. Prochaines étapes

1. Dessiner les écrans de la V1 (mois en cours, nouveau mois, calendrier, analyse).
2. Écrire le schéma de données (postes dont indicateur « saisonnier », comptes, mois, réel, chèques, paramètres).
3. Écrire le script d'import des Excel (salaires, crédits, modèle d'octobre).
4. Mettre en place le VPS, HTTPS et les sauvegardes avant de saisir de vraies données.
