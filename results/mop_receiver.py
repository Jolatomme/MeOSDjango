"""
mop_receiver.py — Réception des mises à jour MeOS en temps réel.

MeOS pousse du XML vers cette URL à chaque changement de résultat.
Équivalent Python/Django du update.php de MeOS Online Results.

Format XML MeOS (MOP - MeOS Online Protocol) :
  Racine   : <MOPComplete> (reset complet) ou <MOPDiff> (mise à jour partielle)
  Namespace: xmlns="http://www.melin.nu/mop"
  Enfants  : <cmp>, <tm>, <cls>, <org>, <ctrl>, <competition>

Référence : MeOS Online Protocol (mop.xsd)
"""

import logging
import re
from xml.etree import ElementTree as ET

from django.db import connection, transaction

logger = logging.getLogger(__name__)

# Namespace MeOS MOP
MOP_NS = 'http://www.melin.nu/mop'


# ─── Réponse MOP ──────────────────────────────────────────────────────────────

MOP_STATUS_XML = '<?xml version="1.0"?><MOPStatus status="{status}"></MOPStatus>'


def mop_response(status: str) -> str:
    """Retourne le XML de statut attendu par MeOS."""
    return MOP_STATUS_XML.format(status=status)


# ─── Utilitaire namespace ──────────────────────────────────────────────────────

_NS_RE = re.compile(r'^\{[^}]+\}')


def _strip_ns(tag: str) -> str:
    """Supprime le préfixe de namespace d'un tag ElementTree.

    '{http://www.melin.nu/mop}MOPComplete' → 'MOPComplete'
    """
    return _NS_RE.sub('', tag)


def _find(elem: ET.Element, local_name: str) -> ET.Element | None:
    """Cherche un élément enfant par nom local, avec ou sans namespace."""
    # Chercher d'abord avec le namespace MeOS, puis sans namespace
    result = elem.find(f'{{{MOP_NS}}}{local_name}')
    if result is None:
        result = elem.find(local_name)
    return result


def _parse_id(value_str: str) -> int:
    """Extrait le numéro entier d'un identifiant MeOS en ignorant les suffixes parasites.

    MeOS peut suffixer les identifiants de postes avec "-1" ou d'autres
    caractères non numériques (ex: "31-1" → 31, "70" → 70).
    Seule la séquence de chiffres en tête de chaîne est conservée.

    Raises:
        ValueError: si aucun chiffre n'est trouvé en tête.
    """
    m = re.match(r'(\d+)', value_str.strip())
    if not m:
        raise ValueError(f"Identifiant invalide : {value_str!r}")
    return int(m.group(1))


# ─── Reset complet ────────────────────────────────────────────────────────────

MEOS_TABLES = [
    'mopRadio', 'mopClassControl', 'mopTeamMember',
    'mopCompetitor', 'mopTeam', 'mopOrganization',
    'mopClass', 'mopControl', 'mopCompetition',
]


def clear_competition(cid: int):
    """Efface toutes les données d'une compétition (MOPComplete)."""
    with connection.cursor() as cur:
        for table in MEOS_TABLES:
            cur.execute(f"DELETE FROM `{table}` WHERE cid = %s", [cid])
    logger.info("clear_competition: cid=%s effacé", cid)


# ─── Helpers bas niveau ───────────────────────────────────────────────────────

def _upsert(table: str, cid: int, id_: int, fields: dict):
    """INSERT ou UPDATE selon l'existence de la ligne (cid, id)."""
    with connection.cursor() as cur:
        cur.execute(
            f"SELECT 1 FROM `{table}` WHERE cid=%s AND id=%s",
            [cid, id_]
        )
        exists = cur.fetchone()

        set_clause = ", ".join(f"`{k}`=%s" for k in fields)
        values     = list(fields.values())

        if exists:
            cur.execute(
                f"UPDATE `{table}` SET {set_clause} WHERE cid=%s AND id=%s",
                values + [cid, id_]
            )
        else:
            col_clause = ", ".join(f"`{k}`" for k in fields)
            ph_clause  = ", ".join(["%s"] * len(fields))
            cur.execute(
                f"INSERT INTO `{table}` (cid, id, {col_clause}) "
                f"VALUES (%s, %s, {ph_clause})",
                [cid, id_] + values
            )


def _update_link_table(table: str, cid: int, id_: int,
                       field_name: str, encoded: str):
    """Recharge une table de liaison (mopClassControl, mopTeamMember).

    Format encoded : "v1,v2;v3,v4"
      - ';' sépare les fractions (leg), numérotées à partir de 1
      - ',' sépare les éléments au sein d'une fraction (ord, base 0)

    Exemples :
      "70"         → leg=1 ord=0 value=70
      "31,32;33"   → leg=1 ord=0 ctrl=31 / leg=1 ord=1 ctrl=32 / leg=2 ord=0 ctrl=33
      "101,102;103"→ leg=1 ord=0 rid=101 / leg=1 ord=1 rid=102 / leg=2 ord=0 rid=103
    """
    with connection.cursor() as cur:
        cur.execute(
            f"DELETE FROM `{table}` WHERE cid=%s AND id=%s",
            [cid, id_]
        )
        rows = []
        for leg_num, leg_str in enumerate(encoded.split(';'), start=1):
            leg_str = leg_str.strip()
            if not leg_str:
                continue
            for ord_idx, value_str in enumerate(leg_str.split(',')):
                value_str = value_str.strip()
                if value_str:
                    rows.append((cid, id_, leg_num, ord_idx, _parse_id(value_str)))

        if rows:
            cur.executemany(
                f"INSERT INTO `{table}` (cid, id, leg, ord, `{field_name}`) "
                f"VALUES (%s, %s, %s, %s, %s)",
                rows
            )


# ─── Processeurs par type d'élément ──────────────────────────────────────────

def process_competition(cid: int, elem: ET.Element):
    """
    <competition date="2012-08-12" organizer="OK Linné"
                 homepage="http://..." zerotime="09:00:00">
      Nom de la compétition
    </competition>
    """
    fields = {
        'name':      (elem.text or '').strip(),
        'date':      elem.get('date', '2000-01-01'),
        'organizer': elem.get('organizer', ''),
        'homepage':  elem.get('homepage', ''),
    }
    _upsert('mopCompetition', cid, 1, fields)


def process_control(cid: int, elem: ET.Element):
    """<ctrl id="70">Radio</ctrl>"""
    id_ = int(elem.get('id'))
    _upsert('mopControl', cid, id_, {
        'name': (elem.text or '').strip(),
    })


def process_class(cid: int, elem: ET.Element):
    """
    <cls id="1" ord="10" radio="70">H21E</cls>
    <cls id="2" ord="20" radio="31,32;33">Relais</cls>  ← leg1: 31,32 / leg2: 33
    <cls id="3" ord="30" radio="">H35</cls>             ← pas de radio

    BUG CORRIGÉ : radio est un ATTRIBUT, pas un élément enfant.
    """
    id_ = int(elem.get('id'))

    if elem.get('delete') == 'true':
        with connection.cursor() as cur:
            # Nettoyer aussi les contrôles associés
            cur.execute(
                "DELETE FROM mopClassControl WHERE cid=%s AND id=%s",
                [cid, id_]
            )
            cur.execute(
                "DELETE FROM mopClass WHERE cid=%s AND id=%s",
                [cid, id_]
            )
        return

    name = (elem.text or '').strip()
    ord_ = int(elem.get('ord', 0))
    _upsert('mopClass', cid, id_, {'name': name, 'ord': ord_})

    # radio est un ATTRIBUT (ex: radio="70" ou radio="31,32;33" ou radio="")
    radio_attr = elem.get('radio', '').strip()
    if radio_attr:
        _update_link_table('mopClassControl', cid, id_, 'ctrl', radio_attr)
    else:
        # Pas de radio : supprimer les éventuels anciens contrôles
        with connection.cursor() as cur:
            cur.execute(
                "DELETE FROM mopClassControl WHERE cid=%s AND id=%s",
                [cid, id_]
            )


def process_organization(cid: int, elem: ET.Element):
    """
    <org id="255" nat="SWE">Länna IF</org>
    <org delete="true" id="515"></org>
    """
    id_ = int(elem.get('id'))

    if elem.get('delete') == 'true':
        with connection.cursor() as cur:
            cur.execute(
                "DELETE FROM mopOrganization WHERE cid=%s AND id=%s",
                [cid, id_]
            )
        return

    _upsert('mopOrganization', cid, id_, {
        'name': (elem.text or '').strip(),
    })


def process_competitor(cid: int, elem: ET.Element):
    """
    <cmp id="5490" card="12345" competing="true">
      <base org="515" cls="1" stat="1" st="370800" rt="71480"
            bib="100" nat="SWE" prel="true">Jonas Svensson</base>
      <input it="0" tstat="1"/>
      <radio>70,27160</radio>          ← ctrl_id,rt  séparés par ;
    </cmp>

    Attributs notables (stockés si présents) :
      stat=0  : Unknown (en course)
      stat=1  : OK
      stat=15 : OCC (Out-of-competition, v3.7)
      prel    : résultat préliminaire (arrivé mais carte non lue)
      competing : a pointé mais pas encore arrivé
    """
    id_ = int(elem.get('id'))

    if elem.get('delete') == 'true':
        with connection.cursor() as cur:
            cur.execute(
                "DELETE FROM mopCompetitor WHERE cid=%s AND id=%s",
                [cid, id_]
            )
            cur.execute(
                "DELETE FROM mopRadio WHERE cid=%s AND id=%s",
                [cid, id_]
            )
        return

    base = _find(elem, 'base')
    if base is None:
        logger.warning("process_competitor: <base> manquant pour id=%s", id_)
        return

    fields = {
        'name':  (base.text or '').strip(),
        'org':   int(base.get('org', 0)),
        'cls':   int(base.get('cls', 0)),
        'stat':  int(base.get('stat', 0)),
        'st':    int(base.get('st', 0)),
        'rt':    int(base.get('rt', 0)),
        'tstat': 0,
        'it':    0,
    }

    inp = _find(elem, 'input')
    if inp is not None:
        fields['it']    = int(inp.get('it', 0))
        fields['tstat'] = int(inp.get('tstat', 0))

    _upsert('mopCompetitor', cid, id_, fields)

    # Temps radio : toujours supprimer et réinsérer
    radio_elem = _find(elem, 'radio')
    with connection.cursor() as cur:
        cur.execute(
            "DELETE FROM mopRadio WHERE cid=%s AND id=%s",
            [cid, id_]
        )
        if radio_elem is not None and radio_elem.text:
            rows = []
            for entry in radio_elem.text.strip().split(';'):
                entry = entry.strip()
                if not entry:
                    continue
                parts = entry.split(',')
                if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                    rows.append((
                        cid, id_,
                        _parse_id(parts[0]),
                        int(parts[1].strip()),
                    ))
            if rows:
                cur.executemany(
                    "REPLACE INTO mopRadio (cid, id, ctrl, rt) "
                    "VALUES (%s, %s, %s, %s)",
                    rows
                )


def process_team(cid: int, elem: ET.Element):
    """
    <tm id="456">
      <base org="3" cls="10" stat="1" st="0" rt="12000">Equipe A</base>
      <r>101,102;103</r>   ← membres : leg1=rid101,rid102 / leg2=rid103
    </tm>

    rt et stat sont le résultat TOTAL de l'équipe (défini par le dernier leg).
    """
    id_ = int(elem.get('id'))

    if elem.get('delete') == 'true':
        with connection.cursor() as cur:
            cur.execute(
                "DELETE FROM mopTeam WHERE cid=%s AND id=%s",
                [cid, id_]
            )
            cur.execute(
                "DELETE FROM mopTeamMember WHERE cid=%s AND id=%s",
                [cid, id_]
            )
        return

    base = _find(elem, 'base')
    if base is None:
        logger.warning("process_team: <base> manquant pour id=%s", id_)
        return

    fields = {
        'name': (base.text or '').strip(),
        'org':  int(base.get('org', 0)),
        'cls':  int(base.get('cls', 0)),
        'stat': int(base.get('stat', 0)),
        'st':   int(base.get('st', 0)),
        'rt':   int(base.get('rt', 0)),
    }
    _upsert('mopTeam', cid, id_, fields)

    r_elem = _find(elem, 'r')
    if r_elem is not None and r_elem.text:
        _update_link_table('mopTeamMember', cid, id_, 'rid',
                           r_elem.text.strip())


# ─── Point d'entrée principal ─────────────────────────────────────────────────

PROCESSORS = {
    'cmp':         process_competitor,
    'tm':          process_team,
    'cls':         process_class,
    'org':         process_organization,
    'ctrl':        process_control,
    'competition': process_competition,
}


def process_mop_xml(cid: int, xml_data: bytes) -> str:
    """Parse et traite un document MOP (MOPComplete ou MOPDiff).

    Gère le namespace MeOS : xmlns="http://www.melin.nu/mop"
    ElementTree préfixe les tags avec {http://www.melin.nu/mop},
    on les strip avant de les dispatcher.

    Returns:
        Statut MeOS : 'OK', 'BADXML', etc.
    """
    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as exc:
        logger.error("process_mop_xml: XML invalide — %s", exc)
        return 'BADXML'

    root_name = _strip_ns(root.tag)

    if root_name not in ('MOPComplete', 'MOPDiff'):
        logger.error("process_mop_xml: racine inconnue '%s' (tag complet: '%s')",
                     root_name, root.tag)
        return 'BADXML'

    count = 0
    with transaction.atomic():
        if root_name == 'MOPComplete':
            clear_competition(cid)

        for child in root:
            tag       = _strip_ns(child.tag)
            processor = PROCESSORS.get(tag)
            count    += 1
            if processor:
                try:
                    processor(cid, child)
                except Exception as exc:
                    logger.exception(
                        "process_mop_xml: erreur sur <%s> id=%s — %s",
                        tag, child.get('id', '?'), exc
                    )
                    # On continue : une erreur sur un élément ne bloque pas les autres
            else:
                logger.debug("process_mop_xml: tag ignoré <%s>", tag)

    logger.info("process_mop_xml: cid=%s %s traité (%d éléments)",
                cid, root_name, count)
    return 'OK'
