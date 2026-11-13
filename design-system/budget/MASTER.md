# Système de design — Budget, ambiance « Nature »

Référence unique pour le style des écrans. Ambiance choisie par Fred le 2026-11-13 parmi trois
maquettes (Douceur, Nature, Nuit calme). Les valeurs vivent dans `budget/static/style.css`
(variables en tête de fichier) ; le mouvement dans `budget/static/app.js`.

## Intention

Une appli où l'on peut passer du temps sans stress : tons de sauge et d'argile, aplats, formes
rondes, rien qui brille ni qui clignote. Le mouvement accompagne, il ne distrait pas.

## Origine

Pistes trouvées avec le skill `ui-ux-pro-max` (`.claude/skills/ui-ux-pro-max/`) :

```bash
S=.claude/skills/ui-ux-pro-max/scripts/search.py
python3 $S "calm soft relaxing wellness friendly" --domain style     # Soft UI Evolution, Nature Distilled
python3 $S "soft organic warm cozy rounded" --domain style           # Nature Distilled, Organic Biophilic
python3 $S "micro interactions easing duration feedback" --domain ux
```

Retenu : « Nature Distilled » / « Organic Biophilic » (tons terreux atténués, coins de 16 à 24 px,
courbes d'arrivée naturelles). Écarté : textures de grain et parallaxe (décor sans utilité ici),
le beige crème et la police à empattements (remplacés par une base sauge et une police sans
empattements, plus lisible pour des chiffres).

## Jetons

| Rôle | Valeur | Contraste |
|---|---|---|
| Fond | `#EDF1E6` | |
| Carte | `#FBFCF7` | |
| Texte | `#22301F` | 12,1:1 sur le fond |
| Texte secondaire | `#57664F` | 5,4:1 sur le fond, 4,8:1 sur le bandeau |
| Bandeau de l'épargne | `#DDE8CC` | |
| Vert feuille (boutons, barres, « fait ») | `#3F6B3A` | blanc dessus : 6,2:1 |
| Argile (dépassement, rappel) | texte `#96481F`, aplat `#B8623A`, fond `#F7E7DC` | 5,4:1 |
| Rouge (risque de découvert seulement) | `#A8261E` sur `#FBE9E6` | 6,1:1 |
| Trait | `#D9E0CD` | |

- **Toujours clair** : pas de thème sombre, quel que soit le réglage de l'appareil (décision de Fred).
- **Police** : Figtree 400 à 800, hébergée dans `static/fonts/` (licence OFL). Chiffres tabulaires.
- **Formes** : cartes 22 px, petits blocs 14 px, boutons et étiquettes en pilule. Pas d'ombre.
- **Espacement** : rythme 4 / 8 px (4, 8, 12, 16, 24, 32).
- Les couleurs des banques ne font pas partie du système : elles se règlent dans `config/settings.toml`.

## Ton et couleur

- **Le rouge est réservé au vrai risque** : matelas dépassé, budget supérieur au salaire.
- Un dépassement de poste, un chèque oublié, un crédit en retard sur son objectif : **argile**, et une phrase posée
  (« Le matelas a absorbé 77 €. Tout va bien, il est là pour ça. »).
- Une proposition d'ajustement se présente comme une idée : « Oui, ajuster » / « Plus tard ».
- L'écran du mois s'ouvre sur l'épargne du mois, en grand.
- Un écart porte toujours son signe (`+` ou `−`), un message porte une icône : la couleur ne fait que renforcer.

## Mouvement

| Élément | Comportement | Durée |
|---|---|---|
| Changement de page | Fondu enchaîné (`@view-transition`) | 260 ms |
| Blocs de la page | Arrivent en cascade, de 12 px plus bas | 600 ms, décalage de 50 ms |
| Montants clés (`data-count`) | Montent de 0 à leur valeur | 1,2 s |
| Anneau du matelas (`data-ring`) | Se remplit | 1,4 s |
| Barres d'avancement (`data-bar`) | Se remplissent l'une après l'autre | 0,9 s |
| Virement coché | Petit rebond, ligne qui s'estompe, sans rechargement | 380 ms |
| Boutons | Se tassent légèrement à l'appui | 180 ms |
| Message de confirmation | S'efface seul après 4,5 s | 600 ms |

- Courbe unique : `cubic-bezier(.22, 1, .36, 1)` (arrivée douce).
- **Amélioration progressive** : la page est complète et au repos sans script ; le serveur rend toujours la valeur finale.
- `prefers-reduced-motion` coupe tout mouvement.

## Contraintes techniques

- CSS simple, pas de dépendance, pas de service tiers.
- Pas de style ni de script en ligne dans les gabarits (CSP `default-src 'self'`) ; `app.js` est un fichier local.
- Cibles tactiles de 44 px au moins, focus visible, téléphone d'abord.
