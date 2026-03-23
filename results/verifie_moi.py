"""
verifie_moi.py — Génération du fichier CSV pour l'application Android « O Checklist »
(publiée en français sous le nom « Vérifie moi »).

L'application est utilisée au départ des compétitions d'orientation pour cocher
les coureurs partants et détecter les DNS. Elle importe un fichier CSV au format :

    Nom, Club, Catégorie, Dossard, HeureDepart, NuméroPuce, NomDepart

Une ligne par coureur, triées par heure de départ croissante.
Les champs obligatoires sont : Nom, Club, Catégorie, HeureDepart.
Les autres champs peuvent être vides (les virgules doivent quand même être présentes).

Format heure : hh:mm:ss  (ex : 09:10:00)
Encodage : UTF-8
Séparateur : virgule

Référence : https://stigning.se/startclock/template.html
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from .meos_checker import parse_meosxml


# ─── Mapping catégorie → nom de départ ───────────────────────────────────────
#
# Correspondance entre le nom de la catégorie MeOS et le nom du poste de départ
# utilisé sur le terrain. Ce mapping est appliqué à la 7ème colonne du CSV
# (NomDepart), qui permet à l'application O Checklist de regrouper les coureurs
# par zone de départ.
#
# Les clés sont les noms de catégorie tels qu'ils apparaissent dans MeOS
# (sensible à la casse).

CATEGORY_START_MAP: dict[str, str] = {
    # ── Départ A ──────────────────────────────────────────────────────────────
    'H20':  'A',
    'H21':  'A',
    'H35':  'A',
    # ── Départ B ──────────────────────────────────────────────────────────────
    'D21':  'B',
    'H18':  'B',
    # ── Départ B bis ──────────────────────────────────────────────────────────
    'H40':  'B bis',
    'H45':  'B bis',
    # ── Départ C ──────────────────────────────────────────────────────────────
    'D18':  'C',
    'D20':  'C',
    'D35':  'C',
    'H50':  'C',
    # ── Départ C bis ──────────────────────────────────────────────────────────
    'D40':  'C bis',
    'D45':  'C bis',
    'H55':  'C bis',
    # ── Départ D ──────────────────────────────────────────────────────────────
    'D50':  'D',
    'D55':  'D',
    'D60':  'D',
    'H60':  'D',
    'H65':  'D',
    # ── Départ E ──────────────────────────────────────────────────────────────
    'D65':  'E',
    'D70':  'E',
    'D75':  'E',
    'D80':  'E',
    'D85':  'E',
    'H70':  'E',
    'H75':  'E',
    'H80':  'E',
    'H85':  'E',
    # ── Départ F ──────────────────────────────────────────────────────────────
    'D16':  'F',
    'H16':  'F',
    # ── Départ G ──────────────────────────────────────────────────────────────
    'D14':  'G',
    'H14':  'G',
    # ── Départ H ──────────────────────────────────────────────────────────────
    'D12':  'H',
    'H12':  'H',
    # ── Départ Vert ───────────────────────────────────────────────────────────
    'D10':  'Vert',
    'H10':  'Vert',
    # ── Jalonné ───────────────────────────────────────────────────────────────
    'Jalonné': 'Jalonné',
}


def get_start_name(class_name: str) -> str:
    """Retourne le nom du poste de départ pour une catégorie donnée.

    La recherche est d'abord tentée avec le nom exact, puis avec le nom
    tronqué aux premiers caractères alphanumériques (pour gérer les variantes
    comme 'H21E', 'H21A', 'D21L'…).

    Returns:
        Le nom du départ (ex: 'A', 'B bis', 'Vert') ou '' si inconnu.
    """
    if not class_name:
        return ''

    # Correspondance exacte
    if class_name in CATEGORY_START_MAP:
        return CATEGORY_START_MAP[class_name]

    # Correspondance sur le préfixe (ex: 'H21E' → cherche 'H21')
    # On extrait la lettre initiale + les chiffres qui suivent
    import re
    m = re.match(r'^([A-Za-z]+\d+)', class_name)
    if m:
        prefix = m.group(1)
        if prefix in CATEGORY_START_MAP:
            return CATEGORY_START_MAP[prefix]

    return ''


# ─── Résultat de la génération ────────────────────────────────────────────────

@dataclass
class RunnerRow:
    """Une ligne du CSV (un coureur)."""
    name:       str
    club:       str
    cls:        str
    bib:        str
    start_time: str   # format hh:mm:ss, toujours renseigné (filtrage en amont)
    card_no:    str
    start_name: str   # nom du poste de départ, dérivé de la catégorie


@dataclass
class CsvResult:
    """Résultat de la génération CSV."""
    csv_content:      str
    rows:             list[RunnerRow]   # utilisé pour la prévisualisation dans le template
    n_skipped:        int               # coureurs ignorés (sans heure de départ)
    competition_name: str               # nom de la compétition (pour le nom du fichier)

    @property
    def n_runners(self) -> int:
        return len(self.rows)

    @property
    def n_with_card(self) -> int:
        return sum(1 for r in self.rows if r.card_no)


# ─── Formatage de l'heure ─────────────────────────────────────────────────────

def _fmt_hms(total_seconds: int) -> str:
    """Convertit des secondes depuis minuit en 'hh:mm:ss'."""
    total_seconds = total_seconds % 86400   # gérer le passage de minuit
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f'{h:02d}:{m:02d}:{s:02d}'


# ─── Génération ───────────────────────────────────────────────────────────────

def generate_verifie_moi_csv(xml_bytes: bytes) -> CsvResult:
    """Parse un fichier .meosxml et génère le CSV pour O Checklist / Vérifie moi.

    Règles d'inclusion :
      - Les vacants (nom = 'vacant') sont exclus.
      - Les coureurs sans heure de départ sont exclus : ils partent en parallèle
        avec un autre dispositif et ne doivent pas figurer dans ce CSV.
      - Les coureurs restants sont triés par heure de départ croissante.

    La colonne NomDepart est remplie automatiquement à partir du mapping
    CATEGORY_START_MAP (catégorie → nom du poste de départ).

    Si le club d'un coureur n'est pas renseigné dans le fichier MeOS,
    la valeur 'Pas de club' est utilisée dans le CSV.

    Args:
        xml_bytes: contenu brut du fichier .meosxml MeOS.

    Returns:
        CsvResult contenant le CSV prêt à télécharger, les lignes pour
        prévisualisation, et le nombre de coureurs ignorés (sans heure).

    Raises:
        ValueError: si le XML est invalide.
    """
    zero_time, competition_name, _, _, _, categories, clubs, runners = parse_meosxml(xml_bytes)

    rows: list[RunnerRow] = []
    n_skipped = 0

    for r in runners:
        # Exclure les vacants
        if r.name.strip().lower() == 'vacant':
            continue

        # Exclure les coureurs sans heure de départ (départ en parallèle)
        if r.start is None:
            n_skipped += 1
            continue

        club_name  = clubs[r.club_id].name        if r.club_id  and r.club_id  in clubs      else 'Pas de club'
        class_name = categories[r.class_id].name   if r.class_id and r.class_id in categories else ''

        rows.append(RunnerRow(
            name       = r.name,
            club       = club_name,
            cls        = class_name,
            bib        = '',
            start_time = _fmt_hms(zero_time + r.start),
            card_no    = r.card_no or '',
            start_name = get_start_name(class_name),
        ))

    # Tri par heure de départ croissante
    rows.sort(key=lambda r: r.start_time)

    # Génération du CSV
    output = io.StringIO()
    output.write('// O Checklist / Vérifie moi — généré depuis MeOS\n')
    output.write('// @colDefs: Nom*, Club*, Catégorie*, Dossard, Heure*, Puce, Départ\n')

    writer = csv.writer(output, delimiter=',', lineterminator='\n')
    for row in rows:
        writer.writerow([
            row.name, row.club, row.cls,
            row.bib, row.start_time, row.card_no, row.start_name,
        ])

    return CsvResult(csv_content=output.getvalue(), rows=rows, n_skipped=n_skipped,
                   competition_name=competition_name)
