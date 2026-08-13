# Changelog

Tous les changements notables de ce projet dont documentés ici.

## [Unreleased]

### Added
- Temps intermédiaires négatifs (boîtier mal synchronisé / carte SI non effacée) : affichage au lieu d'une erreur 500, avec bannière d'avertissement listant les coureurs concernés (lien vers leur fiche, catégorie et postes au temps négatif — tableau), la ligne « Postes suspectés » et marqueur rouge `(!)` sur chaque tronçon négatif.
- Diagnostic différencié : plusieurs coureurs négatifs au même poste → boîtier mal synchronisé ; temps négatifs sur des postes différents (ou un seul coureur) → carte SI non effacée (effacement de doigts).
- Marquage des coureurs concernés dans les classements (classe, circuit, relais, récapitulatif et fiche coureur) : badge « Temps négatif » et ligne surlignée pour travailler en amont sur le problème.
- Page de compétition (choix d'affichage des catégories) : bannière d'avertissement globale avec la liste des coureurs concernés, et badge rouge sur les cartes des catégories (et circuits) où des temps négatifs ont été relevés, avec le nombre de coureurs affectés.

### Changed
- `format_time` accepte les valeurs négatives et les préfixe par `-` (ex. `-00:50`).
- `meos_time` renvoie `-` pour les temps négatifs (non classés `rt=-1` inchangés).

### Deprecated
- 

### Removed
- 

### Fixed
- Erreur 500 sur les pages classe/circuit, coureur, relais, récapitulatif et duel lorsqu'un temps intermédiaire ou le tronçon arrivée était négatif.

### Security
- 

## [0.1.0] - 2026-04-01
### Added
- Initial release.
