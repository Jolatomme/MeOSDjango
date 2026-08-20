"""
Tests unitaires pour mop_receiver.py.

Couvre les corrections issues de l'analyse du protocole MOP :
  1. Namespace xmlns="http://www.melin.nu/mop" géré par _strip_ns()
  2. Radio de <cls> est un attribut, pas un élément enfant
  3. Suppression <cls> nettoie aussi mopClassControl
  4. Suppression <cmp> nettoie aussi mopRadio
  5. Suppression <tm> nettoie aussi mopTeamMember
"""

from unittest.mock import patch, MagicMock, call
from xml.etree import ElementTree as ET
import pytest

from results.mop_receiver import (
    process_mop_xml, process_competitor, process_team,
    process_class, process_organization, process_control,
    process_competition, _update_link_table, mop_response,
    _strip_ns, _parse_id, MOP_NS,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def xml_bytes(content: str) -> bytes:
    """Enveloppe dans un MOPDiff avec namespace."""
    return (
        f'<MOPDiff xmlns="{MOP_NS}">{content}</MOPDiff>'
    ).encode()


def xml_bytes_no_ns(content: str) -> bytes:
    """MOPDiff sans namespace (MeOS ancien)."""
    return f'<MOPDiff>{content}</MOPDiff>'.encode()


def elem(tag, attribs=None, text=None, children=None):
    el = ET.Element(tag, attrib=attribs or {})
    if text:
        el.text = text
    for ctag, cattribs, ctext in (children or []):
        c = ET.SubElement(el, ctag, attrib=cattribs or {})
        if ctext:
            c.text = ctext
    return el


def ns_elem(tag, attribs=None, text=None, children=None):
    """Élément avec namespace MeOS (comme ElementTree le retourne après parsing)."""
    full_tag = f'{{{MOP_NS}}}{tag}'
    el = ET.Element(full_tag, attrib=attribs or {})
    if text:
        el.text = text
    for ctag, cattribs, ctext in (children or []):
        c = ET.SubElement(el, f'{{{MOP_NS}}}{ctag}', attrib=cattribs or {})
        if ctext:
            c.text = ctext
    return el


# ─── Tests _strip_ns ──────────────────────────────────────────────────────────

class TestStripNs:
    def test_avec_namespace(self):
        assert _strip_ns(f'{{{MOP_NS}}}MOPComplete') == 'MOPComplete'

    def test_sans_namespace(self):
        assert _strip_ns('MOPComplete') == 'MOPComplete'

    def test_tag_enfant(self):
        assert _strip_ns(f'{{{MOP_NS}}}cmp') == 'cmp'


# ─── Tests mop_response ───────────────────────────────────────────────────────

class TestMopResponse:
    def test_ok(self):
        assert 'status="OK"' in mop_response('OK')

    def test_badpwd(self):
        assert 'status="BADPWD"' in mop_response('BADPWD')

    def test_xml_declaration(self):
        assert mop_response('OK').startswith('<?xml')


# ─── Tests process_mop_xml — namespace ───────────────────────────────────────

class TestProcessMopXmlNamespace:
    """Vérifie que le namespace MeOS est correctement géré."""

    @patch('results.mop_receiver.transaction')
    @patch('results.mop_receiver.clear_competition')
    def test_namespace_mop_complete(self, mock_clear, mock_tx):
        mock_tx.atomic.return_value.__enter__ = lambda s: s
        mock_tx.atomic.return_value.__exit__  = MagicMock(return_value=False)

        xml = f'<MOPComplete xmlns="{MOP_NS}"></MOPComplete>'.encode()
        status = process_mop_xml(1, xml)

        assert status == 'OK'
        mock_clear.assert_called_once_with(1)

    @patch('results.mop_receiver.transaction')
    @patch('results.mop_receiver.clear_competition')
    def test_namespace_mop_diff(self, mock_clear, mock_tx):
        mock_tx.atomic.return_value.__enter__ = lambda s: s
        mock_tx.atomic.return_value.__exit__  = MagicMock(return_value=False)

        xml = f'<MOPDiff xmlns="{MOP_NS}"></MOPDiff>'.encode()
        status = process_mop_xml(1, xml)

        assert status == 'OK'
        mock_clear.assert_not_called()

    @patch('results.mop_receiver.transaction')
    @patch('results.mop_receiver.clear_competition')
    def test_sans_namespace(self, mock_clear, mock_tx):
        """MeOS ancien sans namespace — doit aussi fonctionner."""
        mock_tx.atomic.return_value.__enter__ = lambda s: s
        mock_tx.atomic.return_value.__exit__  = MagicMock(return_value=False)

        xml = b'<MOPComplete></MOPComplete>'
        status = process_mop_xml(1, xml)
        assert status == 'OK'

    def test_xml_invalide(self):
        assert process_mop_xml(1, b'pas du xml') == 'BADXML'

    def test_racine_inconnue(self):
        assert process_mop_xml(1, b'<AutreTag></AutreTag>') == 'BADXML'

    @patch('results.mop_receiver.transaction')
    @patch('results.mop_receiver.clear_competition')
    def test_dispatch_avec_namespace(self, mock_clear, mock_tx):
        """Les enfants avec namespace sont bien dispatchés.
        
        PROCESSORS est construit à l'import avec des références directes :
        patcher le nom du module ne suffit pas, il faut patcher le dict.
        """
        mock_tx.atomic.return_value.__enter__ = lambda s: s
        mock_tx.atomic.return_value.__exit__  = MagicMock(return_value=False)

        mock_cmp = MagicMock()
        xml = (
            f'<MOPComplete xmlns="{MOP_NS}">'
            '<cmp id="1"><base org="1" cls="2" stat="1" '
            'st="0" rt="6000">Alice</base></cmp>'
            '</MOPComplete>'
        ).encode()

        with patch.dict('results.mop_receiver.PROCESSORS', {'cmp': mock_cmp}):
            status = process_mop_xml(1, xml)

        assert status == 'OK'
        mock_cmp.assert_called_once()

    @patch('results.mop_receiver.transaction')
    @patch('results.mop_receiver.clear_competition')
    def test_exemple_complet_du_protocole(self, mock_clear, mock_tx):
        """Teste l'exemple exact donné dans le document MOP.
        
        Utilise patch.dict sur PROCESSORS pour intercepter les appels,
        car le dict contient des références directes aux fonctions.
        """
        mock_tx.atomic.return_value.__enter__ = lambda s: s
        mock_tx.atomic.return_value.__exit__  = MagicMock(return_value=False)

        xml = f'''<MOPComplete xmlns="{MOP_NS}">
          <competition date="2012-08-12" organizer="OK Linné"
                       homepage="http://www.oklinne.nu"
                       zerotime="09:00:00">Linnéklassikern</competition>
          <ctrl id="70">Radio</ctrl>
          <cls id="1" ord="10" radio="70">H21E</cls>
          <cls id="19" ord="190" radio="">H35</cls>
          <org id="255" nat="SWE">Länna IF</org>
          <org id="515" nat="SWE">OK Österåker</org>
          <cmp id="5490" card="12345">
            <base org="515" cls="1" stat="1" st="370800"
                  rt="71480" bib="100" nat="SWE">Jonas Svensson</base>
            <radio>70,27160</radio>
          </cmp>
        </MOPComplete>'''.encode()

        mc    = MagicMock()
        mctrl = MagicMock()
        mcls  = MagicMock()
        morg  = MagicMock()
        mcmp  = MagicMock()

        with patch.dict('results.mop_receiver.PROCESSORS', {
            'competition': mc,
            'ctrl':        mctrl,
            'cls':         mcls,
            'org':         morg,
            'cmp':         mcmp,
        }):
            status = process_mop_xml(1, xml)

        assert status == 'OK'
        mc.assert_called_once()
        mctrl.assert_called_once()
        assert mcls.call_count == 2
        assert morg.call_count == 2
        mcmp.assert_called_once()


# ─── Tests process_class — BUG CORRIGÉ : radio est un attribut ───────────────

class TestProcessClass:
    """
    CORRECTION PRINCIPALE : dans le protocole MOP, les radio controls
    sont dans l'attribut radio="..." de <cls>, pas dans un élément enfant.
    Exemple : <cls id="1" ord="10" radio="70">H21E</cls>
    """

    @patch('results.mop_receiver._update_link_table')
    @patch('results.mop_receiver._upsert')
    def test_radio_attribut_simple(self, mock_upsert, mock_link):
        """<cls radio="70"> — un seul contrôle, attribut."""
        el = elem('cls', {'id': '1', 'ord': '10', 'radio': '70'}, text='H21E')
        process_class(1, el)

        mock_upsert.assert_called_once()
        mock_link.assert_called_once_with('mopClassControl', 1, 1, 'ctrl', '70')

    @patch('results.mop_receiver._update_link_table')
    @patch('results.mop_receiver._upsert')
    def test_radio_attribut_multi_leg(self, mock_upsert, mock_link):
        """<cls radio="31,32;33"> — 2 legs, attribut."""
        el = elem('cls', {'id': '2', 'ord': '20', 'radio': '31,32;33'}, text='Relais')
        process_class(1, el)
        mock_link.assert_called_once_with('mopClassControl', 1, 2, 'ctrl', '31,32;33')

    @patch('results.mop_receiver.connection')
    @patch('results.mop_receiver._upsert')
    def test_radio_vide_supprime_anciens_controles(self, mock_upsert, mock_conn):
        """<cls radio=""> — pas de radio, supprimer les anciens contrôles."""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        el = elem('cls', {'id': '19', 'ord': '190', 'radio': ''}, text='H35')
        process_class(1, el)

        sql = cur.execute.call_args[0][0]
        assert 'DELETE' in sql
        assert 'ClassControl' in sql

    @patch('results.mop_receiver.connection')
    def test_delete_nettoie_classcontrol(self, mock_conn):
        """Suppression d'une classe doit aussi supprimer mopClassControl."""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        el = elem('cls', {'id': '1', 'delete': 'true'})
        process_class(1, el)

        deleted_tables = [c[0][0] for c in cur.execute.call_args_list]
        assert any('ClassControl' in s for s in deleted_tables)
        assert any('mopClass' in s and 'Control' not in s for s in deleted_tables)

    @patch('results.mop_receiver._update_link_table')
    @patch('results.mop_receiver._upsert')
    def test_radio_attribut_avec_namespace(self, mock_upsert, mock_link):
        """Fonctionne aussi avec les éléments portant le namespace MeOS."""
        el = ns_elem('cls', {'id': '1', 'ord': '10', 'radio': '70'}, text='H21E')
        process_class(1, el)
        mock_link.assert_called_once_with('mopClassControl', 1, 1, 'ctrl', '70')


# ─── Tests process_competitor ─────────────────────────────────────────────────

class TestProcessCompetitor:

    @patch('results.mop_receiver.connection')
    @patch('results.mop_receiver._upsert')
    def test_insertion_normale(self, mock_upsert, mock_conn):
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        el = elem('cmp', {'id': '5490', 'card': '12345'}, children=[
            ('base', {'org': '515', 'cls': '1', 'stat': '1',
                      'st': '370800', 'rt': '71480'}, 'Jonas Svensson'),
        ])
        process_competitor(1, el)

        _, called_cid, called_id, fields = mock_upsert.call_args[0]
        assert called_id == 5490
        assert fields['name'] == 'Jonas Svensson'
        assert fields['rt']   == 71480

    @patch('results.mop_receiver.connection')
    @patch('results.mop_receiver._upsert')
    def test_attribut_card_stocke(self, mock_upsert, mock_conn):
        """<cmp card="12345"> → le numéro de puce est enregistré."""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        el = elem('cmp', {'id': '5490', 'card': '12345'}, children=[
            ('base', {'org': '515', 'cls': '1', 'stat': '1',
                      'st': '370800', 'rt': '71480'}, 'Jonas Svensson'),
        ])
        process_competitor(1, el)

        fields = mock_upsert.call_args[0][3]
        assert fields['card'] == '12345'

    @patch('results.mop_receiver.connection')
    @patch('results.mop_receiver._upsert')
    def test_sans_attribut_card_ne_lecrase_pas(self, mock_upsert, mock_conn):
        """MOPDiff partiel sans card → pas de champ card (pas d'écrasement)."""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        el = elem('cmp', {'id': '1'}, children=[
            ('base', {'org': '1', 'cls': '1', 'stat': '1',
                      'st': '0', 'rt': '3000'}, 'Alice'),
        ])
        process_competitor(1, el)

        fields = mock_upsert.call_args[0][3]
        assert 'card' not in fields

    @patch('results.mop_receiver.connection')
    @patch('results.mop_receiver._upsert')
    def test_attribut_bib_stocke(self, mock_upsert, mock_conn):
        """<base bib="218"> → le dossard est enregistré."""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        el = elem('cmp', {'id': '5490'}, children=[
            ('base', {'org': '515', 'cls': '1', 'stat': '1',
                      'st': '370800', 'rt': '71480', 'bib': '218'},
             'Jonas Svensson'),
        ])
        process_competitor(1, el)

        fields = mock_upsert.call_args[0][3]
        assert fields['bib'] == '218'

    @patch('results.mop_receiver.connection')
    @patch('results.mop_receiver._upsert')
    def test_sans_attribut_bib_ne_lecrase_pas(self, mock_upsert, mock_conn):
        """MOPDiff partiel sans bib → pas de champ bib (pas d'écrasement)."""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        el = elem('cmp', {'id': '1'}, children=[
            ('base', {'org': '1', 'cls': '1', 'stat': '1',
                      'st': '0', 'rt': '3000'}, 'Alice'),
        ])
        process_competitor(1, el)

        fields = mock_upsert.call_args[0][3]
        assert 'bib' not in fields

    @patch('results.mop_receiver.connection')
    @patch('results.mop_receiver._upsert')
    def test_card_zero_efface_le_numero(self, mock_upsert, mock_conn):
        """<cmp card="0"> → le numéro de puce doit être retiré ('')."""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        el = elem('cmp', {'id': '5490', 'card': '0'}, children=[
            ('base', {'org': '515', 'cls': '1', 'stat': '1',
                      'st': '370800', 'rt': '71480'}, 'Jonas Svensson'),
        ])
        process_competitor(1, el)

        fields = mock_upsert.call_args[0][3]
        assert fields['card'] == ''

    @patch('results.mop_receiver.connection')
    @patch('results.mop_receiver._upsert')
    def test_radio_parse(self, mock_upsert, mock_conn):
        """<radio>70,27160</radio> → (cid, id, 70, 27160)"""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        el = elem('cmp', {'id': '1'}, children=[
            ('base', {'org': '1', 'cls': '1', 'stat': '1',
                      'st': '0', 'rt': '3000'}, 'Alice'),
            ('radio', {}, '70,27160'),
        ])
        process_competitor(1, el)

        rows = cur.executemany.call_args[0][1]
        assert (1, 1, 70, 27160) in rows

    @patch('results.mop_receiver.connection')
    @patch('results.mop_receiver._upsert')
    def test_radio_multiple(self, mock_upsert, mock_conn):
        """<radio>31,1200;32,2500</radio> → deux lignes."""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        el = elem('cmp', {'id': '1'}, children=[
            ('base', {'org': '1', 'cls': '1', 'stat': '1',
                      'st': '0', 'rt': '5000'}, 'Bob'),
            ('radio', {}, '31,1200;32,2500'),
        ])
        process_competitor(1, el)
        rows = cur.executemany.call_args[0][1]
        assert (1, 1, 31, 1200) in rows
        assert (1, 1, 32, 2500) in rows

    @patch('results.mop_receiver.connection')
    def test_delete_nettoie_radio(self, mock_conn):
        """Suppression d'un compétiteur doit aussi supprimer mopRadio."""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        el = elem('cmp', {'id': '5490', 'delete': 'true'})
        process_competitor(1, el)

        deleted = [c[0][0] for c in cur.execute.call_args_list]
        assert any('mopCompetitor' in s for s in deleted)
        assert any('mopRadio' in s for s in deleted)

    @patch('results.mop_receiver.connection')
    @patch('results.mop_receiver._upsert')
    def test_avec_namespace(self, mock_upsert, mock_conn):
        """Fonctionne avec des éléments portant le namespace."""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        el = ns_elem('cmp', {'id': '1'}, children=[
            ('base', {'org': '1', 'cls': '1', 'stat': '1',
                      'st': '0', 'rt': '5000'}, 'Carla'),
        ])
        process_competitor(1, el)
        mock_upsert.assert_called_once()


# ─── Tests process_team ───────────────────────────────────────────────────────

class TestProcessTeam:

    @patch('results.mop_receiver._update_link_table')
    @patch('results.mop_receiver._upsert')
    def test_insertion(self, mock_upsert, mock_link):
        el = elem('tm', {'id': '100'}, children=[
            ('base', {'org': '3', 'cls': '10', 'stat': '1',
                      'st': '0', 'rt': '12000'}, 'Equipe A'),
            ('r', {}, '101,102;103'),
        ])
        process_team(1, el)
        fields = mock_upsert.call_args[0][3]
        assert fields['name'] == 'Equipe A'
        mock_link.assert_called_once_with('mopTeamMember', 1, 100, 'rid', '101,102;103')

    @patch('results.mop_receiver.connection')
    def test_delete_nettoie_membres(self, mock_conn):
        """Suppression d'une équipe doit aussi supprimer mopTeamMember."""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        el = elem('tm', {'id': '100', 'delete': 'true'})
        process_team(1, el)

        deleted = [c[0][0] for c in cur.execute.call_args_list]
        assert any('mopTeam' in s and 'Member' not in s for s in deleted)
        assert any('mopTeamMember' in s for s in deleted)


# ─── Tests _update_link_table ─────────────────────────────────────────────────

class TestUpdateLinkTable:

    @patch('results.mop_receiver.connection')
    def test_radio_simple(self, mock_conn):
        """'70' → leg=1 ord=0 value=70"""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        _update_link_table('mopClassControl', 1, 1, 'ctrl', '70')
        rows = cur.executemany.call_args[0][1]
        assert (1, 1, 1, 0, 70) in rows
        assert len(rows) == 1

    @patch('results.mop_receiver.connection')
    def test_deux_fractions(self, mock_conn):
        """'31,32;33' → 3 lignes sur 2 legs."""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        _update_link_table('mopClassControl', 1, 10, 'ctrl', '31,32;33')
        rows = cur.executemany.call_args[0][1]
        assert (1, 10, 1, 0, 31) in rows
        assert (1, 10, 1, 1, 32) in rows
        assert (1, 10, 2, 0, 33) in rows

    @patch('results.mop_receiver.connection')
    def test_encoded_vide(self, mock_conn):
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        _update_link_table('mopClassControl', 1, 10, 'ctrl', '')
        cur.executemany.assert_not_called()

    @patch('results.mop_receiver.connection')
    def test_supprime_avant_inserer(self, mock_conn):
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        _update_link_table('mopClassControl', 1, 10, 'ctrl', '70')
        assert 'DELETE' in cur.execute.call_args_list[0][0][0]


# ─── Tests _parse_id ──────────────────────────────────────────────────────────

class TestParseId:
    """Vérifie l'extraction du numéro entier en tête d'identifiant MeOS."""

    def _call(self, s):
        return _parse_id(s)

    def test_numero_simple(self):
        assert self._call('70') == 70

    def test_suffixe_tiret_un(self):
        """Cas principal signalé : "31-1" → 31."""
        assert self._call('31-1') == 31

    def test_suffixe_tiret_autre(self):
        assert self._call('32-99') == 32

    def test_suffixe_non_numerique(self):
        assert self._call('100abc') == 100

    def test_espaces_ignores(self):
        assert self._call('  42 ') == 42

    def test_espaces_avec_suffixe(self):
        assert self._call(' 31-1 ') == 31

    def test_chaine_vide_leve_valuerror(self):
        with pytest.raises(ValueError):
            self._call('')

    def test_chaine_sans_chiffre_leve_valuerror(self):
        with pytest.raises(ValueError):
            self._call('-1')

    def test_grand_numero(self):
        assert self._call('12345-1') == 12345


# ─── Tests _update_link_table — suffixes parasites ────────────────────────────

class TestUpdateLinkTableParseId:
    """Vérifie que _update_link_table tolère les identifiants avec suffixes."""

    @patch('results.mop_receiver.connection')
    def test_suffixe_tiret_dans_radio_simple(self, mock_conn):
        """'31-1' → valeur stockée = 31."""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        _update_link_table('mopClassControl', 1, 10, 'ctrl', '31-1')
        rows = cur.executemany.call_args[0][1]
        assert (1, 10, 1, 0, 31) in rows

    @patch('results.mop_receiver.connection')
    def test_suffixe_tiret_dans_multi_controles(self, mock_conn):
        """'31-1,32-1;33-1' → valeurs 31, 32, 33."""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        _update_link_table('mopClassControl', 1, 10, 'ctrl', '31-1,32-1;33-1')
        rows = cur.executemany.call_args[0][1]
        assert (1, 10, 1, 0, 31) in rows
        assert (1, 10, 1, 1, 32) in rows
        assert (1, 10, 2, 0, 33) in rows

    @patch('results.mop_receiver.connection')
    def test_mix_suffixe_et_normal(self, mock_conn):
        """'31-1,32' → valeurs 31 et 32 (mix correct/suffixé)."""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        _update_link_table('mopClassControl', 1, 10, 'ctrl', '31-1,32')
        rows = cur.executemany.call_args[0][1]
        assert (1, 10, 1, 0, 31) in rows
        assert (1, 10, 1, 1, 32) in rows


# ─── Tests process_competitor — suffixes dans les postes radio ────────────────

class TestProcessCompetitorParseId:
    """Vérifie que process_competitor tolère les numéros de poste avec suffixes."""

    @patch('results.mop_receiver.connection')
    @patch('results.mop_receiver._upsert')
    def test_radio_avec_suffixe_tiret(self, mock_upsert, mock_conn):
        """<radio>31-1,1200</radio> → ctrl=31, rt=1200."""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        el = elem('cmp', {'id': '1'}, children=[
            ('base', {'org': '1', 'cls': '1', 'stat': '1',
                      'st': '0', 'rt': '5000'}, 'Alice'),
            ('radio', {}, '31-1,1200'),
        ])
        process_competitor(1, el)

        rows = cur.executemany.call_args[0][1]
        assert (1, 1, 31, 1200) in rows

    @patch('results.mop_receiver.connection')
    @patch('results.mop_receiver._upsert')
    def test_radio_multiple_avec_suffixes(self, mock_upsert, mock_conn):
        """<radio>31-1,1200;32-1,2500</radio> → deux lignes avec ctrl 31 et 32."""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        el = elem('cmp', {'id': '1'}, children=[
            ('base', {'org': '1', 'cls': '1', 'stat': '1',
                      'st': '0', 'rt': '5000'}, 'Bob'),
            ('radio', {}, '31-1,1200;32-1,2500'),
        ])
        process_competitor(1, el)

        rows = cur.executemany.call_args[0][1]
        assert (1, 1, 31, 1200) in rows
        assert (1, 1, 32, 2500) in rows

    @patch('results.mop_receiver.connection')
    @patch('results.mop_receiver._upsert')
    def test_radio_sans_suffixe_inchange(self, mock_upsert, mock_conn):
        """Les postes sans suffixe continuent de fonctionner normalement."""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        el = elem('cmp', {'id': '1'}, children=[
            ('base', {'org': '1', 'cls': '1', 'stat': '1',
                      'st': '0', 'rt': '3000'}, 'Carla'),
            ('radio', {}, '70,27160'),
        ])
        process_competitor(1, el)

        rows = cur.executemany.call_args[0][1]
        assert (1, 1, 70, 27160) in rows


# ─── Couverture complémentaire (clear_competition, _upsert, frozen, …) ──────

class TestClearCompetition:

    @patch('results.mop_receiver.connection')
    def test_supprime_toutes_les_tables(self, mock_conn):
        from results.mop_receiver import clear_competition, MEOS_TABLES
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

        clear_competition(7)

        assert cur.execute.call_count >= len(MEOS_TABLES)
        for c in cur.execute.call_args_list:
            assert 'DELETE' in c.args[0]
            assert c.args[1] == [7]


class TestUpsert:

    def _run(self, exists):
        from results.mop_receiver import _upsert
        cur = MagicMock()
        cur.fetchone.return_value = exists
        with patch('results.mop_receiver.connection') as mock_conn:
            mock_conn.cursor.return_value.__enter__ = lambda s: cur
            mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)
            _upsert('mopCompetition', 1, 99, {'name': 'Test', 'date': '2026-01-01'})
            return cur.execute.call_args_list

    def test_update_si_existe(self):
        calls = self._run((1,))
        assert 'UPDATE' in calls[1][0][0]
        assert calls[1][0][1] == ['Test', '2026-01-01', 1, 99]

    def test_insert_si_absent(self):
        calls = self._run(None)
        assert 'INSERT' in calls[1][0][0]
        assert calls[1][0][1] == [1, 99, 'Test', '2026-01-01']


class TestProcessCompetition:

    @patch('results.mop_receiver._upsert')
    def test_champs_complets(self, mock_upsert):
        from results.mop_receiver import process_competition
        el = elem('competition',
                  {'date': '2026-01-01', 'organizer': 'OK Linné',
                   'homepage': 'http://x', 'zerotime': '09:00:00'},
                  text='Course Test')
        process_competition(1, el)
        fields = mock_upsert.call_args[0][3]
        assert fields['name'] == 'Course Test'
        assert fields['date'] == '2026-01-01'
        assert fields['organizer'] == 'OK Linné'
        assert fields['homepage'] == 'http://x'


class TestProcessControl:

    @patch('results.mop_receiver._upsert')
    def test_nom_poste(self, mock_upsert):
        from results.mop_receiver import process_control
        el = elem('ctrl', {'id': '70'}, text='Radio')
        process_control(1, el)
        fields = mock_upsert.call_args[0][3]
        assert fields['name'] == 'Radio'


class TestProcessOrganization:

    @patch('results.mop_receiver.connection')
    def test_delete(self, mock_conn):
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)
        from results.mop_receiver import process_organization
        el = elem('org', {'id': '255', 'delete': 'true'})
        process_organization(1, el)
        assert 'DELETE' in cur.execute.call_args[0][0]

    @patch('results.mop_receiver._upsert')
    def test_insertion(self, mock_upsert):
        from results.mop_receiver import process_organization
        el = elem('org', {'id': '255'}, text='Länna IF')
        process_organization(1, el)
        fields = mock_upsert.call_args[0][3]
        assert fields['name'] == 'Länna IF'


class TestProcessCompetitorComplement:

    @patch('results.mop_receiver._upsert')
    @patch('results.mop_receiver.connection')
    def test_base_manquant_ignore(self, mock_conn, mock_upsert):
        """<cmp> sans <base> → warning et retour sans upsert."""
        from results.mop_receiver import process_competitor
        el = elem('cmp', {'id': '5'})
        process_competitor(1, el)
        mock_upsert.assert_not_called()

    @patch('results.mop_receiver._upsert')
    @patch('results.mop_receiver.connection')
    def test_input_renseigne_it_et_tstat(self, mock_conn, mock_upsert):
        """<input it/tstat> alimente it et tstat dans le base."""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)
        from results.mop_receiver import process_competitor
        el = elem('cmp', {'id': '9'}, children=[
            ('base', {'org': '1', 'cls': '1', 'stat': '1',
                      'st': '0', 'rt': '3000'}, 'A'),
            ('input', {'it': '123', 'tstat': '2'}, None),
        ])
        process_competitor(1, el)
        fields = mock_upsert.call_args[0][3]
        assert fields['it'] == 123
        assert fields['tstat'] == 2

    @patch('results.mop_receiver._upsert')
    @patch('results.mop_receiver.connection')
    def test_base_prel_true_stocke_prel(self, mock_conn, mock_upsert):
        """prel="true" sur <base> (arrivée radio, carte non lue) → prel=1."""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)
        from results.mop_receiver import process_competitor
        el = elem('cmp', {'id': '9'}, children=[
            ('base', {'org': '1', 'cls': '1', 'stat': '1',
                      'st': '0', 'rt': '3000', 'prel': 'true'}, 'A'),
        ])
        process_competitor(1, el)
        fields = mock_upsert.call_args[0][3]
        assert fields['prel'] == 1

    @patch('results.mop_receiver._upsert')
    @patch('results.mop_receiver.connection')
    def test_base_sans_prel_efface_prel(self, mock_conn, mock_upsert):
        """Attribut prel absent (résultat officiel, carte lue) → prel=0."""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)
        from results.mop_receiver import process_competitor
        el = elem('cmp', {'id': '9'}, children=[
            ('base', {'org': '1', 'cls': '1', 'stat': '1',
                      'st': '0', 'rt': '3000'}, 'A'),
        ])
        process_competitor(1, el)
        fields = mock_upsert.call_args[0][3]
        assert fields['prel'] == 0

    @patch('results.mop_receiver._upsert')
    @patch('results.mop_receiver.connection')
    def test_radio_entrees_vides_ignorees(self, mock_conn, mock_upsert):
        """'70,1;;80,2;' → les segments vides sont ignorés."""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)
        from results.mop_receiver import process_competitor
        el = elem('cmp', {'id': '9'}, children=[
            ('base', {'org': '1', 'cls': '1', 'stat': '1',
                      'st': '0', 'rt': '3000'}, 'A'),
            ('radio', {}, '70,1;;80,2;'),
        ])
        process_competitor(1, el)
        rows = cur.executemany.call_args[0][1]
        assert (1, 9, 70, 1) in rows
        assert (1, 9, 80, 2) in rows
        assert len(rows) == 2


class TestProcessTeamComplement:

    @patch('results.mop_receiver._upsert')
    @patch('results.mop_receiver.connection')
    def test_base_manquant_ignore(self, mock_conn, mock_upsert):
        """<tm> sans <base> → warning sans insert."""
        from results.mop_receiver import process_team
        el = elem('tm', {'id': '100'})
        process_team(1, el)
        mock_upsert.assert_not_called()

    @patch('results.mop_receiver._upsert')
    @patch('results.mop_receiver.connection')
    def test_base_prel_true_stocke_prel(self, mock_conn, mock_upsert):
        """prel="true" sur <tm><base> → prel=1."""
        cur = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: cur
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)
        from results.mop_receiver import process_team
        el = elem('tm', {'id': '100'}, children=[
            ('base', {'org': '1', 'cls': '1', 'stat': '1',
                      'st': '0', 'rt': '3000', 'prel': 'true'}, 'Équipe A'),
        ])
        process_team(1, el)
        fields = mock_upsert.call_args[0][3]
        assert fields['prel'] == 1


class TestProcessMopXmlFrozen:

    @patch('results.mop_receiver.transaction')
    def test_competition_gelée_retourne_frozen(self, mock_tx):
        cur = MagicMock()
        cur.fetchone.return_value = (1,)
        with patch('results.mop_receiver.connection') as mock_conn:
            mock_conn.cursor.return_value.__enter__ = lambda s: cur
            mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)
            from results.mop_receiver import process_mop_xml
            assert process_mop_xml(1, b'<MOPDiff></MOPDiff>') == 'FROZEN'
        mock_tx.atomic.assert_not_called()

    def test_erreur_db_ignoree_puis_traitement(self):
        """Une exception sur la vérification frozen ne bloque pas le traitement."""
        with patch('results.mop_receiver.connection') as mock_conn, \
             patch('results.mop_receiver.transaction') as mock_tx, \
             patch('results.mop_receiver.clear_competition') as mock_clear:
            mock_conn.cursor.side_effect = RuntimeError('db down')
            mock_tx.atomic.return_value.__enter__ = lambda s: s
            mock_tx.atomic.return_value.__exit__  = MagicMock(return_value=False)
            from results.mop_receiver import process_mop_xml
            status = process_mop_xml(1, b'<MOPComplete></MOPComplete>')
            assert status == 'OK'
            mock_clear.assert_called_once_with(1)

    @patch('results.mop_receiver.transaction')
    def test_exception_processeur_ne_bloque_pas_les_autres(self, mock_tx):
        """Une exception sur <cmp> n'empêche pas le traitement des autres éléments."""
        mock_tx.atomic.return_value.__enter__ = lambda s: s
        mock_tx.atomic.return_value.__exit__  = MagicMock(return_value=False)
        xml = '<MOPDiff><cmp id="1"><base name="x"/></cmp><ctrl id="1"/></MOPDiff>'.encode()
        boom = MagicMock(side_effect=RuntimeError('sur <cmp>'))
        ok = MagicMock(return_value=None)
        with patch.dict('results.mop_receiver.PROCESSORS', {'cmp': boom, 'ctrl': ok}):
            from results.mop_receiver import process_mop_xml
            status = process_mop_xml(1, xml)
        assert status == 'OK'
        ok.assert_called_once()

    @patch('results.mop_receiver.transaction')
    def test_tag_inconnu_ignore_sans_exception(self, mock_tx):
        """Un tag sans processeur enregistré est ignoré (logger.debug)."""
        mock_tx.atomic.return_value.__enter__ = lambda s: s
        mock_tx.atomic.return_value.__exit__  = MagicMock(return_value=False)
        xml = '<MOPDiff><tagInconnu id="42"/></MOPDiff>'.encode()
        from results.mop_receiver import process_mop_xml
        assert process_mop_xml(1, xml) == 'OK'
