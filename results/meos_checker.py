"""
meos_checker.py — Vérificateur de conformité réglementaire pour les fichiers MeOS.

Analyse un fichier .meosxml et vérifie 8 règles :

  Règles de tirage :
    1. Aucun club n'a deux coureurs consécutifs sur le même circuit.
    2. Les catégories d'un même circuit forment chacune un bloc contigu.
    3. Pas de premier poste commun entre deux circuits différents.
    4. Regroupements des catégories sur des plages continues.

  Règles de complétude des données :
    5. Tous les postes ont des coordonnées <xpos> et <ypos>.
    6. Aucun circuit n'est vide (sans postes).
    7. Aucune catégorie n'est vide (sans coureurs).
    8. Chaque coureur a : un circuit, une catégorie, un numéro de puce (CardNo),
       une heure de départ, et un identifiant unique.

Toutes les fonctions sont pures (sans accès DB ni effet de bord HTTP).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional

from django.utils.translation import gettext as _
from django.utils.translation import ngettext


# ─── Modèles de données ────────────────────────────────────────────────────────

@dataclass
class Control:
    id: str
    number: str      # numéro lisible (champ <Numbers>)
    has_xpos: bool
    has_ypos: bool


@dataclass
class Course:
    id: str
    name: str
    controls: list[int]   # IDs des postes dans l'ordre


@dataclass
class Category:
    id: str
    name: str
    course_id: str
    first_start: Optional[int]
    start_interval: Optional[int]


@dataclass
class Runner:
    id: str
    name: str
    start: Optional[int]
    club_id: Optional[str]
    class_id: Optional[str]
    card_no: Optional[str]


@dataclass
class Club:
    id: str
    name: str


@dataclass
class Violation:
    description: str
    runners: list[str] = field(default_factory=list)
    context: str = ''


@dataclass
class RuleResult:
    rule_id: str
    title: str
    status: str          # 'ok' | 'warning' | 'error'
    summary: str
    violations: list[Violation] = field(default_factory=list)
    num: int = 0         # numéro d'affichage (1‑8)


@dataclass
class CheckReport:
    competition_name: str
    competition_date: str
    zero_time: int
    n_runners: int
    n_vacants: int
    n_no_start: int
    n_classes: int
    n_courses: int
    results: list[RuleResult] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(r.status == 'error' for r in self.results)

    @property
    def has_warnings(self) -> bool:
        return any(r.status == 'warning' for r in self.results)


# ─── Formatage des heures ──────────────────────────────────────────────────────

def _fmt_time(seconds: int, zero_time: int = 0) -> str:
    total = zero_time + seconds
    h = (total // 3600) % 24
    m = (total % 3600) // 60
    return f"{h:02d}:{m:02d}"


# ─── Parsing ──────────────────────────────────────────────────────────────────

def parse_meosxml(xml_bytes: bytes) -> tuple[
    int, str, str,
    dict[str, Control],
    dict[str, Course],
    dict[str, Category],
    dict[str, Club],
    list[Runner],
]:
    """Parse un fichier .meosxml MeOS.

    Returns:
        (zero_time, competition_name, competition_date,
         controls, courses, categories, clubs, runners)

    Raises:
        ValueError si le XML est invalide.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError(_("XML invalide : %(exc)s") % {"exc": exc}) from exc

    comp_name     = root.findtext('Name', '')
    comp_date     = root.findtext('Date', '')
    try:
        zero_time = int(root.findtext('ZeroTime', '0'))
    except (ValueError, TypeError):
        zero_time = 0

    # ── Postes ────────────────────────────────────────────────────────────────
    controls: dict[str, Control] = {}
    for el in root.findall('.//ControlList/Control'):
        cid    = el.findtext('Id', '').strip()
        number = el.findtext('Numbers', cid).strip()
        xpos   = el.findtext('.//xpos', '').strip()
        ypos   = el.findtext('.//ypos', '').strip()
        if cid:
            controls[cid] = Control(
                id=cid, number=number,
                has_xpos=bool(xpos), has_ypos=bool(ypos),
            )

    # ── Circuits ──────────────────────────────────────────────────────────────
    courses: dict[str, Course] = {}
    for el in root.findall('.//CourseList/Course'):
        cid      = el.findtext('Id', '').strip()
        name     = el.findtext('Name', '').strip()
        ctrl_str = el.findtext('Controls', '')
        ctls = [
            int(c.strip())
            for c in ctrl_str.rstrip(';').split(';')
            if c.strip()
        ]
        if cid:
            courses[cid] = Course(id=cid, name=name, controls=ctls)

    # ── Catégories ────────────────────────────────────────────────────────────
    categories: dict[str, Category] = {}
    for el in root.findall('.//ClassList/Class'):
        cid       = el.findtext('Id', '').strip()
        name      = el.findtext('Name', '').strip()
        course_id = el.findtext('Course', '').strip()
        fs_str    = el.findtext('.//FirstStart', '').strip()
        si_str    = el.findtext('.//StartInterval', '').strip()
        try:
            first_start = int(fs_str) if fs_str else None
        except ValueError:
            first_start = None
        try:
            start_interval = int(si_str) if si_str else None
        except ValueError:
            start_interval = None
        if cid:
            categories[cid] = Category(
                id=cid, name=name, course_id=course_id,
                first_start=first_start, start_interval=start_interval,
            )

    # ── Clubs ─────────────────────────────────────────────────────────────────
    clubs: dict[str, Club] = {}
    for el in root.findall('.//ClubList/Club'):
        cid  = el.findtext('Id', '').strip()
        name = el.findtext('Name', '').strip()
        if cid:
            clubs[cid] = Club(id=cid, name=name)

    # ── Coureurs ──────────────────────────────────────────────────────────────
    runners: list[Runner] = []
    for el in root.findall('.//RunnerList/Runner'):
        rid      = el.findtext('Id', '').strip()
        name     = el.findtext('Name', '').strip()
        start_s  = el.findtext('Start', '').strip()
        club_id  = el.findtext('Club', '').strip() or None
        class_id = el.findtext('Class', '').strip() or None
        card_no  = el.findtext('CardNo', '').strip() or None
        try:
            start = int(start_s) if start_s else None
        except ValueError:
            start = None
        runners.append(Runner(
            id=rid, name=name, start=start,
            club_id=club_id, class_id=class_id, card_no=card_no,
        ))

    return zero_time, comp_name, comp_date, controls, courses, categories, clubs, runners


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _runners_by_course(
    runners: list[Runner],
    categories: dict[str, Category],
) -> dict[str, list[Runner]]:
    by_course: dict[str, list[Runner]] = {}
    for r in runners:
        if r.start is None or r.class_id is None:
            continue
        cat = categories.get(r.class_id)
        if cat is None or not cat.course_id:
            continue
        by_course.setdefault(cat.course_id, []).append(r)
    for lst in by_course.values():
        lst.sort(key=lambda x: x.start)  # type: ignore[arg-type]
    return by_course


def _club_name(club_id: Optional[str], clubs: dict[str, Club]) -> str:
    if not club_id:
        return _('(sans club)')
    c = clubs.get(club_id)
    return c.name if c else _('Club #%(id)s') % {'id': club_id}


def _class_name(class_id: Optional[str], categories: dict[str, Category]) -> str:
    if not class_id:
        return '?'
    cat = categories.get(class_id)
    return cat.name if cat else _('Cat #%(id)s') % {'id': class_id}


# ─── Règle 1 ──────────────────────────────────────────────────────────────────

def check_club_consecutif(
    runners: list[Runner],
    categories: dict[str, Category],
    courses: dict[str, Course],
    clubs: dict[str, Club],
    zero_time: int,
    gap_max_seconds: int = 120,
) -> RuleResult:
    violations: list[Violation] = []
    by_course = _runners_by_course(runners, categories)

    for course_id, sorted_runners in by_course.items():
        course_name = courses[course_id].name if course_id in courses else course_id
        for i in range(len(sorted_runners) - 1):
            r1, r2 = sorted_runners[i], sorted_runners[i + 1]
            # Un Vacant sert uniquement de séparateur, on ne le signale pas
            if r1.name.strip().lower() == 'vacant' or r2.name.strip().lower() == 'vacant':
                continue
            if r1.club_id and r1.club_id == r2.club_id:
                # Deux coureurs du même club séparés de plus de 2 min
                # ne sont pas considérés consécutifs
                if r1.start is not None and r2.start is not None:
                    if abs(r2.start - r1.start) > gap_max_seconds:
                        continue
                club = _club_name(r1.club_id, clubs)
                t1   = _fmt_time(r1.start, zero_time)   # type: ignore[arg-type]
                t2   = _fmt_time(r2.start, zero_time)   # type: ignore[arg-type]
                c1   = _class_name(r1.class_id, categories)
                c2   = _class_name(r2.class_id, categories)
                violations.append(Violation(
                    description=_(
                        "Club %(club)s — Circuit %(course)s : "
                        "%(n1)s (%(c1)s) à %(t1)s, "
                        "%(n2)s (%(c2)s) à %(t2)s"
                    ) % {
                        'club': club, 'course': course_name,
                        'n1': r1.name or '?', 'c1': c1, 't1': t1,
                        'n2': r2.name or '?', 'c2': c2, 't2': t2,
                    },
                ))

    status  = 'ok' if not violations else 'error'
    n = len(violations)
    summary = (_("Aucun club n'a deux coureurs consécutifs sur le même circuit.")
               if not violations
               else ngettext("%(n)s paire de coureurs du même club consécutifs.",
                             "%(n)s paires de coureurs du même club consécutifs.",
                             n) % {'n': n})
    return RuleResult(
        rule_id='club_consecutif',
        title=_('Pas de club consécutif sur le même circuit'),
        status=status, summary=summary, violations=violations,
    )


# ─── Règle 2 ──────────────────────────────────────────────────────────────────

def check_entrelacement(
    runners: list[Runner],
    categories: dict[str, Category],
    courses: dict[str, Course],
    zero_time: int,
) -> RuleResult:
    violations: list[Violation] = []
    by_course = _runners_by_course(runners, categories)

    for course_id, sorted_runners in by_course.items():
        course_name = courses[course_id].name if course_id in courses else course_id

        # Group runners by class once
        by_class: dict[str, list[Runner]] = {}
        for r in sorted_runners:
            if r.class_id:
                by_class.setdefault(r.class_id, []).append(r)

        # Detect interleaving
        seen_classes: set[str] = set()
        last_class: Optional[str] = None
        interleaved: set[str] = set()

        for r in sorted_runners:
            cid = r.class_id
            if cid in seen_classes and cid != last_class:
                interleaved.add(cid)
            seen_classes.add(cid)
            last_class = cid

        if interleaved:
            cat_names = ', '.join(
                _class_name(cid, categories) for cid in sorted(interleaved)
            )
            border_lines = []
            for cid in sorted(interleaved):
                cat_runners = by_class.get(cid, [])
                if cat_runners:
                    cat_runners.sort(key=lambda r: r.start or 0)
                    cname = _class_name(cid, categories)
                    first_r = cat_runners[0]
                    last_r  = cat_runners[-1]
                    border_lines.append(
                        _(">>> 1er %(cat)s : %(name)s à %(time)s") % {
                            'cat': cname, 'name': first_r.name,
                            'time': _fmt_time(first_r.start, zero_time),
                        }
                    )
                    border_lines.append(
                        _(">>> Der %(cat)s : %(name)s à %(time)s") % {
                            'cat': cname, 'name': last_r.name,
                            'time': _fmt_time(last_r.start, zero_time),
                        }
                    )
            # Séquence des 12 premiers départs pour visualiser l'entrelacement
            seq = [
                f"{_fmt_time(r.start, zero_time)}  {_class_name(r.class_id, categories)}  {r.name}"
                for r in sorted_runners[:12]
            ]
            violations.append(Violation(
                description=ngettext(
                    "Circuit %(course)s — "
                    "%(n)s catégorie entrelacée : %(cats)s "
                    "(séquence des %(k)s 1ers départs ci-dessous)",
                    "Circuit %(course)s — "
                    "%(n)s catégories entrelacées : %(cats)s "
                    "(séquence des %(k)s 1ers départs ci-dessous)",
                    len(interleaved),
                ) % {
                    'course': course_name,
                    'n': len(interleaved),
                    'cats': cat_names,
                    'k': min(12, len(sorted_runners)),
                },
                runners=border_lines + seq,
            ))

    status  = 'ok' if not violations else 'error'
    n = len(violations)
    summary = (_("Chaque catégorie forme un bloc continu sur son circuit.")
               if not violations
               else ngettext("%(n)s circuit avec des catégories entrelacées.",
                             "%(n)s circuits avec des catégories entrelacées.",
                             n) % {'n': n})
    return RuleResult(
        rule_id='entrelacement',
        title=_("Pas d'entrelacement de catégories sur un même circuit"),
        status=status, summary=summary, violations=violations,
    )


# ─── Règle 3 ──────────────────────────────────────────────────────────────────

def check_premiers_postes(courses: dict[str, Course]) -> RuleResult:
    violations: list[Violation] = []
    by_first: dict[int, list[Course]] = {}

    for course in courses.values():
        if not course.controls:
            continue
        by_first.setdefault(course.controls[0], []).append(course)

    for ctrl_id, course_list in by_first.items():
        if len(course_list) >= 2:
            circuit_names = ', '.join(c.name for c in course_list)
            violations.append(Violation(
                description=_(
                    "Poste n°%(ctrl)s partagé comme 1er poste "
                    "par %(n)s circuits : %(courses)s"
                ) % {
                    'ctrl': ctrl_id, 'n': len(course_list), 'courses': circuit_names,
                },
            ))

    status  = 'ok' if not violations else 'error'
    summary = (_("Chaque circuit commence par un premier poste unique.")
               if not violations
               else ngettext("%(n)s conflit de premier poste détecté.",
                             "%(n)s conflits de premier poste détectés.",
                             len(violations)) % {'n': len(violations)})
    return RuleResult(
        rule_id='premiers_postes',
        title=_('Pas de premier poste commun entre circuits'),
        status=status, summary=summary, violations=violations,
    )


# ─── Règle 4 ──────────────────────────────────────────────────────────────────

def check_plages_continues(
    runners: list[Runner],
    categories: dict[str, Category],
    courses: dict[str, Course],
    zero_time: int,
) -> RuleResult:
    violations: list[Violation] = []
    by_course = _runners_by_course(runners, categories)

    for course_id, sorted_runners in by_course.items():
        by_class: dict[str, list[Runner]] = {}
        for r in sorted_runners:
            if r.class_id:
                by_class.setdefault(r.class_id, []).append(r)

        if len(by_class) <= 1:
            continue

        course_name = courses[course_id].name if course_id in courses else course_id

        class_ranges: dict[str, tuple[int, int]] = {}
        for cid, crlist in by_class.items():
            starts = [r.start for r in crlist if r.start is not None]
            if starts:
                class_ranges[cid] = (min(starts), max(starts))

        for cid_a, (a_min, a_max) in class_ranges.items():
            cat_name = _class_name(cid_a, categories)
            intruders: list[tuple[str, str]] = []
            for cid_b, blist in by_class.items():
                if cid_b == cid_a:
                    continue
                for r in blist:
                    if r.start is not None and a_min < r.start < a_max:
                        intruders.append((
                            _("%(name)s (%(cls)s) à %(time)s") % {
                                'name': r.name,
                                'cls': _class_name(r.class_id, categories),
                                'time': _fmt_time(r.start, zero_time),
                            },
                            _class_name(r.class_id, categories),
                        ))
            if intruders:
                intrusions = [line for line, _ in intruders]
                intruding_cats = ', '.join(sorted({cat for _, cat in intruders}))
                # Premier et dernier coureur de la categorie cid_a
                cat_runners_sorted = sorted(by_class[cid_a], key=lambda r: r.start or 0)
                first_r = cat_runners_sorted[0]
                last_r  = cat_runners_sorted[-1]
                border_lines = [
                    _(">>> 1er %(cat)s : %(name)s à %(time)s") % {
                        'cat': cat_name, 'name': first_r.name,
                        'time': _fmt_time(first_r.start, zero_time),
                    },
                    _(">>> Der %(cat)s : %(name)s à %(time)s") % {
                        'cat': cat_name, 'name': last_r.name,
                        'time': _fmt_time(last_r.start, zero_time),
                    },
                ]
                violations.append(Violation(
                    description=ngettext(
                        "Circuit %(course)s — %(cat)s "
                        "(%(tmin)s–%(tmax)s) : "
                        "%(n)s départ de %(cats)s intercalé",
                        "Circuit %(course)s — %(cat)s "
                        "(%(tmin)s–%(tmax)s) : "
                        "%(n)s départs de %(cats)s intercalés",
                        len(intrusions),
                    ) % {
                        'course': course_name, 'cat': cat_name,
                        'tmin': _fmt_time(a_min, zero_time),
                        'tmax': _fmt_time(a_max, zero_time),
                        'n': len(intrusions), 'cats': intruding_cats,
                    },
                    runners=(
                        border_lines
                        + intrusions[:10]
                        + ([intrusions[-1]] if len(intrusions) > 10 else [])
                    ),
                ))

    status  = 'ok' if not violations else 'error'
    summary = (_("Toutes les catégories sont regroupées sur des plages de départ continues.")
               if not violations
               else ngettext("%(n)s plage de catégorie non continue.",
                             "%(n)s plages de catégorie non continues.",
                             len(violations)) % {'n': len(violations)})
    return RuleResult(
        rule_id='plages_continues',
        title=_('Regroupement des catégories sur des plages continues'),
        status=status, summary=summary, violations=violations,
    )


# ─── Règle 5 ──────────────────────────────────────────────────────────────────

def check_coordonnees_postes(controls: dict[str, Control]) -> RuleResult:
    """Chaque poste doit avoir des coordonnées <xpos> et <ypos>."""
    violations: list[Violation] = []

    for ctrl in controls.values():
        missing = []
        if not ctrl.has_xpos:
            missing.append('xpos')
        if not ctrl.has_ypos:
            missing.append('ypos')
        if missing:
            violations.append(Violation(
                description=ngettext(
                    "Poste n°%(num)s : %(missing)s manquant",
                    "Poste n°%(num)s : %(missing)s manquants",
                    len(missing),
                ) % {'num': ctrl.number, 'missing': ', '.join(missing)},
            ))

    status  = 'ok' if not violations else 'error'
    summary = (_("Tous les postes ont des coordonnées xpos et ypos.")
               if not violations
               else ngettext("%(n)s poste sans coordonnées complètes.",
                             "%(n)s postes sans coordonnées complètes.",
                             len(violations)) % {'n': len(violations)})
    return RuleResult(
        rule_id='coordonnees_postes',
        title=_('Coordonnées des postes (xpos / ypos)'),
        status=status, summary=summary, violations=violations,
    )


# ─── Règle 6 ──────────────────────────────────────────────────────────────────

def check_circuits_vides(courses: dict[str, Course]) -> RuleResult:
    """Chaque circuit doit comporter au moins un poste."""
    violations = [
        Violation(description=_("Circuit « %(name)s » : aucun poste défini.") % {'name': c.name})
        for c in courses.values()
        if not c.controls
    ]

    status  = 'ok' if not violations else 'error'
    summary = (_("Aucun circuit vide.")
               if not violations
               else ngettext("%(n)s circuit vide sans postes.",
                             "%(n)s circuits vides sans postes.",
                             len(violations)) % {'n': len(violations)})
    return RuleResult(
        rule_id='circuits_vides',
        title=_('Pas de circuits vides'),
        status=status, summary=summary, violations=violations,
    )


# ─── Règle 7 ──────────────────────────────────────────────────────────────────

def check_categories_vides(
    runners: list[Runner],
    categories: dict[str, Category],
) -> RuleResult:
    """Chaque catégorie doit avoir au moins un coureur inscrit."""
    class_ids_with_runners = {r.class_id for r in runners if r.class_id}

    violations = [
        Violation(description=_("Catégorie « %(name)s » : aucun coureur inscrit.") % {'name': cat.name})
        for cat in categories.values()
        if cat.id not in class_ids_with_runners
    ]

    status  = 'ok' if not violations else 'warning'
    summary = (_("Toutes les catégories ont au moins un coureur.")
               if not violations
               else ngettext("%(n)s catégorie sans coureur.",
                             "%(n)s catégories sans coureur.",
                             len(violations)) % {'n': len(violations)})
    return RuleResult(
        rule_id='categories_vides',
        title=_('Pas de catégories vides'),
        status=status, summary=summary, violations=violations,
    )


# ─── Règle 8 ──────────────────────────────────────────────────────────────────

def check_completude_coureurs(
    runners: list[Runner],
    categories: dict[str, Category],
    courses: dict[str, Course],
) -> RuleResult:
    """Chaque coureur doit avoir : circuit, catégorie, CardNo, heure de départ, ID unique."""
    violations: list[Violation] = []

    # ── Doublons d'ID ─────────────────────────────────────────────────────────
    seen_ids: dict[str, str] = {}
    n_dup = 0
    for r in runners:
        if r.id in seen_ids:
            n_dup += 1
            violations.append(Violation(
                description=_(
                    "ID dupliqué (id=%(id)s) : "
                    "« %(old)s » et « %(new)s »"
                ) % {'id': r.id, 'old': seen_ids[r.id], 'new': r.name},
            ))
        else:
            seen_ids[r.id] = r.name

    # ── Champs obligatoires ────────────────────────────────────────────────────
    for r in runners:
        missing: list[str] = []

        # Catégorie
        if not r.class_id or r.class_id not in categories:
            missing.append(_('catégorie'))

        # Circuit (via la catégorie)
        if r.class_id and r.class_id in categories:
            cat = categories[r.class_id]
            if not cat.course_id or cat.course_id not in courses:
                missing.append(_('circuit'))

        # Numéro de puce
        if not r.card_no:
            missing.append(_('numéro de puce (CardNo)'))

        # Heure de départ
        if r.start is None:
            missing.append(_('heure de départ'))

        if missing:
            violations.append(Violation(
                description=_("%(name)s (id=%(id)s) : %(missing)s") % {
                    'name': r.name, 'id': r.id, 'missing': ', '.join(missing),
                },
            ))

    if not violations:
        status  = 'ok'
        summary = _("Tous les coureurs ont leurs données obligatoires et des identifiants uniques.")
    else:
        n_missing = len(violations) - n_dup
        parts = []
        if n_dup:
            parts.append(ngettext("%(n)s doublon d'ID", "%(n)s doublons d'ID", n_dup) % {'n': n_dup})
        if n_missing:
            parts.append(ngettext("%(n)s coureur avec données manquantes",
                                  "%(n)s coureurs avec données manquantes",
                                  n_missing) % {'n': n_missing})
        status  = 'error'
        summary = ' | '.join(parts) + '.'

    return RuleResult(
        rule_id='completude_coureurs',
        title=_('Complétude des données coureurs (circuit, catégorie, puce, départ, ID unique)'),
        status=status, summary=summary, violations=violations,
    )


# ─── Point d'entrée ────────────────────────────────────────────────────────────

def check_meos_file(
    xml_bytes: bytes,
    gap_max_seconds: int = 120,
    enabled_rules: Optional[set[str]] = None,
) -> CheckReport:
    """Analyse un fichier .meosxml et retourne un rapport complet (8 règles).

    Args:
        xml_bytes: Contenu du fichier .meosxml.
        gap_max_seconds: Écart max en secondes entre 2 coureurs du même club
                         pour être considérés consécutifs (défaut: 120 = 2 min).
        enabled_rules: Ensemble des identifiants de règles à exécuter.
                       None (défaut) = toutes les règles.

    Raises:
        ValueError si le fichier ne peut pas être parsé.
    """
    zero_time, comp_name, comp_date, controls, courses, categories, clubs, runners = (
        parse_meosxml(xml_bytes)
    )

    # R1 utilise la liste complète (Vacants inclus) comme séparateurs naturels
    # Toutes les autres règles ignorent les Vacants
    real_runners = [r for r in runners if r.name.strip().lower() != 'vacant']
    vacants      = [r for r in runners if r.name.strip().lower() == 'vacant']
    started   = [r for r in real_runners if r.start is not None]
    no_start  = [r for r in real_runners if r.start is None]

    report = CheckReport(
        competition_name=comp_name,
        competition_date=comp_date,
        zero_time=zero_time,
        n_runners=len(started),
        n_vacants=len(vacants),
        n_no_start=len(no_start),
        n_classes=len(categories),
        n_courses=len(courses),
    )

    _RULES: list[tuple[str, int, ...]] = [
        ('club_consecutif',   1, check_club_consecutif, (runners, categories, courses, clubs, zero_time, gap_max_seconds)),
        ('entrelacement',     2, check_entrelacement, (real_runners, categories, courses, zero_time)),
        ('premiers_postes',   3, check_premiers_postes, (courses,)),
        ('plages_continues',  4, check_plages_continues, (real_runners, categories, courses, zero_time)),
        ('coordonnees_postes',5, check_coordonnees_postes, (controls,)),
        ('circuits_vides',    6, check_circuits_vides, (courses,)),
        ('categories_vides',  7, check_categories_vides, (real_runners, categories)),
        ('completude_coureurs',8, check_completude_coureurs, (real_runners, categories, courses)),
    ]
    enabled = enabled_rules if enabled_rules is not None else {r[0] for r in _RULES}
    results = []
    for rid, num, fn, args in _RULES:
        if rid in enabled:
            result = fn(*args)
            result.num = num
            results.append(result)
    report.results = results

    return report
