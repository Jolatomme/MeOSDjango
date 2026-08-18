# Changelog

Tous les changements notables de ce projet sont documentés ici.

## [Unreleased]

### Added
- Suivi « Live » des postes radio en temps réel : nouvel onglet (catégories et circuits) avec classement regroupé « En course / Arrivés / En attente / Terminé », horloge de course depuis le premier départ, chrono individuel défilant depuis le départ, temps « il y a X h / Y min / Z s » et badge En direct/Hors ligne ; rafraîchi par polling JSON 5 s (`live.js`, pause quand l'onglet est caché).
- Un coureur dont l'heure de départ est passée apparaît « En course » même sans poinçon radio (virtuellement en tête), puis le classement live s'établit sur le nombre de postes radio pointés et le temps au dernier poste ; un coureur n'est « Arrivé » que lorsque ses données sont complètes (statut OK et `rt > 0`, carte vidée à la GEC).
- Accès JSON pour le polling : `/api/<cid>/class/<classe>/live/` et `/api/<cid>/course/<hash>/live/` (horloges serveur, postes radio, coureurs annotés).
- Les analyses (superman, performance, régularité, regroupement, lièvre/suiveur, récapitulatif, duel) se calculent **pendant la course** dès les premières arrivées, en ne prenant en compte que les coureurs au statut **OK** (statut attribué par MeOS, puce lue à la GEC) : les coureurs encore en course, non partis (`st = 0`) ou avec un statut non-OK n'apparaissent pas. Tant que la course est en cours, un bandeau « Analyse partielle — N arrivés sur M » informe que les données se complètent au fil des arrivées ; l'export CSV du récapitulatif est disponible pendant la course (lignes OK uniquement, plus de 409).
- Commande `python manage.py simulate_live` : simule un flux MOP temps réel (MOPComplete puis MOPDiff, postes radio, statuts de démonstration DNS/PM/DNF/OK) vers `/mop/update/` pour tester la page Live sans MeOS.
- Temps intermédiaires négatifs (boîtier mal synchronisé / carte SI non effacée) : affichage au lieu d'une erreur 500, avec bannière d'avertissement listant les coureurs concernés (lien vers leur fiche, catégorie et postes au temps négatif — tableau), la ligne « Postes suspectés » et marqueur rouge `(!)` sur chaque tronçon négatif.
- Diagnostic différencié : plusieurs coureurs négatifs au même poste → boîtier mal synchronisé ; temps négatifs sur des postes différents (ou un seul coureur) → carte SI non effacée (effacement de doigts).
- Marquage des coureurs concernés dans les classements (classe, circuit, relais, récapitulatif et fiche coureur) : badge « Temps négatif » et ligne surlignée pour travailler en amont sur le problème.
- Page de compétition (choix d'affichage des catégories) : bannière d'avertissement globale avec la liste des coureurs concernés, et badge rouge sur les cartes des catégories (et circuits) où des temps négatifs ont été relevés, avec le nombre de coureurs affectés.

### Changed
- `results/services.py` : nouvelles fonctions live (`rank_live`, `race_start_clock`, `race_in_progress`, `clock_tenths`, `format_clock`) ; chaque coureur est annoté (`live_group`, `live_rank`, `n_punches`, `last_ctrl`, `last_time`, `last_punch_clock`).
- Analyses pendant la course : suppression du verrou `race_in_progress` sur les 7 vues d'analyse et le CSV (plus de message « Analyse indisponible pendant la course », plus de 409) ; `race_in_progress` est conservé pour le bandeau « Analyse partielle » (compteurs `n_ok`/`n_total` posés par `_partial_analysis_info` dans `results/views.py`). Regroupement, lièvre/suiveur, duel et récapitulatif n'affichent plus que les coureurs OK (`is_ok` et `st > 0`).
- Temps live affichés à la seconde (sans dixième), les écarts « il y a » étant formatés `X h Y min Z s` / `X min Y s` / `X s`.
- `format_time` accepte les valeurs négatives et les préfixe par `-` (ex. `-00:50`).
- `meos_time` renvoie `-` pour les temps négatifs (non classés `rt=-1` inchangés).

### Deprecated
- 

### Removed
- 

### Fixed
- `simulate_live` : temps envoyés dans le mauvais format (heures absolues du jour pour les poinçons radio, au lieu de temps relatifs au départ en 1/10 s) — conforme désormais au format MOP (`st` en heure murale 1/10 s, `rt` et poinçons relatifs en 1/10 s).
- `simulate_live` écrivait les heures de départ en UTC (`timezone.now()`, `USE_TZ`) alors que les vues du site utilisent l'heure locale (`datetime.now()`) : le chronomètre de course affichait un décalage de ~2 h — écriture désormais en heure locale.
- Page Live : le temps « il y a » se figeait entre deux polls et s'incrémentait par pas de 5 s (dixièmes de seconde confondus avec des secondes) — tick client à 1 s entre deux polls, sans dixième.
- Erreur 500 sur les pages classe/circuit, coureur, relais, récapitulatif et duel lorsqu'un temps intermédiaire ou le tronçon arrivée était négatif.
- Admin : « Supprimer les données MOP » supprime aussi la configuration de la compétition (`CompetitionConfig`) — la compétition disparaît de la liste au lieu d'y rester avec son CID en guise de nom. Le nom de la compétition est désormais capturé avant la suppression (message de confirmation exact).
- Admin : purge automatique des `CompetitionConfig` orphelines (cid absent de `mopCompetition`) à l'ouverture de la liste des configurations.

### Security
- 

## [0.1.0] - 2026-04-01
### Added
- Initial release.
