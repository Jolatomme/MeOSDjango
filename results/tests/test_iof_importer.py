"""
Tests de l'import IOF Data Standard v3 (ResultList).

Aucune base de données : ``process_mop_xml`` et ``Mopcompetition`` sont
mockés. Les tests vérifient le parseur, les conversions IOF → MOP, la
génération du document MOPComplete et les règles de remplacement.
"""

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pytest

from results.iof_importer import (
    IofImportError, build_mop_model, build_mop_xml, import_iof_result_list,
    inspect_iof_result_list, parse_iof_result_list,
)
from results.models import (
    STAT_CANCEL, STAT_DNF, STAT_DNS, STAT_DQ, STAT_MP, STAT_NP,
    STAT_OCC, STAT_OK, STAT_OT, STAT_UNKNOWN,
)
from results.mop_receiver import MOP_NS

IOF_NS = 'http://www.orienteering.org/datastandard/3.0'


# ─── Documents IOF de test ────────────────────────────────────────────────────

def _xml(body: str, *, status='Complete', version='3.0') -> bytes:
    attrs = [f'xmlns="{IOF_NS}"']
    if version is not None:
        attrs.append(f'iofVersion="{version}"')
    if status is not None:
        attrs.append(f'status="{status}"')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<ResultList {" ".join(attrs)}>{body}</ResultList>'
    ).encode()


def _event(name='Championnat test', event_date='2026-05-17',
           organiser='CO Test', homepage='https://example.org',
           races='') -> str:
    return (
        '<Event>'
        f'<Name>{name}</Name>'
        f'<StartTime><Date>{event_date}</Date></StartTime>'
        f'<Organiser><Name>{organiser}</Name></Organiser>'
        f'<URL type="Website">{homepage}</URL>'
        f'{races}'
        '</Event>'
    )


def _person_result(person_id='101', family='Doe', given='Jane',
                   org_id='20', org_name='CO Test', nat='FRA',
                   result='') -> str:
    return (
        '<PersonResult>'
        '<Person>'
        f'<Id>{person_id}</Id>'
        f'<Name><Family>{family}</Family><Given>{given}</Given></Name>'
        f'<Nationality code="{nat}"/>'
        '</Person>'
        '<Organisation>'
        f'<Id>{org_id}</Id><Name>{org_name}</Name>'
        f'<Country code="{nat}">France</Country>'
        '</Organisation>'
        f'{result}'
        '</PersonResult>'
    )


def _result(*, race_number=None, bib='7', start='2026-05-17T10:00:00',
            finish='2026-05-17T10:30:00', time='1800', status='OK',
            splits='', leg=None, leg_order=None, card='') -> str:
    race_attr = f' raceNumber="{race_number}"' if race_number is not None else ''
    parts = [f'<Result{race_attr}>']
    if leg is not None:
        parts.append(f'<Leg>{leg}</Leg>')
    if leg_order is not None:
        parts.append(f'<LegOrder>{leg_order}</LegOrder>')
    if bib:
        parts.append(f'<BibNumber>{bib}</BibNumber>')
    if start:
        parts.append(f'<StartTime>{start}</StartTime>')
    if finish:
        parts.append(f'<FinishTime>{finish}</FinishTime>')
    if time is not None:
        parts.append(f'<Time>{time}</Time>')
    if status:
        parts.append(f'<Status>{status}</Status>')
    parts.append(splits)
    if card:
        parts.append(f'<ControlCard>{card}</ControlCard>')
    parts.append('</Result>')
    return ''.join(parts)


def _split(code, time=None, status=None) -> str:
    attrs = f' status="{status}"' if status else ''
    time_xml = f'<Time>{time}</Time>' if time is not None else ''
    return f'<SplitTime{attrs}><ControlCode>{code}</ControlCode>{time_xml}</SplitTime>'


def _class_result(class_id='10', name='H21', content='') -> str:
    return (
        '<ClassResult>'
        f'<Class><Id>{class_id}</Id><Name>{name}</Name></Class>'
        f'{content}'
        '</ClassResult>'
    )


def _individual_xml(*, status='Complete', version='3.0') -> bytes:
    splits = (
        _split('31', '300')
        + _split('32', '600')
        + _split('100', '1800')
    )
    body = (
        _event()
        + _class_result(
            content=(
                _person_result(result=_result(splits=splits, card='123456'))
                + _person_result(
                    person_id='102', family='Martin', given='Edgar',
                    org_id='21', org_name='Autre club',
                    result=_result(
                        bib='8', time='1900', status='MissingPunch',
                        splits=_split('31', '310') + _split('32', '620'),
                    ),
                )
            )
        )
    )
    return _xml(body, status=status, version=version)


def _relay_xml() -> bytes:
    def member(person_id, family, leg, time, split_time):
        return (
            '<TeamMemberResult>'
            '<Person>'
            f'<Id>{person_id}</Id>'
            f'<Name><Family>{family}</Family><Given>Runner</Given></Name>'
            '</Person>'
            f'<Result>'
            f'<Leg>{leg}</Leg>'
            f'<BibNumber>{person_id}</BibNumber>'
            f'<StartTime>2026-05-17T1{leg}:00:00</StartTime>'
            f'<FinishTime>2026-05-17T1{leg}:30:00</FinishTime>'
            f'<Time>{time}</Time>'
            '<Status>OK</Status>'
            f'{_split("31", str(split_time))}'
            f'{_split("32", str(split_time + 100))}'
            '</Result>'
            '</TeamMemberResult>'
        )

    team = (
        '<TeamResult>'
        '<Name>Équipe Test</Name>'
        '<Organisation><Id>30</Id><Name>CO Test</Name>'
        '<Country code="FRA">France</Country></Organisation>'
        '<BibNumber>1</BibNumber>'
        f'{member("201", "Alpha", 1, "1500", 500)}'
        f'{member("202", "Beta", 2, "1600", 550)}'
        '</TeamResult>'
    )
    return _xml(_event() + _class_result(name='Relais', content=team))


def _multi_race_xml() -> bytes:
    races = (
        '<Race><RaceNumber>1</RaceNumber><Name>Étape 1</Name>'
        '<StartTime><Date>2026-05-17</Date></StartTime></Race>'
        '<Race><RaceNumber>2</RaceNumber><Name>Étape 2</Name>'
        '<StartTime><Date>2026-05-18</Date></StartTime></Race>'
    )
    person = _person_result(
        result=(
            _result(race_number=1, bib='1', time='1800')
            + _result(race_number=2, bib='1', time='1700')
        )
    )
    return _xml(_event(races=races) + _class_result(content=person))


# ─── Parseur ──────────────────────────────────────────────────────────────────

class TestParse:

    def test_parse_resultats_individuels(self):
        parsed = parse_iof_result_list(_individual_xml())

        assert parsed.event.name == 'Championnat test'
        assert parsed.event.date == date(2026, 5, 17)
        assert parsed.event.organiser == 'CO Test'
        assert parsed.event.homepage == 'https://example.org'
        assert parsed.race_number is None
        assert len(parsed.classes) == 1

        cls = parsed.classes[0]
        assert cls.iof_id == '10'
        assert cls.name == 'H21'
        assert len(cls.persons) == 2

        person = cls.persons[0]
        assert person.iof_id == '101'
        assert person.family == 'Doe'
        assert person.given == 'Jane'
        assert person.nationality == 'FRA'
        assert person.organisation.name == 'CO Test'

        result = person.results[0]
        assert result.status == 'OK'
        assert (result.stat, result.prel, result.tstat) == (STAT_OK, 0, STAT_OK)
        assert result.time_tenths == 18000
        assert result.start == datetime(2026, 5, 17, 10, 0)
        assert result.finish == datetime(2026, 5, 17, 10, 30)
        assert result.card == '123456'
        assert [(s.code, s.time_tenths) for s in result.splits] == [
            ('31', 3000), ('32', 6000), ('100', 18000),
        ]

    def test_statuts_iof_vers_mop(self):
        statuses = {
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
        }
        for iof_status, expected in statuses.items():
            body = (
                _event()
                + _class_result(
                    content=_person_result(
                        result=_result(status=iof_status, time=None,
                                       finish=None, splits=''),
                    )
                )
            )
            parsed = parse_iof_result_list(_xml(body))
            result = parsed.classes[0].persons[0].results[0]
            assert (result.stat, result.prel, result.tstat) == expected

    def test_statut_inconnu_devient_statut_mop_inconnu(self):
        body = (
            _event()
            + _class_result(
                content=_person_result(
                    result=_result(status='SomethingNew', time=None, finish=None),
                )
            )
        )
        parsed = parse_iof_result_list(_xml(body))
        result = parsed.classes[0].persons[0].results[0]
        assert (result.stat, result.prel, result.tstat) == (STAT_UNKNOWN, 0, 0)
        assert any('inconnu' in warning for warning in parsed.warnings)

    def test_temps_absent_utilise_fin_moins_depart(self):
        body = (
            _event()
            + _class_result(
                content=_person_result(
                    result=_result(time=None),
                )
            )
        )
        parsed = parse_iof_result_list(_xml(body))
        result = parsed.classes[0].persons[0].results[0]
        assert result.time_tenths == 18000

    def test_temps_negatif_ignore(self):
        body = (
            _event()
            + _class_result(
                content=_person_result(
                    result=_result(time='-5', finish=None),
                )
            )
        )
        parsed = parse_iof_result_list(_xml(body))
        result = parsed.classes[0].persons[0].results[0]
        assert result.time_tenths is None
        assert any('négatif' in warning for warning in parsed.warnings)

    def test_split_missing_conserve_dans_la_sequence(self):
        splits = _split('31', '300') + _split('32', status='Missing')
        body = (
            _event()
            + _class_result(
                content=_person_result(
                    result=_result(splits=splits),
                )
            )
        )
        parsed = parse_iof_result_list(_xml(body))
        result = parsed.classes[0].persons[0].results[0]
        assert [s.code for s in result.splits] == ['31', '32']
        assert result.splits[1].status == 'Missing'
        assert result.splits[1].time_tenths is None

    def test_fichier_multi_course_exige_un_numero(self):
        with pytest.raises(IofImportError) as excinfo:
            parse_iof_result_list(_multi_race_xml())
        assert '1, 2' in str(excinfo.value)

    def test_fichier_multi_course_selectionne_la_course(self):
        parsed = parse_iof_result_list(_multi_race_xml(), race_number=2)
        assert parsed.race_number == 2
        result = parsed.classes[0].persons[0].results[0]
        assert result.time_tenths == 17000
        assert result.bib == '1'

    def test_numero_de_course_inexistant(self):
        with pytest.raises(IofImportError) as excinfo:
            parse_iof_result_list(_multi_race_xml(), race_number=3)
        assert '3' in str(excinfo.value)

    def test_delta_refuse(self):
        with pytest.raises(IofImportError) as excinfo:
            parse_iof_result_list(_individual_xml(status='Delta'))
        assert 'Delta' in str(excinfo.value)

    def test_mauvais_namespace_refuse(self):
        xml = (
            '<ResultList xmlns="http://example.org/autre" iofVersion="3.0" '
            'status="Complete"><Event><Name>X</Name></Event></ResultList>'
        ).encode()
        with pytest.raises(IofImportError):
            parse_iof_result_list(xml)

    def test_racine_invalide_refusee(self):
        with pytest.raises(IofImportError):
            parse_iof_result_list(b'<MOPComplete/>')

    def test_doctype_refuse(self):
        xml = b'<!DOCTYPE x [<!ENTITY y "z">]><ResultList/>'
        with pytest.raises(IofImportError) as excinfo:
            parse_iof_result_list(xml)
        assert 'DOCTYPE' in str(excinfo.value)

    def test_xml_invalide(self):
        with pytest.raises(IofImportError):
            parse_iof_result_list(b'<ResultList>')

    def test_fichier_vide(self):
        with pytest.raises(IofImportError):
            parse_iof_result_list(b'   ')

    def test_classes_dupliquees_fusionnees(self):
        body = (
            _event()
            + _class_result(
                class_id='10', name='H21',
                content=_person_result(
                    person_id='101', result=_result(time='1800'),
                ),
            )
            + _class_result(
                class_id='10', name='H21',
                content=_person_result(
                    person_id='102', family='Martin',
                    result=_result(time='1900'),
                ),
            )
        )
        parsed = parse_iof_result_list(_xml(body))
        assert len(parsed.classes) == 1
        assert len(parsed.classes[0].persons) == 2
        assert any('fusionnés' in warning for warning in parsed.warnings)

    def test_classe_melange_individuel_et_equipe_refusee(self):
        body = (
            _event()
            + _class_result(
                class_id='10', name='H21',
                content=(
                    _person_result(result=_result())
                    + '<TeamResult><Name>T</Name>'
                    '<TeamMemberResult><Person><Id>9</Id><Name>'
                    '<Family>X</Family></Name></Person>'
                    '<Result><Leg>1</Leg><Time>100</Time>'
                    '<Status>OK</Status></Result>'
                    '</TeamMemberResult></TeamResult>'
                ),
            )
        )
        with pytest.raises(IofImportError) as excinfo:
            parse_iof_result_list(_xml(body))
        assert 'mélange' in str(excinfo.value)


# ─── Construction du modèle MOP et XML ───────────────────────────────────────

class TestBuild:

    def _model(self, xml=None, metadata=None):
        parsed = parse_iof_result_list(xml or _individual_xml())
        return parsed, build_mop_model(
            parsed,
            metadata or {
                'name': 'Course site',
                'date': '2026-05-17',
                'organizer': 'Club site',
                'homepage': 'https://site.example',
            },
            parsed.warnings,
        )

    def test_identifiants_et_circuits(self):
        _, model = self._model()
        assert set(model.classes) == {10}
        assert set(model.orgs) == {20, 21}
        assert set(model.competitors) == {101, 102}
        assert set(model.controls) == {31, 32, 100}
        assert model.classes[10].controls_by_leg[1] == [31, 32, 100]
        assert model.classes[10].name == 'H21'
        assert model.competitors[101].radio == [
            (31, 3000), (32, 6000), (100, 18000),
        ]
        assert model.competitors[101].nat == 'FRA'
        assert model.competitors[101].card == '123456'
        assert model.competitors[102].stat == STAT_MP

    def test_xml_mop_complete(self):
        _, model = self._model()
        xml = build_mop_xml(model)
        root = ET.fromstring(xml)

        assert root.tag == f'{{{MOP_NS}}}MOPComplete'
        competition = root.find(f'{{{MOP_NS}}}competition')
        assert competition.text == 'Course site'
        assert competition.get('date') == '2026-05-17'
        assert competition.get('organizer') == 'Club site'
        assert competition.get('homepage') == 'https://site.example'

        cls = root.find(f'{{{MOP_NS}}}cls')
        assert cls.get('id') == '10'
        assert cls.get('radio') == '31,32,100'
        assert cls.text == 'H21'

        controls = {
            elem.get('id'): elem.text
            for elem in root.findall(f'{{{MOP_NS}}}ctrl')
        }
        assert controls == {'31': '31', '32': '32', '100': '100'}

        cmp = root.find(f'{{{MOP_NS}}}cmp')
        assert cmp.get('id') == '101'
        assert cmp.get('card') == '123456'
        base = cmp.find(f'{{{MOP_NS}}}base')
        assert base.text == 'Doe Jane'
        assert base.get('org') == '20'
        assert base.get('cls') == '10'
        assert base.get('stat') == str(STAT_OK)
        assert base.get('st') == '360000'
        assert base.get('rt') == '18000'
        assert base.get('bib') == '7'
        assert base.get('nat') == 'FRA'
        input_elem = cmp.find(f'{{{MOP_NS}}}input')
        assert input_elem.get('it') == '378000'
        assert input_elem.get('tstat') == str(STAT_OK)
        radio = cmp.find(f'{{{MOP_NS}}}radio')
        assert radio.text == '31,3000;32,6000;100,18000'

    def test_relais_genere_equipe_et_fractions(self):
        parsed, model = self._model(_relay_xml())
        assert len(model.teams) == 1
        assert len(model.competitors) == 2
        assert model.classes[10].controls_by_leg == {
            1: [31, 32],
            2: [31, 32],
        }
        team = next(iter(model.teams.values()))
        assert team.stat == STAT_OK
        assert team.rt == 31000
        assert team.members == [(1, 0, 201), (2, 0, 202)]

        root = ET.fromstring(build_mop_xml(model))
        tm = root.find(f'{{{MOP_NS}}}tm')
        assert tm.find(f'{{{MOP_NS}}}base').text == 'Équipe Test'
        assert tm.find(f'{{{MOP_NS}}}r').text == '201;202'

    def test_relais_fraction_manquante_equipe_dnf(self):
        xml = _relay_xml().decode().replace(
            '<Leg>2</Leg>', '<Leg>3</Leg>',
        ).replace('T12:00:00', 'T13:00:00').replace('T12:30:00', 'T13:30:00').encode()
        parsed, model = self._model(xml)
        team = next(iter(model.teams.values()))
        assert team.stat == STAT_DNF
        assert any('fraction 2' in w for w in parsed.warnings)

    def test_controles_repetes_uniformes(self):
        splits = (
            _split('31', '300') + _split('32', '600')
            + _split('31', '900') + _split('100', '1200')
        )
        body = (
            _event()
            + _class_result(
                content=_person_result(result=_result(splits=splits)),
            )
        )
        parsed, model = self._model(_xml(body))
        assert model.classes[10].controls_by_leg[1] == [
            31, 32, 1_000_000_000, 100,
        ]
        assert model.competitors[101].radio == [
            (31, 3000), (32, 6000), (1_000_000_000, 9000), (100, 12000),
        ]

    def test_circuits_differents_fusionnes(self):
        body = (
            _event()
            + _class_result(
                content=(
                    _person_result(
                        person_id='101',
                        result=_result(splits=_split('31', '300') + _split('32', '600')),
                    )
                    + _person_result(
                        person_id='102', family='Martin',
                        result=_result(splits=_split('31', '310') + _split('33', '620')),
                    )
                )
            )
        )
        parsed, model = self._model(_xml(body))
        assert model.classes[10].controls_by_leg[1] == [31, 33, 32]
        assert any('fourches' in w for w in parsed.warnings)

    def test_identifiants_dupliques_rendus_uniques(self):
        body = (
            _event()
            + _class_result(
                content=(
                    _person_result(
                        person_id='101', result=_result(splits=_split('31', '300')),
                    )
                    + _person_result(
                        person_id='101', family='Martin',
                        result=_result(splits=_split('31', '310')),
                    )
                )
            )
        )
        parsed, model = self._model(_xml(body))
        ids = sorted(model.competitors)
        assert len(ids) == 2
        assert ids[0] == 101
        assert ids[1] >= 1_000_000_000
        assert any('dupliqué' in w for w in parsed.warnings)

    def test_code_poste_non_numerique_conserve(self):
        body = (
            _event()
            + _class_result(
                content=_person_result(
                    result=_result(splits=_split('A1', '300')),
                )
            )
        )
        parsed, model = self._model(_xml(body))
        assert model.controls[1_000_000_000].name == 'A1'
        assert model.classes[10].controls_by_leg[1] == [1_000_000_000]


# ─── Import, métadonnées et cache ────────────────────────────────────────────

def _existing(name='Nom site', day=date(2026, 5, 17),
              organizer='Club site', homepage='https://site.example'):
    return SimpleNamespace(
        name=name, date=day, organizer=organizer, homepage=homepage,
        livelox='https://livelox.example/1', logo='logo.png',
    )


class TestImport:

    @patch('results.iof_importer.cache')
    @patch('results.iof_importer.process_mop_xml', return_value='OK')
    @patch('results.iof_importer.Mopcompetition')
    def test_import_reussi_et_invalidation_cache(
            self, MockComp, mock_process, mock_cache):
        MockComp.objects.filter.return_value.first.return_value = _existing()

        report = import_iof_result_list(42, _individual_xml())

        assert report.status == 'OK'
        assert report.classes == 1
        assert report.competitors == 2
        assert report.teams == 0
        assert report.controls == 3
        assert report.splits == 5
        mock_process.assert_called_once()
        assert mock_process.call_args.args[0] == 42
        assert mock_process.call_args.args[1].startswith(b'<?xml')

        mock_cache.delete.assert_any_call('raceindex:42')
        mock_cache.delete.assert_any_call('live:42:10')
        for hash_value in report.course_hashes:
            mock_cache.delete.assert_any_call(f'live:42:{hash_value}')

    @patch('results.iof_importer.cache')
    @patch('results.iof_importer.process_mop_xml', return_value='FROZEN')
    @patch('results.iof_importer.Mopcompetition')
    def test_course_gelee_aucune_ecriture(
            self, MockComp, mock_process, mock_cache):
        MockComp.objects.filter.return_value.first.return_value = _existing()

        report = import_iof_result_list(42, _individual_xml())

        assert report.status == 'FROZEN'
        mock_cache.delete.assert_not_called()

    @patch('results.iof_importer.cache')
    @patch('results.iof_importer.process_mop_xml', return_value='ERROR')
    @patch('results.iof_importer.Mopcompetition')
    def test_echec_mop_leve_une_erreur(
            self, MockComp, mock_process, mock_cache):
        MockComp.objects.filter.return_value.first.return_value = _existing()

        with pytest.raises(IofImportError) as excinfo:
            import_iof_result_list(42, _individual_xml())
        assert 'ERROR' in str(excinfo.value)
        mock_cache.delete.assert_not_called()

    @patch('results.iof_importer.process_mop_xml', return_value='OK')
    @patch('results.iof_importer.Mopcompetition')
    def test_metadonnees_site_conservees_par_defaut(
            self, MockComp, mock_process):
        MockComp.objects.filter.return_value.first.return_value = _existing()

        import_iof_result_list(42, _individual_xml())

        root = ET.fromstring(mock_process.call_args.args[1])
        competition = root.find(f'{{{MOP_NS}}}competition')
        assert competition.text == 'Nom site'
        assert competition.get('date') == '2026-05-17'
        assert competition.get('organizer') == 'Club site'
        assert competition.get('homepage') == 'https://site.example'

    @patch('results.iof_importer.process_mop_xml', return_value='OK')
    @patch('results.iof_importer.Mopcompetition')
    def test_metadonnees_iof_sur_demande(self, MockComp, mock_process):
        MockComp.objects.filter.return_value.first.return_value = _existing()

        import_iof_result_list(
            42, _individual_xml(), use_event_metadata=True,
        )

        root = ET.fromstring(mock_process.call_args.args[1])
        competition = root.find(f'{{{MOP_NS}}}competition')
        assert competition.text == 'Championnat test'
        assert competition.get('organizer') == 'CO Test'
        assert competition.get('homepage') == 'https://example.org'

    @patch('results.iof_importer.process_mop_xml', return_value='OK')
    @patch('results.iof_importer.Mopcompetition')
    def test_champs_site_vides_completes_par_iof(self, MockComp, mock_process):
        MockComp.objects.filter.return_value.first.return_value = _existing(
            name='', organizer='', homepage='',
        )

        import_iof_result_list(42, _individual_xml())

        root = ET.fromstring(mock_process.call_args.args[1])
        competition = root.find(f'{{{MOP_NS}}}competition')
        assert competition.text == 'Championnat test'
        assert competition.get('organizer') == 'CO Test'
        assert competition.get('homepage') == 'https://example.org'

    @patch('results.iof_importer.process_mop_xml', return_value='OK')
    @patch('results.iof_importer.Mopcompetition')
    def test_aucune_competition_existante(self, MockComp, mock_process):
        MockComp.objects.filter.return_value.first.return_value = None

        import_iof_result_list(42, _individual_xml())

        root = ET.fromstring(mock_process.call_args.args[1])
        assert root.find(f'{{{MOP_NS}}}competition').text == 'Championnat test'

    @patch('results.iof_importer.process_mop_xml')
    def test_dry_run_necrit_pas(self, mock_process):
        report = inspect_iof_result_list(_individual_xml(), cid=None)

        assert report.status == 'DRY-RUN'
        assert report.classes == 1
        assert report.competitors == 2
        mock_process.assert_not_called()

    @patch('results.iof_importer.cache')
    @patch('results.iof_importer.process_mop_xml', return_value='OK')
    @patch('results.iof_importer.Mopcompetition')
    def test_import_multi_course(self, MockComp, mock_process, mock_cache):
        MockComp.objects.filter.return_value.first.return_value = _existing()

        report = import_iof_result_list(
            42, _multi_race_xml(), race_number=2,
        )

        assert report.race_number == 2
        root = ET.fromstring(mock_process.call_args.args[1])
        cmp = root.find(f'{{{MOP_NS}}}cmp')
        assert cmp.find(f'{{{MOP_NS}}}base').get('rt') == '17000'
