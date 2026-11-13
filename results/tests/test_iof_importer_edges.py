"""
Tests de bord du parseur / convertisseur IOF (branches défensives).

Ces tests complètent ``test_iof_importer.py`` : ils ciblent les valeurs
invalides, les avertissements de troncature, les cas limites des registres
d'identifiants et la résolution des métadonnées. Aucune base de données.
"""

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pytest

from results.iof_importer import (
    IofClassResult, IofEvent, IofImportError, IofOrganisation, IofPerson,
    IofRace, IofResult, IofResultList, IofSplit, IofTeam, IofTeamMember,
    MAX_TINYINT, SYNTHETIC_ID_START,
    _Allocator, _CanonicalCourse, _ControlRegistry, _Truncator,
    _child, _children, _clean_text, _clock_tenths, _dedupe_sequence,
    _invalidate_caches, _map_splits, _matches_race, _member_quality,
    _namespace, _numeric_id,
    _parse_date, _parse_datetime, _parse_decimal, _parse_int,
    _read_existing_metadata, _resolve_competition_metadata,
    _team_member_entries, build_mop_model, build_mop_xml,
    parse_iof_result_list,
)
from results.models import STAT_DNF, STAT_OK, STAT_UNKNOWN
from results.mop_receiver import MOP_NS
from results.tests.test_iof_importer import (
    _class_result, _event, _individual_xml, _multi_race_xml, _person_result,
    _relay_xml, _result, _split, _xml,
)


def _metadata():
    return {
        'name': 'Course site',
        'date': '2026-05-17',
        'organizer': 'Club site',
        'homepage': 'https://site.example',
    }


def _iof_result(*, time_tenths=18000, stat=STAT_OK, splits=None,
                bib='7', start=None, finish=None, status='OK',
                leg=None, leg_order=None, card=''):
    return IofResult(
        race_number=None, bib=bib, start=start, finish=finish,
        time_tenths=time_tenths, status=status, splits=splits or [],
        card=card, leg=leg, leg_order=leg_order,
        stat=stat, prel=0, tstat=stat,
    )


def _iof_person(pid='101', family='Doe', given='Jane', organisation=None,
                results=None, nationality=''):
    return IofPerson(
        iof_id=pid, family=family, given=given,
        nationality=nationality, organisation=organisation,
        results=results if results is not None else [_iof_result()],
    )


def _parsed(classes):
    return IofResultList(
        event=IofEvent(name='E', date=date(2026, 5, 17),
                       organiser='', homepage=''),
        classes=classes, status='Complete', race_number=None,
    )


def _relay_member(person_id, *, leg=1, time='100', status='OK',
                  with_person=True, with_result=True, organisation=''):
    parts = ['<TeamMemberResult>']
    if with_person:
        parts.append(
            f'<Person><Id>{person_id}</Id><Name>'
            f'<Family>F{person_id}</Family><Given>G</Given></Name></Person>'
        )
    parts.append(organisation)
    if with_result:
        leg_xml = f'<Leg>{leg}</Leg>' if leg is not None else ''
        time_xml = f'<Time>{time}</Time>' if time is not None else ''
        parts.append(
            f'<Result>{leg_xml}'
            '<StartTime>2026-05-17T10:00:00</StartTime>'
            f'<Status>{status}</Status>{time_xml}</Result>'
        )
    parts.append('</TeamMemberResult>')
    return ''.join(parts)


def _relay_team(members, *, name='Équipe Test', organisation=''):
    return (
        f'<TeamResult><Name>{name}</Name>{organisation}'
        f'{members}</TeamResult>'
    )


def _relay_doc(team_xml):
    return _xml(_event() + _class_result(name='Relais', content=team_xml))


# ─── Helpers XML et conversions ──────────────────────────────────────────────

class TestHelperEdges:

    def test_helpers_none_et_namespace_absent(self):
        assert _namespace('ResultList') == ''
        assert _children(None, 'Event') == []
        assert _child(None, 'Event') is None

    def test_parse_int_invalide(self):
        assert _parse_int('abc') is None
        assert _parse_int(None) is None

    def test_numeric_id_hors_limites(self):
        assert _numeric_id('0') is None
        assert _numeric_id('999999999999999999') is None
        assert _numeric_id('31') == 31

    def test_matches_race_sans_selection(self):
        elem = ET.Element('Result', {'raceNumber': '2'})
        assert _matches_race(elem, None, 1) is False
        assert _matches_race(ET.Element('Result'), 2, 2) is False
        assert _matches_race(ET.Element('Result'), None, 1) is True

    def test_parse_decimal_invalide_et_non_fini(self):
        assert _parse_decimal('abc') is None
        assert _parse_decimal('NaN') is None
        assert _parse_decimal('Infinity') is None

    def test_clock_tenths_sans_valeur(self):
        assert _clock_tenths(None) == 0

    def test_parse_date_vide_ou_invalide(self):
        assert _parse_date('') is None
        assert _parse_date('pas-une-date') is None

    def test_parse_datetime_invalide(self):
        assert _parse_datetime('pas-une-date') is None

    def test_clean_text_tronque_et_avertit(self):
        warnings = []
        text = _clean_text('x' * 80, 64, 'nom de la course', warnings)
        assert text == 'x' * 64
        assert any('tronqué' in warning for warning in warnings)

    def test_truncator_agrege_les_alertes(self):
        warnings = []
        truncator = _Truncator(warnings)
        assert truncator('y' * 70, 64, 'classe') == 'y' * 64
        assert not warnings
        truncator.add_warning()
        assert any('tronquées' in warning for warning in warnings)

    def test_allocator_saute_les_identifiants_utilises(self):
        allocator = _Allocator()
        allocator.used.add(SYNTHETIC_ID_START)
        assert allocator.allocate() == SYNTHETIC_ID_START + 1

    def test_control_registry_saute_les_identifiants_utilises(self):
        registry = _ControlRegistry(_Truncator([]))
        registry.used.add(SYNTHETIC_ID_START)
        assert registry._allocate() == SYNTHETIC_ID_START + 1

    def test_dedupe_sequence(self):
        assert _dedupe_sequence(['31', '31', '32', '31']) == ['31', '32']

    def test_map_splits_cas_limites(self):
        canonical = _CanonicalCourse(
            codes=['31', '32'], ids=[31, 32], uniform=True,
            occurrence_ids={('31', 0): 31, ('32', 0): 32},
            code_ids={'31': 31, '32': 32},
        )
        splits = [
            IofSplit(code='31', time_tenths=100, status='Additional'),
            IofSplit(code='', time_tenths=200, status='OK'),
            IofSplit(code='31', time_tenths=500, status='OK'),
            IofSplit(code='31', time_tenths=600, status='OK'),
            IofSplit(code='99', time_tenths=700, status='OK'),
            IofSplit(code='32', time_tenths=None, status='Missing'),
        ]
        warnings = []
        radio = _map_splits(splits, canonical, warnings, 'Doe Jane')
        assert radio == [(31, 500)]
        assert any('répété' in warning for warning in warnings)


# ─── Parseur : cas limites ───────────────────────────────────────────────────

class TestParseEdges:

    def test_entree_str_acceptee(self):
        parsed = parse_iof_result_list(_individual_xml().decode())
        assert len(parsed.classes) == 1

    def test_fichier_trop_gros_refuse(self, monkeypatch):
        monkeypatch.setattr('results.iof_importer.MAX_UPLOAD_BYTES', 10)
        with pytest.raises(IofImportError) as excinfo:
            parse_iof_result_list(_individual_xml())
        assert 'taille maximale' in str(excinfo.value)

    def test_version_iof_inconnue_refusee(self):
        with pytest.raises(IofImportError) as excinfo:
            parse_iof_result_list(_individual_xml(version='2.0'))
        assert '2.0' in str(excinfo.value)

    def test_namespace_version_et_statut_absents_avertissent(self):
        xml = (
            '<ResultList>'
            '<Event><Name>E</Name></Event>'
            '<ClassResult><Class><Id>10</Id><Name>H21</Name></Class>'
            '<PersonResult><Person><Id>1</Id><Name><Family>A</Family>'
            '</Name></Person>'
            '<Result><Time>100</Time><Status>OK</Status></Result>'
            '</PersonResult></ClassResult>'
            '</ResultList>'
        )
        parsed = parse_iof_result_list(xml)
        assert any('Namespace' in warning for warning in parsed.warnings)
        assert any('Version' in warning for warning in parsed.warnings)
        assert any('Statut de fichier' in warning for warning in parsed.warnings)

    def test_statut_de_fichier_inconnu_avertit(self):
        parsed = parse_iof_result_list(_individual_xml(status='Bogus'))
        assert any('inconnu' in warning for warning in parsed.warnings)

    def test_statut_absent_avertit(self):
        body = (
            _event()
            + _class_result(content=_person_result(
                result=_result(status='', time=None, finish=None),
            ))
        )
        parsed = parse_iof_result_list(_xml(body))
        result = parsed.classes[0].persons[0].results[0]
        assert (result.stat, result.prel, result.tstat) == (STAT_UNKNOWN, 0, 0)
        assert any('Statut IOF absent' in warning for warning in parsed.warnings)

    def test_race_number_invalide_ignore(self):
        body = (
            _event()
            + _class_result(content=(
                _person_result(
                    person_id='101',
                    result=_result(race_number='abc', time='100'),
                )
                + _person_result(
                    person_id='102', family='Martin',
                    result=_result(time='200'),
                )
            ))
        )
        parsed = parse_iof_result_list(_xml(body))
        assert len(parsed.classes[0].persons) == 1
        assert any('raceNumber invalide' in warning for warning in parsed.warnings)

    def test_resultat_sans_numero_dans_fichier_multi_course(self):
        body = (
            _event(
                races=(
                    '<Race><RaceNumber>1</RaceNumber></Race>'
                    '<Race><RaceNumber>2</RaceNumber></Race>'
                ),
            )
            + _class_result(content=(
                _person_result(
                    person_id='101',
                    result=_result(race_number=1, time='100'),
                )
                + _person_result(
                    person_id='102', family='Martin',
                    result=_result(time='200'),
                )
            ))
        )
        parsed = parse_iof_result_list(_xml(body), race_number=1)
        assert len(parsed.classes[0].persons) == 1
        assert any('sans numéro de course' in warning for warning in parsed.warnings)

    def test_classresult_sans_class_ignore(self):
        body = (
            _event()
            + '<ClassResult><PersonResult/></ClassResult>'
            + _class_result(content=_person_result(result=_result(time='100')))
        )
        parsed = parse_iof_result_list(_xml(body))
        assert len(parsed.classes) == 1
        assert any('sans <Class>' in warning for warning in parsed.warnings)

    def test_aucune_classe_leve_une_erreur(self):
        with pytest.raises(IofImportError) as excinfo:
            parse_iof_result_list(_xml(_event()))
        assert 'aucune classe' in str(excinfo.value)

    def test_aucun_resultat_exploitable_leve_une_erreur(self):
        body = (
            _event()
            + _class_result(content=(
                '<PersonResult><Person><Id>1</Id><Name><Family>A</Family>'
                '</Name></Person></PersonResult>'
            ))
        )
        with pytest.raises(IofImportError) as excinfo:
            parse_iof_result_list(_xml(body))
        assert 'aucun résultat exploitable' in str(excinfo.value)

    def test_classe_sans_nom_conservee(self):
        body = (
            _event()
            + '<ClassResult><Class><Id></Id></Class>'
            + _person_result(result=_result(time='100'))
            + '</ClassResult>'
        )
        parsed = parse_iof_result_list(_xml(body))
        assert parsed.classes[0].name == ''
        assert any('Classe sans nom' in warning for warning in parsed.warnings)

    def test_person_result_sans_person_ignore(self):
        body = (
            _event()
            + _class_result(content=(
                '<PersonResult><Result><Time>100</Time>'
                '<Status>OK</Status></Result></PersonResult>'
                + _person_result(person_id='102', result=_result(time='200'))
            ))
        )
        parsed = parse_iof_result_list(_xml(body))
        assert len(parsed.classes[0].persons) == 1
        assert any('sans <Person>' in warning for warning in parsed.warnings)

    def test_equipe_sans_membre_ignoree(self):
        team = _relay_team(
            _relay_member('201'),
            organisation=(
                '<Organisation><Id>30</Id><Name>CO Test</Name></Organisation>'
            ),
        ) + '<TeamResult><Name>Vide</Name></TeamResult>'
        parsed = parse_iof_result_list(_relay_doc(team))
        assert len(parsed.classes[0].teams) == 1
        assert any('sans membre' in warning for warning in parsed.warnings)

    def test_plusieurs_resultats_meme_course(self):
        body = (
            _event()
            + _class_result(content=_person_result(
                result=_result(time='100') + _result(time='200'),
            ))
        )
        parsed = parse_iof_result_list(_xml(body))
        result = parsed.classes[0].persons[0].results[0]
        assert result.time_tenths == 1000
        assert any('Plusieurs résultats' in warning for warning in parsed.warnings)

    def test_evenement_absent_avertit(self):
        body = _class_result(content=_person_result(result=_result(time='100')))
        parsed = parse_iof_result_list(_xml(body))
        assert parsed.event.name == ''
        assert any('<Event> absent' in warning for warning in parsed.warnings)

    def test_homepage_premiere_url_sans_type(self):
        event = (
            '<Event><Name>E</Name>'
            '<URL>https://premier.example</URL></Event>'
        )
        body = event + _class_result(
            content=_person_result(result=_result(time='100')),
        )
        parsed = parse_iof_result_list(_xml(body))
        assert parsed.event.homepage == 'https://premier.example'

    def test_race_sans_numero_et_numero_duplique(self):
        event = (
            '<Event><Name>E</Name>'
            '<Race><Name>Sans numéro</Name></Race>'
            '<Race><RaceNumber>2</RaceNumber></Race>'
            '<Race><RaceNumber>1</RaceNumber></Race>'
            '</Event>'
        )
        body = event + _class_result(content=_person_result(
            result=_result(race_number=2, time='100'),
        ))
        parsed = parse_iof_result_list(_xml(body), race_number=2)
        assert [race.number for race in parsed.event.races] == [1, 2]
        assert any('RaceNumber absent' in warning for warning in parsed.warnings)
        assert any('dupliqué' in warning for warning in parsed.warnings)

    def test_organisation_sans_identifiant_et_nationalite_sans_code(self):
        body = (
            _event()
            + _class_result(content=(
                '<PersonResult>'
                '<Person><Id>101</Id><Name><Family>A</Family></Name>'
                '<Nationality>France</Nationality></Person>'
                '<Organisation><Name>Club sans id</Name>'
                '<Country>France</Country></Organisation>'
                f'{_result(time="100")}</PersonResult>'
                '<PersonResult>'
                '<Person><Id>102</Id><Name><Family>B</Family></Name></Person>'
                '<Organisation><Country code="FRA">France</Country></Organisation>'
                f'{_result(time="200")}</PersonResult>'
            ))
        )
        parsed = parse_iof_result_list(_xml(body))
        first, second = parsed.classes[0].persons
        assert first.nationality == 'FRANCE'
        assert first.organisation.name == 'Club sans id'
        assert first.organisation.country_code == 'FRANCE'
        assert second.organisation is None

        model = build_mop_model(parsed, _metadata(), parsed.warnings)
        # Personne sans organisation → org 0, une seule organisation enregistrée.
        assert model.competitors[102].org == 0
        assert len(model.orgs) == 1

    def test_splits_invalides_avertissent(self):
        splits = (
            _split('', '300')
            + _split('31', '300', status='Weird')
            + _split('32', '-5')
        )
        body = (
            _event()
            + _class_result(content=_person_result(
                result=_result(splits=splits),
            ))
        )
        parsed = parse_iof_result_list(_xml(body))
        result = parsed.classes[0].persons[0].results[0]
        assert [split.code for split in result.splits] == ['31', '32']
        assert result.splits[0].status == 'OK'
        assert result.splits[1].time_tenths is None
        assert any('sans ControlCode' in warning for warning in parsed.warnings)
        assert any('Statut de split' in warning for warning in parsed.warnings)
        assert any('Temps négatif' in warning for warning in parsed.warnings)

    def test_arrivee_avant_depart_ignoree(self):
        body = (
            _event()
            + _class_result(content=_person_result(
                result=_result(
                    time=None,
                    start='2026-05-17T10:30:00',
                    finish='2026-05-17T10:00:00',
                ),
            ))
        )
        parsed = parse_iof_result_list(_xml(body))
        result = parsed.classes[0].persons[0].results[0]
        assert result.time_tenths is None
        assert any('antérieure au départ' in warning for warning in parsed.warnings)

    def test_depart_et_arrivee_incomparables(self):
        body = (
            _event()
            + _class_result(content=_person_result(
                result=_result(
                    time=None,
                    start='2026-05-17T10:00:00Z',
                    finish='2026-05-17T10:30:00',
                ),
            ))
        )
        parsed = parse_iof_result_list(_xml(body))
        result = parsed.classes[0].persons[0].results[0]
        assert result.time_tenths is None

    def test_classes_sans_id_fusionnees_par_nom(self):
        body = (
            _event()
            + _class_result(
                class_id='', name='H21',
                content=_person_result(person_id='101', result=_result(time='100')),
            )
            + _class_result(
                class_id='', name='H21',
                content=_person_result(person_id='102', family='B',
                                       result=_result(time='200')),
            )
        )
        parsed = parse_iof_result_list(_xml(body))
        assert len(parsed.classes) == 1
        assert len(parsed.classes[0].persons) == 2

    def test_classes_meme_id_noms_differents_avertit(self):
        body = (
            _event()
            + _class_result(
                class_id='10', name='H21',
                content=_person_result(person_id='101', result=_result(time='100')),
            )
            + _class_result(
                class_id='10', name='H22',
                content=_person_result(person_id='102', family='B',
                                       result=_result(time='200')),
            )
        )
        parsed = parse_iof_result_list(_xml(body))
        assert len(parsed.classes) == 1
        assert any('noms différents' in warning for warning in parsed.warnings)

    def test_classes_sans_id_ni_nom_non_fusionnees(self):
        body = (
            _event()
            + _class_result(
                class_id='', name='',
                content=_person_result(person_id='101', result=_result(time='100')),
            )
            + _class_result(
                class_id='', name='',
                content=_person_result(person_id='102', family='B',
                                       result=_result(time='200')),
            )
        )
        parsed = parse_iof_result_list(_xml(body))
        assert len(parsed.classes) == 2
        model = build_mop_model(parsed, _metadata(), parsed.warnings)
        assert len(model.classes) == 2


# ─── Registres et construction du modèle ─────────────────────────────────────

class TestModelEdges:

    def test_class_registry_fusionne_id_duplique(self):
        parsed = _parsed([
            IofClassResult('10', 'H21', [_iof_person('101')]),
            IofClassResult('10', 'H21', [_iof_person('102', family='Martin')]),
        ])
        model = build_mop_model(parsed, _metadata(), parsed.warnings)
        assert len(model.classes) == 1
        assert len(model.competitors) == 2
        assert any('identifiant dupliqué' in w for w in parsed.warnings)

    def test_class_registry_fusionne_sans_id_par_nom(self):
        parsed = _parsed([
            IofClassResult(None, 'H21', [_iof_person('101')]),
            IofClassResult(None, 'H21', [_iof_person('102', family='Martin')]),
        ])
        model = build_mop_model(parsed, _metadata(), parsed.warnings)
        assert len(model.classes) == 1
        assert any('sans identifiant' in w for w in parsed.warnings)

    def test_org_registry_fusionne_sans_id_par_nom(self):
        parsed = _parsed([
            IofClassResult('10', 'H21', [
                _iof_person('101', organisation=IofOrganisation(None, 'Même Club', '')),
                _iof_person('102', family='Martin',
                            organisation=IofOrganisation(None, 'Même Club', '')),
            ]),
        ])
        model = build_mop_model(parsed, _metadata(), parsed.warnings)
        assert len(model.orgs) == 1
        assert model.competitors[101].org == model.competitors[102].org

    def test_personne_sans_nom_et_statut_ok_sans_temps(self):
        parsed = _parsed([
            IofClassResult('10', 'H21', [
                _iof_person('101', family='', given='',
                            results=[_iof_result(time_tenths=None)]),
            ]),
        ])
        model = build_mop_model(parsed, _metadata(), parsed.warnings)
        assert model.competitors[101].name == 'Unknown 101'
        assert any('sans nom' in w for w in parsed.warnings)
        assert any('sans temps de course' in w for w in parsed.warnings)

    def test_troncature_des_noms_dans_le_modele(self):
        body = (
            _event()
            + _class_result(
                class_id='10', name='C' * 80,
                content=_person_result(
                    person_id='101', family='F' * 80, given='',
                    result=_result(time='100'),
                ),
            )
        )
        parsed = parse_iof_result_list(_xml(body))
        model = build_mop_model(parsed, _metadata(), parsed.warnings)
        assert len(model.classes[10].name) == 64
        assert len(model.competitors[101].name) == 64
        assert any('tronquées' in w for w in parsed.warnings)

    def test_xml_prel_coureur_et_equipe(self):
        xml = _relay_xml().replace(b'<Status>OK</Status>', b'<Status>Finished</Status>')
        parsed = parse_iof_result_list(xml)
        model = build_mop_model(parsed, _metadata(), parsed.warnings)
        root = ET.fromstring(build_mop_xml(model))
        for cmp_elem in root.findall(f'{{{MOP_NS}}}cmp'):
            assert cmp_elem.find(f'{{{MOP_NS}}}base').get('prel') == 'true'
        tm = root.find(f'{{{MOP_NS}}}tm')
        assert tm.find(f'{{{MOP_NS}}}base').get('prel') == 'true'


# ─── Relais : cas limites ────────────────────────────────────────────────────

class TestRelayEdges:

    def test_membre_sans_resultat_et_fraction_hors_limites(self):
        warnings = []
        team = IofTeam(
            entry_id=None, name='T', organisations=[], bib='',
            members=[
                IofTeamMember(person=_iof_person('201'), organisation=None,
                              results=[]),
                IofTeamMember(
                    person=_iof_person('202'), organisation=None,
                    results=[_iof_result(leg=MAX_TINYINT + 50)],
                ),
            ],
        )
        entries = _team_member_entries(team, warnings)
        assert len(entries) == 1
        assert entries[0].leg == MAX_TINYINT
        assert any('hors limites' in warning for warning in warnings)

    def test_member_quality(self):
        def entry(stat, rt, leg_order=1, index=1):
            return SimpleNamespace(
                result=SimpleNamespace(stat=stat, time_tenths=rt),
                leg_order=leg_order,
                index=index,
            )

        assert _member_quality(entry(STAT_OK, 100)) == (0, 100, 1, 1)
        assert _member_quality(entry(STAT_OK, 0)) == (1, 0, 1, 1)
        assert _member_quality(entry(STAT_DNF, 100)) == (2, 0, 1, 1)

    def test_plusieurs_membres_meme_fraction(self):
        team = _relay_team(
            _relay_member('201', leg=1, time='1500')
            + _relay_member('202', leg=1, time='1400'),
            organisation=(
                '<Organisation><Id>30</Id><Name>CO Test</Name></Organisation>'
            ),
        )
        parsed = parse_iof_result_list(_relay_doc(team))
        model = build_mop_model(parsed, _metadata(), parsed.warnings)
        team_obj = next(iter(model.teams.values()))
        assert team_obj.rt == 14000
        assert len(team_obj.members) == 2
        assert any('plusieurs membres' in w for w in parsed.warnings)

    def test_membre_non_ok_stat_equipe(self):
        team = _relay_team(
            _relay_member('201', leg=1, status='DidNotFinish', time='1500'),
            organisation=(
                '<Organisation><Id>30</Id><Name>CO Test</Name></Organisation>'
            ),
        )
        parsed = parse_iof_result_list(_relay_doc(team))
        model = build_mop_model(parsed, _metadata(), parsed.warnings)
        team_obj = next(iter(model.teams.values()))
        assert team_obj.stat == STAT_DNF

    def test_temps_de_fraction_manquant_equipe_dnf(self):
        team = _relay_team(
            _relay_member('201', leg=1, time=None),
            organisation=(
                '<Organisation><Id>30</Id><Name>CO Test</Name></Organisation>'
            ),
        )
        parsed = parse_iof_result_list(_relay_doc(team))
        model = build_mop_model(parsed, _metadata(), parsed.warnings)
        team_obj = next(iter(model.teams.values()))
        assert team_obj.stat == STAT_DNF
        assert any('temps de fraction manquant' in w for w in parsed.warnings)

    def test_equipe_sans_organisation_ni_membre_classable(self):
        team = _relay_team(_relay_member('201', with_result=False))
        parsed = parse_iof_result_list(_relay_doc(team))
        model = build_mop_model(parsed, _metadata(), parsed.warnings)
        team_obj = next(iter(model.teams.values()))
        assert team_obj.stat == STAT_DNF
        assert team_obj.org == 0
        assert any('aucun membre classable' in w for w in parsed.warnings)

    def test_equipe_sans_organisation_utilise_celle_du_membre(self):
        member = _relay_member(
            '201', leg=1,
            organisation=(
                '<Organisation><Id>31</Id><Name>Club Membre</Name></Organisation>'
            ),
        )
        team = _relay_team(member)
        parsed = parse_iof_result_list(_relay_doc(team))
        model = build_mop_model(parsed, _metadata(), parsed.warnings)
        team_obj = next(iter(model.teams.values()))
        assert team_obj.org == 31

    def test_membre_sans_personne_ignore(self):
        team = _relay_team(
            _relay_member('201', leg=1, with_person=False),
            organisation=(
                '<Organisation><Id>30</Id><Name>CO Test</Name></Organisation>'
            ),
        )
        parsed = parse_iof_result_list(_relay_doc(team))
        model = build_mop_model(parsed, _metadata(), parsed.warnings)
        team_obj = next(iter(model.teams.values()))
        assert team_obj.stat == STAT_DNF
        assert any('sans personne' in w for w in parsed.warnings)


# ─── Métadonnées ─────────────────────────────────────────────────────────────

class TestMetadataEdges:

    @patch('results.iof_importer.Mopcompetition')
    def test_read_existing_metadata_datetime(self, MockComp):
        MockComp.objects.filter.return_value.first.return_value = SimpleNamespace(
            name='N', organizer='O', homepage='H',
            date=datetime(2026, 5, 17, 9, 30),
        )
        assert _read_existing_metadata(42)['date'] == '2026-05-17'

    @patch('results.iof_importer.Mopcompetition')
    def test_read_existing_metadata_date_texte(self, MockComp):
        MockComp.objects.filter.return_value.first.return_value = SimpleNamespace(
            name='N', organizer='O', homepage='H', date='2026-05-18',
        )
        assert _read_existing_metadata(42)['date'] == '2026-05-18'

    @patch('results.iof_importer.Mopcompetition')
    def test_read_existing_metadata_date_invalide(self, MockComp):
        MockComp.objects.filter.return_value.first.return_value = SimpleNamespace(
            name='N', organizer='O', homepage='H', date='pas-une-date',
        )
        assert 'date' not in _read_existing_metadata(42)

    @patch('results.iof_importer.Mopcompetition')
    def test_read_existing_metadata_erreur_db(self, MockComp):
        MockComp.objects.filter.side_effect = RuntimeError('boom')
        with pytest.raises(IofImportError) as excinfo:
            _read_existing_metadata(42)
        assert 'Impossible de lire' in str(excinfo.value)

    def test_metadata_date_prise_dans_une_course(self):
        event = IofEvent(
            name='E', date=None, organiser='', homepage='',
            races=[
                IofRace(number=1, name='', date=None),
                IofRace(number=2, name='', date=date(2026, 7, 1)),
            ],
        )
        parsed = IofResultList(event=event, classes=[], status='Complete',
                               race_number=1)
        metadata = _resolve_competition_metadata(parsed, None, False, parsed.warnings)
        assert metadata['date'] == '2026-07-01'

    @patch('results.iof_importer._read_existing_metadata', return_value={})
    def test_metadata_sans_date_utilise_aujourdhui(self, mock_existing):
        event = IofEvent(name='', date=None, organiser='', homepage='')
        parsed = IofResultList(event=event, classes=[], status='Complete',
                               race_number=None)
        metadata = _resolve_competition_metadata(parsed, 42, False, parsed.warnings)
        assert metadata['date'] == date.today().isoformat()
        assert metadata['name'] == 'Course 42'
        assert any("date de l'événement" in w.lower() for w in parsed.warnings)

    def test_metadata_sans_date_ni_cid(self):
        event = IofEvent(name='', date=None, organiser='', homepage='')
        parsed = IofResultList(event=event, classes=[], status='Complete',
                               race_number=None)
        metadata = _resolve_competition_metadata(parsed, None, False, parsed.warnings)
        assert metadata['name'] == 'Course'

    @patch('results.iof_importer._read_existing_metadata')
    def test_metadata_date_invalide_remplacee(self, mock_existing):
        mock_existing.return_value = {'date': 'pas-une-date', 'name': 'Nom'}
        event = IofEvent(name='E', date=None, organiser='', homepage='')
        parsed = IofResultList(event=event, classes=[], status='Complete',
                               race_number=None)
        metadata = _resolve_competition_metadata(parsed, 42, False, parsed.warnings)
        assert metadata['date'] == date.today().isoformat()
        assert any('Date de course invalide' in w for w in parsed.warnings)

    @patch('results.iof_importer.cache')
    def test_invalidation_cache_erreur_loggee(self, mock_cache):
        mock_cache.delete.side_effect = RuntimeError('boom')
        report = SimpleNamespace(class_ids=[10], course_hashes=['abcd1234'])
        _invalidate_caches(42, report)   # ne propage pas l'erreur
        mock_cache.delete.assert_called_once_with('raceindex:42')
