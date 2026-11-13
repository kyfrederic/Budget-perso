# Système de design — Budget

Référence unique pour le style des écrans. Établi avec le skill `ui-ux-pro-max`
(`.claude/skills/ui-ux-pro-max/`), puis adapté aux contraintes du projet.
Les valeurs vivent dans `budget/static/style.css` (variables CSS en tête de fichier).

## Requêtes d'origine

```bash
S=.claude/skills/ui-ux-pro-max/scripts/search.py
python3 $S "personal finance budget tracker dashboard" --design-system -p "Budget" --density 7 --variance 3 --motion 2
python3 $S "financial dashboard data numbers tabular" --domain typography
python3 $S "banking fintech trust light" --domain color
python3 $S "personal finance budget app" --domain product
python3 $S "progress budget remaining gauge" --domain chart
python3 $S "form input labels inline validation" --domain ux
python3 $S "data table mobile responsive" --domain ux
```

## Ce qui est retenu

| Sujet | Recommandation du skill | Application |
|---|---|---|
| Style | **Minimalism & Swiss Style** : grille, hiérarchie typographique nette, peu d'effets, contraste élevé | Bordures fines, pas d'ombre, rayons de 8 px, chiffres mis en avant |
| Couleurs | « Calm blue + success green + alert red » ; bleu `#1E40AF`, bleu secondaire `#3B82F6`, vert `#059669`, rouge `#DC2626` ; fond sombre `#0F172A`, carte `#192134` | Thème sombre repris tel quel ; thème clair pris dans la palette « Banking » du skill (fond `#F8FAFC`, carte `#FFFFFF`, texte `#020617`, texte secondaire `#475569`, bordure `#E2E8F0`) |
| Typographie | Paire « Financial Trust » : **IBM Plex Sans** (titres et texte) | Police hébergée dans `static/fonts/` (licence OFL), chiffres tabulaires |
| Densité | 7/10 : échelle d'espacement 8 → 32 px | Rythme 4 / 8 px |
| Matelas | Barre de progression avec le nombre et la cible en texte à côté ; la couleur seule ne suffit pas | `<progress>` + montant + mention « n/n réels saisis » |
| Tableaux | Mobile d'abord ; cartes ou défilement horizontal sur téléphone | Lignes du budget en cartes sur téléphone, en tableau à partir de 760 px |
| Formulaires | Libellé visible pour chaque champ, jamais le seul texte d'exemple | Libellés au-dessus des champs ; `aria-label` sur les champs du tableau |
| Navigation | 5 destinations au plus dans une barre basse sur téléphone | Barre basse : Mois, Calendrier, Analyse, Chèques, Plus ; barre haute sur PC |
| Icônes | SVG d'une seule famille, pas d'émoji | Tracés au trait de 2 px, dans `templates/_icons.html` |
| Interaction | Cibles ≥ 44 px, survol 150–250 ms, focus visible, `prefers-reduced-motion` | Appliqué partout |

## Ce qui est écarté, et pourquoi

- **Caveat + Quicksand** (typographie proposée par la génération automatique) : écriture manuscrite, hors sujet pour un outil de chiffres. Remplacée par la paire « Financial Trust » trouvée avec une recherche ciblée.
- **Glassmorphism + OLED** (style principal du type « Personal Finance Tracker ») : flous et transparences nuisent à la lecture des montants. Le style secondaire recommandé (Minimalism & Swiss) est retenu.
- **Modèle de page « Product Demo », animation GSAP au défilement** : recommandations pour une page vitrine, sans objet ici.
- **Tailwind, polices Google en ligne** : le projet reste en CSS simple, sans service tiers, avec une politique CSP stricte.
- **Vert `#059669` pour le texte** : contraste de 3,8:1 sur blanc, insuffisant. Le texte utilise `#047857` (5,5:1) ; `#059669` sert aux aplats.

## Jetons

| Rôle | Clair | Sombre |
|---|---|---|
| Fond | `#F8FAFC` | `#0F172A` |
| Carte | `#FFFFFF` | `#192134` |
| Texte | `#020617` | `#F8FAFC` |
| Texte secondaire | `#475569` | `#94A3B8` |
| Bordure | `#E2E8F0` | `#2B3650` |
| Bordure de champ | `#7C8BA1` | `#64748B` |
| Primaire (boutons, onglet actif) | `#1E40AF` sur blanc | `#3B82F6`, texte `#020617` |
| Lien | `#1E40AF` | `#93C5FD` |
| Positif (épargne, économie) | `#047857` | `#34D399` |
| Négatif (dépassement, alerte) | `#DC2626` | `#F87171` |
| Attention | `#A16207` | `#FBBF24` |

Les couleurs des banques ne font pas partie du système : elles se règlent dans `config/settings.toml`.

## Règles

- Un montant est toujours aligné à droite, en chiffres tabulaires.
- Un écart porte toujours son signe (`+` ou `−`) : la couleur ne fait que le renforcer.
- Un message d'alerte porte une icône en plus de sa couleur.
- Pas de style ni de script en ligne dans les gabarits (CSP).
