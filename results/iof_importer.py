"""
iof_importer.py — Import des résultats IOF Data Standard v3 (ResultList).

Le fichier IOF est converti en un document MOP ``MOPComplete`` en mémoire,
puis confié à :func:`results.mop_receiver.process_mop_xml`. L'import bénéficie
donc exactement des mêmes règles d'écriture que MeOS : transaction unique,
vérification du gel, effacement complet de la course, préservation de
``livelox``/``logo`` et validation des données MOP.

Format d'entrée :
  https://github.com/international-orienteering-federation/datastandard-v3

Limites connues (documentées dans le rapport d'import) :
  - les circuits avec fourches sont fusionnés en une séquence unique ;
  - les postes répétés ne sont fidèlement conservés que si tous les
    concurrents d'une classe ont la même séquence ;
  - un seul numéro de course est importé pour les fichiers multi-course ;
  - les résultats globaux (OverallResult), les routes GPS et le Trail-O
    ne sont pas importés ;
  - le statut ``Delta`` n'est pas pris en charge.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from xml.etree import ElementTree as ET

from django.core.cache import cache
from django.utils.translation import gettext

from .mop_receiver import MOP_NS, process_mop_xml
from .models import (
    Mopcompetition,
    STAT_OK, STAT_MP, STAT_DNF, STAT_DQ, STAT_OT, STAT_OCC,
    STAT_DNS, STAT_CANCEL, STAT_NP, STAT_UNKNOWN,
)

logger = logging.getLogger(__name__)

IOF_NS = 'http://www.orienteering.org/datastandard/3.0'
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
SYNTHETIC_ID_START = 1_000_000_000
MAX_MOP_ID = 2_147_483_647
MAX_TINYINT = 127


# ─── Erreurs ──────────────────────────────────────────────────────────────────

class IofImportError(Exception):
    """Erreur d'import destinée à l'utilisateur (message traduit)."""


# ─── Modèle IOF intermédiaire ─────────────────────────────────────────────────

@dataclass
class IofSplit:
    code: str
    time_tenths: int | None
    status: str  # OK, Missing, Additional


@dataclass
class IofOrganisation:
    iof_id: str | None
    name: str
    country_code: str = ''


@dataclass
class IofPerson:
    iof_id: str | None
    family: str
    given: str
    nationality: str
    organisation: IofOrganisation | None
    results: list['IofResult'] = field(default_factory=list)


@dataclass
class IofResult:
    race_number: int | None
    bib: str
    start: datetime | None
    finish: datetime | None
    time_tenths: int | None
    status: str
    splits: list[IofSplit]
    card: str
    leg: int | None
    leg_order: int | None
    stat: int
    prel: int
    tstat: int


@dataclass
class IofTeamMember:
    person: IofPerson | None
    organisation: IofOrganisation | None
    results: list[IofResult] = field(default_factory=list)


@dataclass
class IofTeam:
    entry_id: str | None
    name: str
    organisations: list[IofOrganisation]
    bib: str
    members: list[IofTeamMember] = field(default_factory=list)


@dataclass
class IofClassResult:
    iof_id: str | None
    name: str
    persons: list[IofPerson] = field(default_factory=list)
    teams: list[IofTeam] = field(default_factory=list)


@dataclass
class IofRace:
    number: int
    name: str
    date: date | None


@dataclass
class IofEvent:
    name: str
    date: date | None
    organiser: str
    homepage: str
    races: list[IofRace] = field(default_factory=list)


@dataclass
class IofResultList:
    event: IofEvent
    classes: list[IofClassResult]
    status: str
    race_number: int | None
    warnings: list[str] = field(default_factory=list)


# ─── Modèle MOP intermédiaire ─────────────────────────────────────────────────

@dataclass
class _MopControl:
    id: int
    name: str


@dataclass
class _MopClass:
    id: int
    name: str
    ord: int
    controls_by_leg: dict[int, list[int]] = field(default_factory=dict)


@dataclass
class _MopOrg:
    id: int
    name: str
    nat: str


@dataclass
class _MopCompetitor:
    id: int
    name: str
    org: int
    cls: int
    stat: int
    st: int
    rt: int
    it: int
    tstat: int
    prel: int
    bib: str
    card: str
    nat: str
    radio: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class _MopTeam:
    id: int
    name: str
    org: int
    cls: int
    stat: int
    st: int
    rt: int
    prel: int
    members: list[tuple[int, int, int]] = field(default_factory=list)


@dataclass
class _MopModel:
    competition: dict
    controls: dict[int, _MopControl]
    classes: dict[int, _MopClass]
    orgs: dict[int, _MopOrg]
    competitors: dict[int, _MopCompetitor]
    teams: dict[int, _MopTeam]


@dataclass
class IofImportReport:
    status: str
    race_number: int | None
    competition_name: str
    classes: int
    competitors: int
    teams: int
    controls: int
    splits: int
    warnings: list[str] = field(default_factory=list)
    class_ids: list[int] = field(default_factory=list)
    course_hashes: list[str] = field(default_factory=list)


# ─── Correspondance des statuts IOF → MOP ────────────────────────────────────

# (stat, prel, tstat)
_STATUS_MAP: dict[str, tuple[int, int, int]] = {
    'OK': (STAT_OK, 0, STAT_OK),
    'Finished': (STAT_OK, 1, 0),
    'MissingPunch': (STAT_MP, 0, STAT_MP),
    'Disqualified': (STAT_DQ, 0, STAT_DQ),
    'DidNotFinish': (STAT_DNF, 0, STAT_DNF),
    'SportingWithdrawal': (STAT_DNF, 0, STAT_DNF),
    'OverTime': (STAT_OT, 0, STAT_OT),
    'NotCompeting': (STAT_OCC, 0, STAT_OCC),
    'DidNotStart': (STAT_DNS, 0, STAT_DNS),
    'Inactive': (STAT_DNS, 0, STAT_DNS),
    'Cancelled': (STAT_CANCEL, 0, STAT_CANCEL),
    'Moved': (STAT_NP, 0, STAT_NP),
    'MovedUp': (STAT_NP, 0, STAT_NP),
    'DidNotEnter': (STAT_NP, 0, STAT_NP),
    'Active': (STAT_UNKNOWN, 0, 0),
}


def _status_tuple(status: str, warnings: list[str]) -> tuple[int, int, int]:
    key = (status or '').strip()
    if key in _STATUS_MAP:
        return _STATUS_MAP[key]
    if key:
        warnings.append(
            gettext(
                "Statut IOF « %(status)s » inconnu : résultat importé avec le "
                "statut MOP inconnu."
            ) % {'status': key}
        )
    else:
        warnings.append(
            gettext("Statut IOF absent : résultat importé avec le statut MOP inconnu.")
        )
    return (STAT_UNKNOWN, 0, 0)


# ─── Helpers XML ──────────────────────────────────────────────────────────────

def _local(tag: str) -> str:
    return tag.rsplit('}', 1)[-1] if '}' in tag else tag


def _namespace(tag: str) -> str:
    if tag.startswith('{'):
        return tag[1:].split('}', 1)[0]
    return ''


def _children(elem: ET.Element | None, name: str) -> list[ET.Element]:
    if elem is None:
        return []
    return [child for child in elem if _local(child.tag) == name]


def _child(elem: ET.Element | None, name: str) -> ET.Element | None:
    if elem is None:
        return None
    for child in elem:
        if _local(child.tag) == name:
            return child
    return None


def _text(elem: ET.Element | None, name: str, default: str = '') -> str:
    child = _child(elem, name)
    if child is None:
        return default
    return (child.text or '').strip()


# ─── Helpers de conversion ───────────────────────────────────────────────────

def _parse_int(value: str | None) -> int | None:
    value = (value or '').strip()
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _numeric_id(value: str | None) -> int | None:
    value = (value or '').strip()
    if not re.fullmatch(r'\d+', value):
        return None
    number = int(value)
    if 0 < number <= MAX_MOP_ID:
        return number
    return None


def _parse_decimal(value: str | None) -> Decimal | None:
    value = (value or '').strip()
    if not value:
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    return number


def _to_tenths(value: Decimal | None) -> int | None:
    if value is None or value < 0:
        return None
    return int((value * 10).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _clock_tenths(value: datetime | None) -> int:
    if value is None:
        return 0
    seconds = value.hour * 3600 + value.minute * 60 + value.second
    return seconds * 10 + (value.microsecond + 50_000) // 100_000


def _parse_date(value: str | None) -> date | None:
    value = (value or '').strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _parse_datetime(value: str | None) -> datetime | None:
    value = (value or '').strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None


def _clean_text(value: str | None, max_length: int, label: str,
                warnings: list[str]) -> str:
    text = ' '.join((value or '').split())
    if len(text) > max_length:
        warnings.append(
            gettext("« %(label)s » tronqué à %(max)d caractères.") % {
                'label': label, 'max': max_length,
            }
        )
        text = text[:max_length]
    return text


class _Truncator:
    """Tronque les valeurs aux tailles des colonnes MOP, en agrégeant l'alerte."""

    def __init__(self, warnings: list[str]):
        self.warnings = warnings
        self.labels: set[str] = set()

    def __call__(self, value: str | None, max_length: int, label: str) -> str:
        text = ' '.join((value or '').split())
        if len(text) > max_length:
            self.labels.add(label)
            text = text[:max_length]
        return text

    def add_warning(self):
        if self.labels:
            self.warnings.append(
                gettext("Certaines valeurs ont été tronquées : %(fields)s.") % {
                    'fields': ', '.join(sorted(self.labels)),
                }
            )


# ─── Parseur IOF ──────────────────────────────────────────────────────────────

def _parse_organisation(elem: ET.Element | None) -> IofOrganisation | None:
    if elem is None:
        return None
    iof_id = _text(elem, 'Id') or None
    name = _text(elem, 'Name')
    country = _child(elem, 'Country')
    nat = ''
    if country is not None:
        nat = (country.get('code') or '').strip().upper()
        if not nat:
            nat = (country.text or '').strip().upper()[:8]
    if not name and not iof_id:
        return None
    return IofOrganisation(iof_id=iof_id, name=name, country_code=nat)


def _parse_person(elem: ET.Element) -> IofPerson:
    ids = [(child.text or '').strip() for child in _children(elem, 'Id')]
    iof_id = next((value for value in ids if value), None)
    name_elem = _child(elem, 'Name')
    family = _text(name_elem, 'Family')
    given = _text(name_elem, 'Given')
    nat = ''
    nat_elem = _child(elem, 'Nationality')
    if nat_elem is not None:
        nat = (nat_elem.get('code') or '').strip().upper()
        if not nat:
            nat = (nat_elem.text or '').strip().upper()[:8]
    return IofPerson(
        iof_id=iof_id,
        family=family,
        given=given,
        nationality=nat,
        organisation=None,
    )


def _parse_split(elem: ET.Element, warnings: list[str]) -> IofSplit | None:
    code = _text(elem, 'ControlCode')
    if not code:
        warnings.append(gettext("SplitTime sans ControlCode : ignoré."))
        return None
    status = (elem.get('status') or 'OK').strip()
    if status not in ('OK', 'Missing', 'Additional'):
        warnings.append(
            gettext("Statut de split « %(status)s » inconnu : traité comme OK.") % {
                'status': status,
            }
        )
        status = 'OK'
    time_tenths = None
    if status == 'OK':
        value = _parse_decimal(_text(elem, 'Time'))
        if value is not None and value < 0:
            warnings.append(
                gettext("Temps négatif ignoré pour le poste « %(code)s ».") % {
                    'code': code,
                }
            )
        else:
            time_tenths = _to_tenths(value)
    return IofSplit(code=code, time_tenths=time_tenths, status=status)


def _parse_result(elem: ET.Element, warnings: list[str]) -> IofResult:
    race_number = _parse_int(elem.get('raceNumber'))
    start = _parse_datetime(_text(elem, 'StartTime'))
    finish = _parse_datetime(_text(elem, 'FinishTime'))

    time_value = _parse_decimal(_text(elem, 'Time'))
    time_tenths = _to_tenths(time_value)
    if time_value is not None and time_value < 0:
        warnings.append(gettext("Temps de course négatif ignoré."))
        time_tenths = None
    if time_tenths is None and start is not None and finish is not None:
        try:
            delta = finish - start
        except TypeError:
            delta = None
        if delta is not None:
            if delta.total_seconds() < 0:
                warnings.append(
                    gettext("Heure d'arrivée antérieure au départ : temps ignoré.")
                )
            else:
                time_tenths = _to_tenths(Decimal(str(delta.total_seconds())))

    status = _text(elem, 'Status')
    stat, prel, tstat = _status_tuple(status, warnings)

    splits = []
    for split_elem in _children(elem, 'SplitTime'):
        split = _parse_split(split_elem, warnings)
        if split is not None:
            splits.append(split)

    card = ''
    for card_elem in _children(elem, 'ControlCard'):
        card = (card_elem.text or '').strip()
        if card:
            break

    return IofResult(
        race_number=race_number,
        bib=_text(elem, 'BibNumber'),
        start=start,
        finish=finish,
        time_tenths=time_tenths,
        status=status,
        splits=splits,
        card=card,
        leg=_parse_int(_text(elem, 'Leg')),
        leg_order=_parse_int(_text(elem, 'LegOrder')),
        stat=stat,
        prel=prel,
        tstat=tstat,
    )


def _matches_race(elem: ET.Element, selected: int | None,
                  race_count: int) -> bool:
    raw = elem.get('raceNumber')
    if raw is None:
        return selected is None or race_count <= 1
    number = _parse_int(raw)
    if number is None:
        return False
    if selected is None:
        return number == 1
    return number == selected


def _parse_results(container: ET.Element, selected: int | None,
                   race_count: int, warnings: list[str]) -> list[IofResult]:
    matches = []
    for result_elem in _children(container, 'Result'):
        if not _matches_race(result_elem, selected, race_count):
            continue
        matches.append(_parse_result(result_elem, warnings))
    if len(matches) > 1:
        warnings.append(
            gettext("Plusieurs résultats pour la même course : le premier est conservé.")
        )
    return matches[:1]


def _parse_team(team_elem: ET.Element, selected: int | None,
                race_count: int, warnings: list[str]) -> IofTeam:
    organisations = [
        org for org in (
            _parse_organisation(org_elem)
            for org_elem in _children(team_elem, 'Organisation')
        ) if org is not None
    ]
    members = []
    for member_elem in _children(team_elem, 'TeamMemberResult'):
        person_elem = _child(member_elem, 'Person')
        person = _parse_person(person_elem) if person_elem is not None else None
        organisation = _parse_organisation(_child(member_elem, 'Organisation'))
        results = _parse_results(member_elem, selected, race_count, warnings)
        members.append(
            IofTeamMember(
                person=person,
                organisation=organisation,
                results=results,
            )
        )
    return IofTeam(
        entry_id=_text(team_elem, 'EntryId') or None,
        name=_text(team_elem, 'Name'),
        organisations=organisations,
        bib=_text(team_elem, 'BibNumber'),
        members=members,
    )


def _parse_event(event_elem: ET.Element | None,
                 warnings: list[str]) -> IofEvent:
    if event_elem is None:
        warnings.append(gettext("Élément <Event> absent : informations minimales utilisées."))
        return IofEvent(name='', date=None, organiser='', homepage='')

    name = _text(event_elem, 'Name')
    start_elem = _child(event_elem, 'StartTime')
    event_date = _parse_date(_text(start_elem, 'Date')) if start_elem is not None else None

    organiser = ''
    organiser_elem = _child(event_elem, 'Organiser')
    if organiser_elem is not None:
        organiser = _text(organiser_elem, 'Name')

    homepage = ''
    urls = _children(event_elem, 'URL')
    for url_elem in urls:
        if (url_elem.get('type') or '') == 'Website':
            homepage = (url_elem.text or '').strip()
            break
    if not homepage and urls:
        homepage = (urls[0].text or '').strip()

    races = []
    seen_numbers: set[int] = set()
    for index, race_elem in enumerate(_children(event_elem, 'Race'), start=1):
        number = _parse_int(_text(race_elem, 'RaceNumber'))
        if number is None or number <= 0:
            number = index
            warnings.append(
                gettext("RaceNumber absent ou invalide : numéro %(number)s utilisé.") % {
                    'number': number,
                }
            )
        if number in seen_numbers:
            warnings.append(
                gettext("Numéro de course %(number)s dupliqué : occurrence ignorée.") % {
                    'number': number,
                }
            )
            continue
        seen_numbers.add(number)
        race_start = _child(race_elem, 'StartTime')
        races.append(
            IofRace(
                number=number,
                name=_text(race_elem, 'Name'),
                date=_parse_date(_text(race_start, 'Date')) if race_start is not None else None,
            )
        )

    return IofEvent(
        name=name,
        date=event_date,
        organiser=organiser,
        homepage=homepage,
        races=races,
    )


def _merge_class_results(classes: list[IofClassResult],
                         warnings: list[str]) -> list[IofClassResult]:
    """Fusionne les blocs ``ClassResult`` qui désignent la même classe.

    Certains exportateurs découpent une classe en plusieurs blocs (par
    exemple un bloc par organisation). Sans fusion, le second passage
    écraserait les circuits du premier. La clé est l'identifiant IOF de la
    classe, ou à défaut son nom.
    """
    merged: list[IofClassResult] = []
    by_key: dict[tuple[str, str], IofClassResult] = {}

    for class_result in classes:
        class_id = (class_result.iof_id or '').strip()
        if class_id:
            key: tuple[str, str] | None = ('id', class_id)
        elif class_result.name:
            key = ('name', class_result.name)
        else:
            key = None

        existing = by_key.get(key) if key is not None else None
        if existing is None:
            if key is not None:
                by_key[key] = class_result
            merged.append(class_result)
            continue

        warnings.append(
            gettext(
                "Classe « %(name)s » présente plusieurs fois : résultats fusionnés."
            ) % {'name': existing.name or class_result.name or '?'}
        )
        if class_result.name and class_result.name != existing.name:
            warnings.append(
                gettext(
                    "Classe « %(name)s » : noms différents pour un même "
                    "identifiant — « %(kept)s » conservé."
                ) % {
                    'name': existing.name or class_result.name,
                    'kept': existing.name,
                }
            )
        existing.persons.extend(class_result.persons)
        existing.teams.extend(class_result.teams)

    for class_result in merged:
        if class_result.persons and class_result.teams:
            raise IofImportError(
                gettext(
                    "La classe « %(name)s » mélange des résultats individuels "
                    "et des équipes, ce qui n'est pas pris en charge."
                ) % {'name': class_result.name or '?'}
            )
    return merged


def parse_iof_result_list(xml_data: bytes | str, *,
                          race_number: int | None = None) -> IofResultList:
    """Parse un document IOF v3 ``ResultList``.

    Args:
        xml_data: contenu XML (bytes ou str).
        race_number: numéro de course à retenir pour un fichier multi-course.

    Raises:
        IofImportError: fichier invalide, format non pris en charge, course
            ambiguë ou aucun résultat exploitable.
    """
    if isinstance(xml_data, str):
        xml_data = xml_data.encode('utf-8')
    if not xml_data or not xml_data.strip():
        raise IofImportError(gettext("Le fichier est vide."))
    if len(xml_data) > MAX_UPLOAD_BYTES:
        raise IofImportError(
            gettext("Le fichier dépasse la taille maximale de %(max)d Mo.") % {
                'max': MAX_UPLOAD_BYTES // (1024 * 1024),
            }
        )
    upper = xml_data.upper()
    if b'<!DOCTYPE' in upper or b'<!ENTITY' in upper:
        raise IofImportError(
            gettext(
                "Le fichier contient une déclaration DOCTYPE ou ENTITY, "
                "refusée pour des raisons de sécurité."
            )
        )

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as exc:
        raise IofImportError(
            gettext("XML invalide : %(error)s") % {'error': str(exc)}
        ) from exc

    warnings: list[str] = []
    if _local(root.tag) != 'ResultList':
        raise IofImportError(
            gettext(
                "Le fichier n'est pas une liste de résultats IOF v3 "
                "(élément <ResultList> attendu)."
            )
        )

    namespace = _namespace(root.tag)
    if namespace and namespace.rstrip('/') != IOF_NS.rstrip('/'):
        raise IofImportError(
            gettext(
                "Namespace IOF v3 attendu (%(ns)s)."
            ) % {'ns': IOF_NS}
        )
    if not namespace:
        warnings.append(
            gettext("Namespace IOF v3 absent : le fichier est accepté, mais vérifiez son format.")
        )

    version = (root.get('iofVersion') or '').strip()
    if version and not version.startswith('3.'):
        raise IofImportError(
            gettext("Version IOF non prise en charge : %(version)s (IOF v3 attendu).") % {
                'version': version,
            }
        )
    if not version:
        warnings.append(
            gettext("Version IOF absente : le fichier est traité comme IOF v3.")
        )

    status = (root.get('status') or '').strip()
    if status.lower() == 'delta':
        raise IofImportError(
            gettext(
                "Le statut « Delta » n'est pas pris en charge : exportez une "
                "liste complète (Complete ou Snapshot)."
            )
        )
    if status and status.lower() not in ('complete', 'snapshot'):
        warnings.append(
            gettext("Statut de fichier IOF « %(status)s » inconnu : traité comme Complete.") % {
                'status': status,
            }
        )
    if not status:
        warnings.append(
            gettext("Statut de fichier IOF absent : traité comme Complete.")
        )

    event = _parse_event(_child(root, 'Event'), warnings)

    declared = {race.number for race in event.races}
    observed: set[int] = set()
    for elem in root.iter():
        if _local(elem.tag) not in ('Result', 'Course'):
            continue
        raw = elem.get('raceNumber')
        if raw is None:
            continue
        number = _parse_int(raw)
        if number is not None and number > 0:
            observed.add(number)
        else:
            warnings.append(
                gettext("raceNumber invalide « %(value)s » : ignoré.") % {
                    'value': raw,
                }
            )
    available = sorted(declared | observed)

    if race_number is None:
        if len(available) > 1:
            raise IofImportError(
                gettext(
                    "Ce fichier contient plusieurs courses (%(races)s) : "
                    "précisez le numéro de course à importer."
                ) % {'races': ', '.join(str(n) for n in available)}
            )
        selected = available[0] if available else None
    else:
        if available and race_number not in available:
            raise IofImportError(
                gettext(
                    "La course %(race)s n'existe pas dans ce fichier "
                    "(courses disponibles : %(races)s)."
                ) % {
                    'race': race_number,
                    'races': ', '.join(str(n) for n in available),
                }
            )
        selected = race_number

    race_count = len(available)
    if race_count > 1:
        ambiguous = any(
            _local(elem.tag) == 'Result' and elem.get('raceNumber') is None
            for elem in root.iter()
        )
        if ambiguous:
            warnings.append(
                gettext(
                    "Résultat sans numéro de course dans un fichier multi-course : ignoré."
                )
            )

    classes: list[IofClassResult] = []
    for class_elem in _children(root, 'ClassResult'):
        class_info = _child(class_elem, 'Class')
        if class_info is None:
            warnings.append(gettext("ClassResult sans <Class> : ignoré."))
            continue
        class_id = _text(class_info, 'Id') or None
        class_name = _text(class_info, 'Name') or class_id or ''
        if not class_name:
            warnings.append(gettext("Classe sans nom : nom vide conservé."))

        persons: list[IofPerson] = []
        for person_elem in _children(class_elem, 'PersonResult'):
            person_info = _child(person_elem, 'Person')
            if person_info is None:
                warnings.append(gettext("PersonResult sans <Person> : ignoré."))
                continue
            person = _parse_person(person_info)
            person.organisation = _parse_organisation(_child(person_elem, 'Organisation'))
            person.results = _parse_results(person_elem, selected, race_count, warnings)
            if person.results:
                persons.append(person)

        teams: list[IofTeam] = []
        for team_elem in _children(class_elem, 'TeamResult'):
            team = _parse_team(team_elem, selected, race_count, warnings)
            if team.members:
                teams.append(team)
            else:
                warnings.append(
                    gettext("Équipe « %(name)s » sans membre : ignorée.") % {
                        'name': team.name or '?',
                    }
                )

        classes.append(
            IofClassResult(
                iof_id=class_id,
                name=class_name,
                persons=persons,
                teams=teams,
            )
        )

    classes = _merge_class_results(classes, warnings)

    if not classes:
        raise IofImportError(gettext("Le fichier ne contient aucune classe de résultats."))

    total_results = sum(len(c.persons) + len(c.teams) for c in classes)
    if total_results == 0:
        raise IofImportError(
            gettext("Le fichier ne contient aucun résultat exploitable pour la course sélectionnée.")
        )

    return IofResultList(
        event=event,
        classes=classes,
        status=status or 'Complete',
        race_number=selected,
        warnings=warnings,
    )


# ─── Allocation des identifiants MOP ─────────────────────────────────────────

class _Allocator:
    """Alloue des identifiants entiers positifs, en réutilisant les IDs IOF."""

    def __init__(self, warnings: list[str] | None = None, label: str = ''):
        self.used: set[int] = set()
        self.next_synthetic = SYNTHETIC_ID_START
        self.warnings = warnings
        self.label = label

    def allocate(self) -> int:
        while self.next_synthetic in self.used:
            self.next_synthetic += 1
        value = self.next_synthetic
        self.used.add(value)
        self.next_synthetic += 1
        return value

    def allocate_preferred(self, raw: str | None) -> int:
        value = _numeric_id(raw)
        if value is not None and value not in self.used:
            self.used.add(value)
            return value
        if value is not None and value in self.used and self.warnings is not None:
            self.warnings.append(
                gettext(
                    "Identifiant %(id)s dupliqué (%(label)s) : un identifiant "
                    "synthétique est utilisé."
                ) % {'id': value, 'label': self.label or '?'}
            )
        return self.allocate()


class _ControlRegistry:
    def __init__(self, truncator: _Truncator):
        self.truncator = truncator
        self.controls: dict[int, _MopControl] = {}
        self.by_code: dict[str, int] = {}
        self.used: set[int] = set()
        self.next_synthetic = SYNTHETIC_ID_START

    def _allocate(self) -> int:
        while self.next_synthetic in self.used:
            self.next_synthetic += 1
        value = self.next_synthetic
        self.used.add(value)
        self.next_synthetic += 1
        return value

    def _register(self, code: str, control_id: int):
        self.used.add(control_id)
        self.controls[control_id] = _MopControl(
            id=control_id,
            name=self.truncator(code, 64, 'poste') or str(control_id),
        )

    def id_for_code(self, code: str) -> int:
        if code in self.by_code:
            return self.by_code[code]
        control_id = None
        numeric = _numeric_id(code)
        if numeric is not None and numeric not in self.used:
            control_id = numeric
        if control_id is None:
            control_id = self._allocate()
        self._register(code, control_id)
        self.by_code[code] = control_id
        return control_id

    def allocate_for_code(self, code: str) -> int:
        control_id = self._allocate()
        self._register(code, control_id)
        return control_id


class _ClassRegistry:
    def __init__(self, allocator: _Allocator, truncator: _Truncator,
                 warnings: list[str]):
        self.allocator = allocator
        self.truncator = truncator
        self.warnings = warnings
        self.classes: dict[int, _MopClass] = {}
        self.by_iof_id: dict[str, int] = {}
        self.by_name: dict[str, int] = {}

    def get(self, class_result: IofClassResult, ord_: int) -> _MopClass:
        key = (class_result.iof_id or '').strip()
        if key and key in self.by_iof_id:
            existing = self.classes[self.by_iof_id[key]]
            self.warnings.append(
                gettext(
                    "Classe « %(name)s » : identifiant dupliqué, les résultats "
                    "sont fusionnés."
                ) % {'name': existing.name or key}
            )
            return existing
        if not key and class_result.name and class_result.name in self.by_name:
            existing = self.classes[self.by_name[class_result.name]]
            self.warnings.append(
                gettext(
                    "Classe « %(name)s » sans identifiant : fusion par nom."
                ) % {'name': class_result.name}
            )
            return existing

        class_id = self.allocator.allocate_preferred(key or None)
        name = self.truncator(class_result.name, 64, 'classe') or f'Class {class_id}'
        obj = _MopClass(id=class_id, name=name, ord=ord_)
        self.classes[class_id] = obj
        if key:
            self.by_iof_id[key] = class_id
        if class_result.name:
            self.by_name.setdefault(class_result.name, class_id)
        return obj


class _OrgRegistry:
    def __init__(self, allocator: _Allocator, truncator: _Truncator,
                 warnings: list[str]):
        self.allocator = allocator
        self.truncator = truncator
        self.warnings = warnings
        self.orgs: dict[int, _MopOrg] = {}
        self.by_iof_id: dict[str, int] = {}
        self.by_name: dict[str, int] = {}

    def get(self, organisation: IofOrganisation | None) -> int:
        if organisation is None:
            return 0
        key = (organisation.iof_id or '').strip()
        if key and key in self.by_iof_id:
            return self.by_iof_id[key]
        if not key and organisation.name and organisation.name in self.by_name:
            return self.by_name[organisation.name]

        org_id = self.allocator.allocate_preferred(key or None)
        name = self.truncator(organisation.name, 64, 'organisation') or f'Org {org_id}'
        nat = self.truncator(organisation.country_code, 8, 'nationalité')
        self.orgs[org_id] = _MopOrg(id=org_id, name=name, nat=nat)
        if key:
            self.by_iof_id[key] = org_id
        if organisation.name:
            self.by_name.setdefault(organisation.name, org_id)
        return org_id


# ─── Construction du modèle MOP ───────────────────────────────────────────────

@dataclass
class _CanonicalCourse:
    codes: list[str]
    ids: list[int]
    uniform: bool
    occurrence_ids: dict[tuple[str, int], int] = field(default_factory=dict)
    code_ids: dict[str, int] = field(default_factory=dict)


def _sequence_from_splits(splits: list[IofSplit]) -> list[str]:
    return [
        split.code for split in splits
        if split.status != 'Additional' and split.code
    ]


def _dedupe_sequence(codes: list[str]) -> list[str]:
    seen = set()
    result = []
    for code in codes:
        if code in seen:
            continue
        seen.add(code)
        result.append(code)
    return result


def _canonical_sequence(sequences: list[list[str]], class_name: str,
                        registry: _ControlRegistry,
                        warnings: list[str]) -> _CanonicalCourse:
    non_empty = [seq for seq in sequences if seq]
    if not non_empty:
        return _CanonicalCourse(codes=[], ids=[], uniform=True)

    base = non_empty[0]
    uniform = all(seq == base for seq in non_empty[1:])

    if uniform:
        codes = list(base)
        ids: list[int] = []
        occurrence_ids: dict[tuple[str, int], int] = {}
        code_ids: dict[str, int] = {}
        occurrences: dict[str, int] = {}
        for code in codes:
            occurrence = occurrences.get(code, 0)
            occurrences[code] = occurrence + 1
            if occurrence == 0:
                control_id = registry.id_for_code(code)
                code_ids[code] = control_id
            else:
                control_id = registry.allocate_for_code(code)
            ids.append(control_id)
            occurrence_ids[(code, occurrence)] = control_id
        return _CanonicalCourse(
            codes=codes,
            ids=ids,
            uniform=True,
            occurrence_ids=occurrence_ids,
            code_ids=code_ids,
        )

    deduped = [_dedupe_sequence(seq) for seq in non_empty]
    counts = Counter(tuple(seq) for seq in deduped)
    best_tuple = max(
        counts,
        key=lambda item: (
            counts[item],
            len(item),
            -next(index for index, seq in enumerate(deduped) if tuple(seq) == item),
        ),
    )
    merged = list(best_tuple)
    for seq in deduped:
        previous = 0
        for code in seq:
            if code in merged:
                previous = merged.index(code) + 1
            else:
                merged.insert(previous, code)
                previous += 1

    ids = [registry.id_for_code(code) for code in merged]
    code_ids = {code: control_id for code, control_id in zip(merged, ids)}
    warnings.append(
        gettext(
            "Classe « %(name)s » : circuits différents (fourches) — séquence "
            "fusionnée, les temps des postes répétés ne sont pas conservés."
        ) % {'name': class_name}
    )
    return _CanonicalCourse(
        codes=merged,
        ids=ids,
        uniform=False,
        occurrence_ids={(code, 0): control_id for code, control_id in code_ids.items()},
        code_ids=code_ids,
    )


def _map_splits(splits: list[IofSplit], canonical: _CanonicalCourse,
                warnings: list[str], runner_name: str) -> list[tuple[int, int]]:
    radio: list[tuple[int, int]] = []
    seen: set[int] = set()
    occurrences: dict[str, int] = {}

    for split in splits:
        if split.status == 'Additional' or not split.code:
            continue
        if canonical.uniform:
            occurrence = occurrences.get(split.code, 0)
            occurrences[split.code] = occurrence + 1
            control_id = canonical.occurrence_ids.get((split.code, occurrence))
            if control_id is None:
                control_id = canonical.code_ids.get(split.code)
        else:
            control_id = canonical.code_ids.get(split.code)

        if control_id is None:
            continue
        if split.status != 'OK' or split.time_tenths is None:
            continue
        if control_id in seen:
            warnings.append(
                gettext(
                    "Poste « %(code)s » répété : temps supplémentaire ignoré "
                    "pour « %(name)s »."
                ) % {'code': split.code, 'name': runner_name or '?'}
            )
            continue
        seen.add(control_id)
        radio.append((control_id, split.time_tenths))
    return radio


def _person_name(person: IofPerson) -> str:
    family = ' '.join((person.family or '').split())
    given = ' '.join((person.given or '').split())
    return f'{family} {given}'.strip()


def _make_competitor(person: IofPerson, result: IofResult, class_id: int,
                     org_registry: _OrgRegistry, allocator: _Allocator,
                     radio: list[tuple[int, int]], truncator: _Truncator,
                     warnings: list[str], *,
                     member_org: IofOrganisation | None = None,
                     fallback_org: IofOrganisation | None = None) -> _MopCompetitor:
    comp_id = allocator.allocate_preferred(person.iof_id)
    raw_name = _person_name(person)
    if not raw_name:
        warnings.append(gettext("Personne sans nom : « Unknown » utilisé."))
    name = truncator(raw_name or f'Unknown {comp_id}', 64, 'nom de coureur')

    organisation = member_org or fallback_org
    org_id = org_registry.get(organisation)
    nat = person.nationality or (organisation.country_code if organisation else '')
    nat = truncator(nat, 8, 'nationalité')
    bib = truncator(result.bib, 32, 'dossard')
    card = truncator(result.card, 32, 'puce')

    st = _clock_tenths(result.start)
    rt = result.time_tenths or 0
    it = _clock_tenths(result.finish)
    if result.stat == STAT_OK and rt <= 0:
        warnings.append(
            gettext("Coureur « %(name)s » : statut OK sans temps de course.") % {
                'name': name,
            }
        )

    return _MopCompetitor(
        id=comp_id,
        name=name,
        org=org_id,
        cls=class_id,
        stat=result.stat,
        st=st,
        rt=rt,
        it=it,
        tstat=result.tstat,
        prel=result.prel,
        bib=bib,
        card=card,
        nat=nat,
        radio=radio,
    )


def _build_individual_class(class_obj: _MopClass,
                            class_result: IofClassResult,
                            org_registry: _OrgRegistry,
                            control_registry: _ControlRegistry,
                            competitor_allocator: _Allocator,
                            competitors: dict[int, _MopCompetitor],
                            truncator: _Truncator,
                            warnings: list[str]):
    entries = [
        (person, person.results[0])
        for person in class_result.persons
        if person.results
    ]
    sequences = [_sequence_from_splits(result.splits) for _, result in entries]
    canonical = _canonical_sequence(
        sequences, class_obj.name, control_registry, warnings,
    )
    if canonical.ids:
        class_obj.controls_by_leg[1] = canonical.ids

    for person, result in entries:
        runner_name = _person_name(person)
        radio = _map_splits(result.splits, canonical, warnings, runner_name)
        competitor = _make_competitor(
            person, result, class_obj.id, org_registry, competitor_allocator,
            radio, truncator, warnings, member_org=person.organisation,
        )
        competitors[competitor.id] = competitor


@dataclass
class _MemberEntry:
    member: IofTeamMember
    result: IofResult
    leg: int
    leg_order: int
    index: int


def _team_member_entries(team: IofTeam, warnings: list[str]) -> list[_MemberEntry]:
    entries = []
    next_leg = 1
    for index, member in enumerate(team.members, start=1):
        if not member.results:
            continue
        result = member.results[0]
        leg = result.leg if result.leg and result.leg > 0 else next_leg
        if leg > MAX_TINYINT:
            warnings.append(
                gettext(
                    "Équipe « %(name)s » : fraction %(leg)s hors limites, "
                    "ramenée à %(max)s."
                ) % {'name': team.name or '?', 'leg': leg, 'max': MAX_TINYINT}
            )
            leg = MAX_TINYINT
        next_leg = max(next_leg, leg + 1)
        leg_order = result.leg_order if result.leg_order and result.leg_order > 0 else index
        entries.append(
            _MemberEntry(
                member=member,
                result=result,
                leg=leg,
                leg_order=leg_order,
                index=index,
            )
        )
    return entries


def _member_quality(entry: _MemberEntry) -> tuple[int, int, int, int]:
    stat = entry.result.stat
    rt = entry.result.time_tenths or 0
    if stat == STAT_OK and rt > 0:
        return (0, rt, entry.leg_order, entry.index)
    if stat == STAT_OK:
        return (1, 0, entry.leg_order, entry.index)
    return (2, 0, entry.leg_order, entry.index)


def _make_team(team: IofTeam, class_id: int, max_leg: int,
               member_rows: list[tuple[_MemberEntry, _MopCompetitor]],
               org_registry: _OrgRegistry, allocator: _Allocator,
               truncator: _Truncator,
               warnings: list[str]) -> _MopTeam:
    by_leg: dict[int, list[tuple[_MemberEntry, _MopCompetitor]]] = {}
    for entry, competitor in member_rows:
        by_leg.setdefault(entry.leg, []).append((entry, competitor))

    counting: dict[int, tuple[_MemberEntry, _MopCompetitor] | None] = {}
    for leg in range(1, max_leg + 1):
        entries = by_leg.get(leg, [])
        if len(entries) > 1:
            warnings.append(
                gettext(
                    "Équipe « %(name)s » : plusieurs membres pour la fraction "
                    "%(leg)s — le meilleur membre est utilisé pour le classement."
                ) % {'name': team.name or '?', 'leg': leg}
            )
        counting[leg] = min(entries, key=lambda item: _member_quality(item[0])) if entries else None

    missing = [leg for leg in range(1, max_leg + 1) if counting.get(leg) is None]
    stat = STAT_OK
    prel = 0
    rt = 0
    if max_leg == 0 or missing:
        stat = STAT_DNF
        if max_leg == 0:
            warnings.append(
                gettext("Équipe « %(name)s » : aucun membre classable — équipe DNF.") % {
                    'name': team.name or '?',
                }
            )
        else:
            warnings.append(
                gettext(
                    "Équipe « %(name)s » : aucun membre pour la fraction "
                    "%(leg)s — équipe DNF."
                ) % {'name': team.name or '?', 'leg': ', '.join(str(l) for l in missing)}
            )
    else:
        non_ok = []
        for leg in range(1, max_leg + 1):
            entry = counting[leg][0]  # type: ignore[index]
            if entry.result.stat != STAT_OK:
                non_ok.append(entry.result.stat)
        if non_ok:
            stat = non_ok[0]
        else:
            times = [
                counting[leg][0].result.time_tenths or 0  # type: ignore[index]
                for leg in range(1, max_leg + 1)
            ]
            if any(value <= 0 for value in times):
                stat = STAT_DNF
                warnings.append(
                    gettext(
                        "Équipe « %(name)s » : temps de fraction manquant — "
                        "équipe DNF."
                    ) % {'name': team.name or '?'}
                )
            else:
                stat = STAT_OK
                rt = sum(times)
                prel = 1 if any(
                    counting[leg][0].result.prel  # type: ignore[index]
                    for leg in range(1, max_leg + 1)
                ) else 0

    starts = [
        _clock_tenths(counting[leg][0].result.start)  # type: ignore[index]
        for leg in range(1, max_leg + 1)
        if counting.get(leg) is not None and counting[leg][0].result.start is not None  # type: ignore[index]
    ]
    st = min(starts) if starts else 0

    if team.organisations:
        org_id = org_registry.get(team.organisations[0])
    elif member_rows:
        org_id = member_rows[0][1].org
    else:
        org_id = 0

    team_id = allocator.allocate_preferred(team.entry_id)
    name = truncator(team.name, 64, "nom d'équipe") or f'Team {team_id}'

    rows: list[tuple[int, int, int]] = []
    for leg in range(1, max_leg + 1):
        entries = by_leg.get(leg, [])
        if not entries:
            continue
        primary = counting.get(leg)
        entries_sorted = sorted(
            entries,
            key=lambda item: (
                0 if primary is not None and item[0] is primary[0] else 1,
                item[0].leg_order,
                item[0].index,
            ),
        )
        for ord_, (_, competitor) in enumerate(entries_sorted):
            rows.append((leg, ord_, competitor.id))

    return _MopTeam(
        id=team_id,
        name=name,
        org=org_id,
        cls=class_id,
        stat=stat,
        st=st,
        rt=rt,
        prel=prel,
        members=rows,
    )


def _build_relay_class(class_obj: _MopClass,
                       class_result: IofClassResult,
                       org_registry: _OrgRegistry,
                       control_registry: _ControlRegistry,
                       competitor_allocator: _Allocator,
                       team_allocator: _Allocator,
                       competitors: dict[int, _MopCompetitor],
                       teams: dict[int, _MopTeam],
                       truncator: _Truncator,
                       warnings: list[str]):
    team_entries: list[tuple[IofTeam, list[_MemberEntry]]] = []
    all_legs: set[int] = set()
    for team in class_result.teams:
        entries = _team_member_entries(team, warnings)
        team_entries.append((team, entries))
        all_legs.update(entry.leg for entry in entries)
    max_leg = max(all_legs) if all_legs else 0

    canonical_by_leg: dict[int, _CanonicalCourse] = {}
    for leg in sorted(all_legs):
        sequences = [
            _sequence_from_splits(entry.result.splits)
            for _, entries in team_entries
            for entry in entries
            if entry.leg == leg
        ]
        canonical = _canonical_sequence(
            sequences, f'{class_obj.name} (fraction {leg})',
            control_registry, warnings,
        )
        canonical_by_leg[leg] = canonical
        if canonical.ids:
            class_obj.controls_by_leg[leg] = canonical.ids

    for team, entries in team_entries:
        member_rows: list[tuple[_MemberEntry, _MopCompetitor]] = []
        fallback_org = team.organisations[0] if team.organisations else None
        for entry in entries:
            if entry.member.person is None:
                warnings.append(
                    gettext(
                        "Équipe « %(name)s » : membre sans personne à la "
                        "fraction %(leg)s — ignoré."
                    ) % {'name': team.name or '?', 'leg': entry.leg}
                )
                continue
            canonical = canonical_by_leg.get(entry.leg)
            runner_name = _person_name(entry.member.person)
            radio = _map_splits(
                entry.result.splits, canonical, warnings, runner_name,
            ) if canonical is not None else []
            competitor = _make_competitor(
                entry.member.person,
                entry.result,
                class_obj.id,
                org_registry,
                competitor_allocator,
                radio,
                truncator,
                warnings,
                member_org=entry.member.organisation,
                fallback_org=fallback_org,
            )
            competitors[competitor.id] = competitor
            member_rows.append((entry, competitor))

        team_obj = _make_team(
            team, class_obj.id, max_leg, member_rows, org_registry,
            team_allocator, truncator, warnings,
        )
        teams[team_obj.id] = team_obj


def build_mop_model(parsed: IofResultList, metadata: dict,
                    warnings: list[str]) -> _MopModel:
    """Construit le modèle MOP intermédiaire à partir du document IOF."""
    truncator = _Truncator(warnings)
    control_registry = _ControlRegistry(truncator)
    class_registry = _ClassRegistry(_Allocator(), truncator, warnings)
    org_registry = _OrgRegistry(_Allocator(), truncator, warnings)
    competitor_allocator = _Allocator(warnings, 'coureur')
    team_allocator = _Allocator(warnings, 'équipe')

    competitors: dict[int, _MopCompetitor] = {}
    teams: dict[int, _MopTeam] = {}

    for index, class_result in enumerate(parsed.classes, start=1):
        class_obj = class_registry.get(class_result, index * 10)
        if class_result.teams:
            _build_relay_class(
                class_obj, class_result, org_registry, control_registry,
                competitor_allocator, team_allocator, competitors, teams,
                truncator, warnings,
            )
        else:
            _build_individual_class(
                class_obj, class_result, org_registry, control_registry,
                competitor_allocator, competitors, truncator, warnings,
            )

    truncator.add_warning()
    return _MopModel(
        competition=metadata,
        controls=control_registry.controls,
        classes=class_registry.classes,
        orgs=org_registry.orgs,
        competitors=competitors,
        teams=teams,
    )


# ─── Métadonnées de la compétition ───────────────────────────────────────────

def _read_existing_metadata(cid: int | None) -> dict[str, str]:
    if cid is None:
        return {}
    try:
        row = Mopcompetition.objects.filter(cid=cid, id=1).first()
    except Exception as exc:
        raise IofImportError(
            gettext("Impossible de lire les informations actuelles de la course.")
        ) from exc
    if row is None:
        return {}

    data: dict[str, str] = {}
    for field_name in ('name', 'organizer', 'homepage'):
        value = getattr(row, field_name, None)
        if isinstance(value, str):
            data[field_name] = value
    value = getattr(row, 'date', None)
    if isinstance(value, datetime):
        data['date'] = value.date().isoformat()
    elif isinstance(value, date):
        data['date'] = value.isoformat()
    elif isinstance(value, str):
        parsed = _parse_date(value)
        if parsed is not None:
            data['date'] = parsed.isoformat()
    return data


def _resolve_competition_metadata(parsed: IofResultList, cid: int | None,
                                  use_event_metadata: bool,
                                  warnings: list[str]) -> dict[str, str]:
    existing = _read_existing_metadata(cid)

    iof_date = None
    if parsed.race_number is not None:
        for race in parsed.event.races:
            if race.number == parsed.race_number and race.date is not None:
                iof_date = race.date.isoformat()
                break
    if iof_date is None and parsed.event.date is not None:
        iof_date = parsed.event.date.isoformat()
    if iof_date is None:
        for race in parsed.event.races:
            if race.date is not None:
                iof_date = race.date.isoformat()
                break

    iof = {
        'name': parsed.event.name,
        'date': iof_date or '',
        'organizer': parsed.event.organiser,
        'homepage': parsed.event.homepage,
    }

    if use_event_metadata or not existing:
        source, fallback = iof, existing
    else:
        source, fallback = existing, iof

    metadata = {
        field_name: source.get(field_name) or fallback.get(field_name) or ''
        for field_name in ('name', 'date', 'organizer', 'homepage')
    }
    if not metadata['date']:
        metadata['date'] = date.today().isoformat()
        warnings.append(
            gettext("La date de l'événement est absente : date du jour utilisée.")
        )
    if not metadata['name']:
        metadata['name'] = f'Course {cid}' if cid is not None else gettext('Course')

    metadata['name'] = _clean_text(metadata['name'], 64, 'nom de la course', warnings)
    metadata['organizer'] = _clean_text(metadata['organizer'], 64, 'organisateur', warnings)
    metadata['homepage'] = _clean_text(metadata['homepage'], 128, 'site web', warnings)
    if not _parse_date(metadata['date']):
        warnings.append(
            gettext("Date de course invalide : date du jour utilisée.")
        )
        metadata['date'] = date.today().isoformat()
    return metadata


# ─── Génération du document MOP ──────────────────────────────────────────────

def _mop_tag(name: str) -> str:
    return f'{{{MOP_NS}}}{name}'


def _class_radio_attr(class_obj: _MopClass) -> str:
    if not class_obj.controls_by_leg:
        return ''
    max_leg = max(class_obj.controls_by_leg)
    parts = []
    for leg in range(1, max_leg + 1):
        parts.append(','.join(str(ctrl) for ctrl in class_obj.controls_by_leg.get(leg, [])))
    return ';'.join(parts)


def build_mop_xml(model: _MopModel) -> bytes:
    """Sérialise le modèle en document MOPComplete (namespace MeOS)."""
    ET.register_namespace('', MOP_NS)
    root = ET.Element(_mop_tag('MOPComplete'))

    competition = ET.SubElement(
        root, _mop_tag('competition'),
        {
            'date': model.competition.get('date', ''),
            'organizer': model.competition.get('organizer', ''),
            'homepage': model.competition.get('homepage', ''),
        },
    )
    competition.text = model.competition.get('name', '')

    for control in sorted(model.controls.values(), key=lambda item: item.id):
        elem = ET.SubElement(root, _mop_tag('ctrl'), {'id': str(control.id)})
        elem.text = control.name

    for class_obj in sorted(model.classes.values(), key=lambda item: (item.ord, item.id)):
        attrs = {'id': str(class_obj.id), 'ord': str(class_obj.ord)}
        radio = _class_radio_attr(class_obj)
        if radio:
            attrs['radio'] = radio
        elem = ET.SubElement(root, _mop_tag('cls'), attrs)
        elem.text = class_obj.name

    for org in sorted(model.orgs.values(), key=lambda item: item.id):
        attrs = {'id': str(org.id)}
        if org.nat:
            attrs['nat'] = org.nat
        elem = ET.SubElement(root, _mop_tag('org'), attrs)
        elem.text = org.name

    for competitor in sorted(model.competitors.values(), key=lambda item: item.id):
        attrs = {'id': str(competitor.id)}
        if competitor.card:
            attrs['card'] = competitor.card
        elem = ET.SubElement(root, _mop_tag('cmp'), attrs)

        base_attrs = {
            'org': str(competitor.org),
            'cls': str(competitor.cls),
            'stat': str(competitor.stat),
            'st': str(competitor.st),
            'rt': str(competitor.rt),
        }
        if competitor.bib:
            base_attrs['bib'] = competitor.bib
        if competitor.nat:
            base_attrs['nat'] = competitor.nat
        if competitor.prel:
            base_attrs['prel'] = 'true'
        base = ET.SubElement(elem, _mop_tag('base'), base_attrs)
        base.text = competitor.name

        ET.SubElement(
            elem, _mop_tag('input'),
            {'it': str(competitor.it), 'tstat': str(competitor.tstat)},
        )

        if competitor.radio:
            radio_elem = ET.SubElement(elem, _mop_tag('radio'))
            radio_elem.text = ';'.join(
                f'{ctrl},{time}' for ctrl, time in competitor.radio
            )

    for team in sorted(model.teams.values(), key=lambda item: item.id):
        elem = ET.SubElement(root, _mop_tag('tm'), {'id': str(team.id)})
        base_attrs = {
            'org': str(team.org),
            'cls': str(team.cls),
            'stat': str(team.stat),
            'st': str(team.st),
            'rt': str(team.rt),
        }
        if team.prel:
            base_attrs['prel'] = 'true'
        base = ET.SubElement(elem, _mop_tag('base'), base_attrs)
        base.text = team.name

        if team.members:
            by_leg: dict[int, list[tuple[int, int]]] = {}
            for leg, ord_, rid in team.members:
                by_leg.setdefault(leg, []).append((ord_, rid))
            max_leg = max(by_leg)
            parts = []
            for leg in range(1, max_leg + 1):
                entries = sorted(by_leg.get(leg, []))
                parts.append(','.join(str(rid) for _, rid in entries))
            r_elem = ET.SubElement(elem, _mop_tag('r'))
            r_elem.text = ';'.join(parts)

    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


# ─── Rapport et point d'entrée ───────────────────────────────────────────────

def _course_hash(ctrl_ids: list[int]) -> str | None:
    if not ctrl_ids:
        return None
    key = ','.join(str(ctrl) for ctrl in ctrl_ids)
    return hashlib.md5(key.encode()).hexdigest()[:8]


def _make_report(parsed: IofResultList, model: _MopModel,
                 status: str) -> IofImportReport:
    course_hashes: list[str] = []
    for class_obj in model.classes.values():
        hash_value = _course_hash(class_obj.controls_by_leg.get(1, []))
        if hash_value and hash_value not in course_hashes:
            course_hashes.append(hash_value)
    return IofImportReport(
        status=status,
        race_number=parsed.race_number,
        competition_name=model.competition.get('name', ''),
        classes=len(model.classes),
        competitors=len(model.competitors),
        teams=len(model.teams),
        controls=len(model.controls),
        splits=sum(len(competitor.radio) for competitor in model.competitors.values()),
        warnings=list(parsed.warnings),
        class_ids=sorted(model.classes),
        course_hashes=course_hashes,
    )


def inspect_iof_result_list(xml_data: bytes | str, *,
                            cid: int | None = None,
                            race_number: int | None = None,
                            use_event_metadata: bool = False) -> IofImportReport:
    """Valide et convertit un fichier IOF sans écrire en base (dry-run)."""
    parsed = parse_iof_result_list(xml_data, race_number=race_number)
    metadata = _resolve_competition_metadata(
        parsed, cid, use_event_metadata, parsed.warnings,
    )
    model = build_mop_model(parsed, metadata, parsed.warnings)
    return _make_report(parsed, model, 'DRY-RUN')


def _invalidate_caches(cid: int, report: IofImportReport):
    try:
        cache.delete(f'raceindex:{cid}')
        for class_id in report.class_ids:
            cache.delete(f'live:{cid}:{class_id}')
        for hash_value in report.course_hashes:
            cache.delete(f'live:{cid}:{hash_value}')
    except Exception:
        logger.exception("iof_importer: cid=%s — échec de l'invalidation du cache", cid)


def import_iof_result_list(cid: int, xml_data: bytes | str, *,
                           race_number: int | None = None,
                           use_event_metadata: bool = False) -> IofImportReport:
    """Importe un fichier IOF ResultList dans la course ``cid``.

    Le document est converti en MOPComplete puis traité par
    :func:`process_mop_xml`, comme un envoi MeOS. Un import réussi remplace
    donc intégralement les résultats existants de la course.

    Returns:
        Un rapport d'import (statut ``OK`` ou ``FROZEN``).

    Raises:
        IofImportError: fichier invalide, course ambiguë, données
            inexploitables ou échec MOP.
    """
    parsed = parse_iof_result_list(xml_data, race_number=race_number)
    metadata = _resolve_competition_metadata(
        parsed, cid, use_event_metadata, parsed.warnings,
    )
    model = build_mop_model(parsed, metadata, parsed.warnings)
    report = _make_report(parsed, model, 'OK')

    logger.info(
        "iof_importer: cid=%s — import IOF course=%s (%d classes, %d concurrents, %d équipes)",
        cid, parsed.race_number, report.classes, report.competitors, report.teams,
    )
    mop_status = process_mop_xml(cid, build_mop_xml(model))
    if mop_status == 'FROZEN':
        report.status = 'FROZEN'
        logger.warning("iof_importer: cid=%s — course gelée, import refusé", cid)
        return report
    if mop_status != 'OK':
        raise IofImportError(
            gettext("L'import a échoué (statut MOP : %(status)s).") % {
                'status': mop_status,
            }
        )

    _invalidate_caches(cid, report)
    return report
