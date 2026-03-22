"""
Tests unitaires pour meos_checker.py (8 regles).

Aucune DB requise.
"""

import pytest
from results.meos_checker import (
    parse_meosxml,
    check_club_consecutif,
    check_entrelacement,
    check_premiers_postes,
    check_plages_continues,
    check_coordonnees_postes,
    check_circuits_vides,
    check_categories_vides,
    check_completude_coureurs,
    check_meos_file,
    Control, Course, Category, Club, Runner,
    _fmt_time,
)


# ── Helpers XML ───────────────────────────────────────────────────────────────

def _xml(body, zero_time=45000, name='Test', date='2026-01-01'):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<meosdata version="5.0">
<Name>{name}</Name>
<Date>{date}</Date>
<ZeroTime>{zero_time}</ZeroTime>
{body}
</meosdata>""".encode('utf-8')


def _control_list(*controls):
    """controls: (id, number, xpos, ypos) — pass None to omit a coord."""
    items = []
    for cid, number, xpos, ypos in controls:
        odata = ''
        if xpos is not None:
            odata += f'<xpos>{xpos}</xpos>'
        if ypos is not None:
            odata += f'<ypos>{ypos}</ypos>'
        items.append(
            f'<Control><Id>{cid}</Id><Numbers>{number}</Numbers>'
            f'<oData>{odata}</oData></Control>'
        )
    return '<ControlList>' + ''.join(items) + '</ControlList>'


def _course_list(*courses):
    """courses: (id, name, controls_str)"""
    items = [
        f'<Course><Id>{cid}</Id><Name>{name}</Name><Controls>{ctls}</Controls></Course>'
        for cid, name, ctls in courses
    ]
    return '<CourseList>' + ''.join(items) + '</CourseList>'


def _class_list(*classes):
    """classes: (id, name, course_id, first_start, interval)"""
    items = []
    for cid, name, course_id, first_start, interval in classes:
        items.append(
            f'<Class><Id>{cid}</Id><Name>{name}</Name><Course>{course_id}</Course>'
            f'<oData><FirstStart>{first_start}</FirstStart>'
            f'<StartInterval>{interval}</StartInterval></oData></Class>'
        )
    return '<ClassList>' + ''.join(items) + '</ClassList>'


def _club_list(*clubs):
    return '<ClubList>' + ''.join(
        f'<Club><Id>{cid}</Id><Name>{name}</Name></Club>'
        for cid, name in clubs
    ) + '</ClubList>'


def _runner_list(*runners):
    """runners: (id, name, start, club_id, class_id, card_no)"""
    items = []
    for rid, name, start, club_id, class_id, card_no in runners:
        start_tag = f'<Start>{start}</Start>' if start is not None else ''
        card_tag  = f'<CardNo>{card_no}</CardNo>' if card_no else ''
        club_tag  = f'<Club>{club_id}</Club>' if club_id else ''
        class_tag = f'<Class>{class_id}</Class>' if class_id else ''
        items.append(
            f'<Runner><Id>{rid}</Id><Name>{name}</Name>'
            f'{start_tag}{card_tag}{club_tag}{class_tag}</Runner>'
        )
    return '<RunnerList>' + ''.join(items) + '</RunnerList>'


def _minimal_body(**kwargs):
    controls = kwargs.get('controls', _control_list(('1', '61', '-10', '40')))
    courses  = kwargs.get('courses',  _course_list(('1', 'A', '1;')))
    cats     = kwargs.get('cats',     _class_list(('100', 'H21', '1', 3600, 120)))
    clubs    = kwargs.get('clubs',    _club_list(('10', 'COCS')))
    runners  = kwargs.get('runners',
                          _runner_list(('1', 'Alice', 3600, '10', '100', '12345')))
    return controls + courses + cats + clubs + runners


# ── Tests parse_meosxml ───────────────────────────────────────────────────────

class TestParseMeosxml:

    def test_xml_invalide_leve_valueerror(self):
        with pytest.raises(ValueError):
            parse_meosxml(b'pas du xml')

    def test_parse_nom_competition(self):
        xml = _xml(_minimal_body(), name='Mon Championnat')
        _, name, *_ = parse_meosxml(xml)
        assert name == 'Mon Championnat'

    def test_parse_zero_time(self):
        xml = _xml(_minimal_body(), zero_time=45000)
        zt, *_ = parse_meosxml(xml)
        assert zt == 45000

    def test_parse_date(self):
        xml = _xml(_minimal_body(), date='2026-03-28')
        _, _, date, *_ = parse_meosxml(xml)
        assert date == '2026-03-28'

    def test_parse_club_name(self):
        body = _minimal_body(clubs=_club_list(('10', 'COCS')))
        _, _, _, _, _, clubs, _ = parse_meosxml(_xml(body))
        assert clubs['10'].name == 'COCS'

    def test_parse_category_name(self):
        body = _minimal_body(cats=_class_list(('100', 'H21', '1', 3600, 120)))
        _, _, _, _, categories, _, _ = parse_meosxml(_xml(body))
        assert categories['100'].name == 'H21'

    def test_parse_course_name(self):
        body = _minimal_body(courses=_course_list(('1', 'Circuit A', '79;80;')))
        _, _, _, courses, _, _, _ = parse_meosxml(_xml(body))
        assert courses['1'].name == 'Circuit A'
        assert courses['1'].controls == [79, 80]

    def test_parse_runner_name_et_start(self):
        body = _minimal_body(runners=_runner_list(('1', 'Alice', 3600, '10', '100', '99')))
        *_, runners = parse_meosxml(_xml(body))
        assert runners[0].name == 'Alice'
        assert runners[0].start == 3600
        assert runners[0].card_no == '99'

    def test_parse_runner_sans_card_no(self):
        body = _minimal_body(runners=_runner_list(('1', 'Alice', 3600, '10', '100', None)))
        *_, runners = parse_meosxml(_xml(body))
        assert runners[0].card_no is None

    def test_parse_runner_sans_depart(self):
        body = _minimal_body(runners=_runner_list(('1', 'Alice', None, '10', '100', '1')))
        *_, runners = parse_meosxml(_xml(body))
        assert runners[0].start is None

    def test_parse_control_avec_coords(self):
        body = _minimal_body(controls=_control_list(('61', '61', '-10.1', '40.')))
        _, _, _, controls, *_ = parse_meosxml(_xml(body))
        assert controls['61'].has_xpos is True
        assert controls['61'].has_ypos is True

    def test_parse_control_sans_xpos(self):
        body = _minimal_body(controls=_control_list(('83', '83', None, '-11.7')))
        _, _, _, controls, *_ = parse_meosxml(_xml(body))
        assert controls['83'].has_xpos is False
        assert controls['83'].has_ypos is True


# ── Tests R1 : club consecutif ────────────────────────────────────────────────

class TestCheckClubConsecutif:

    def _mk(self):
        courses    = {'1': Course('1', 'A', [79])}
        clubs      = {'10': Club('10', 'COCS'), '20': Club('20', 'ANO')}
        categories = {'100': Category('100', 'H21', '1', 3600, 120)}
        return courses, clubs, categories

    def _run(self, runners, categories, courses, clubs, zt=45000):
        return check_club_consecutif(runners, categories, courses, clubs, zt)

    def test_ok_clubs_differents(self):
        co, cl, ca = self._mk()
        r = [Runner('1', 'Alice', 3600, '10', '100', '1'),
             Runner('2', 'Bob',   3720, '20', '100', '2')]
        assert self._run(r, ca, co, cl).status == 'ok'

    def test_violation_meme_club(self):
        co, cl, ca = self._mk()
        r = [Runner('1', 'Alice', 3600, '10', '100', '1'),
             Runner('2', 'Bob',   3720, '10', '100', '2')]
        res = self._run(r, ca, co, cl)
        assert res.status == 'error'
        assert len(res.violations) == 1
        assert 'COCS' in res.violations[0].description
        assert 'Alice' in res.violations[0].description
        assert 'Bob'   in res.violations[0].description
        assert 'A'     in res.violations[0].description

    def test_non_consecutifs_ok(self):
        co, cl, ca = self._mk()
        r = [Runner('1', 'Alice',   3600, '10', '100', '1'),
             Runner('2', 'Bob',     3720, '20', '100', '2'),
             Runner('3', 'Charlie', 3840, '10', '100', '3')]
        assert self._run(r, ca, co, cl).status == 'ok'

    def test_sans_club_ignore(self):
        co, cl, ca = self._mk()
        r = [Runner('1', 'Alice', 3600, None, '100', '1'),
             Runner('2', 'Bob',   3720, None, '100', '2')]
        assert self._run(r, ca, co, cl).status == 'ok'

    def test_plusieurs_violations(self):
        co, cl, ca = self._mk()
        r = [Runner('1', 'A', 3600, '10', '100', '1'),
             Runner('2', 'B', 3720, '10', '100', '2'),
             Runner('3', 'C', 3840, '20', '100', '3'),
             Runner('4', 'D', 3960, '20', '100', '4')]
        assert len(self._run(r, ca, co, cl).violations) == 2


# ── Tests R2 : entrelacement ──────────────────────────────────────────────────

class TestCheckEntrelacement:

    def _run(self, runners, categories, courses, zt=45000):
        return check_entrelacement(runners, categories, courses, zt)

    def test_blocs_distincts_ok(self):
        co = {'1': Course('1', 'A', [79])}
        ca = {'100': Category('100', 'H21', '1', 3600, 120),
              '200': Category('200', 'D21', '1', 3840, 120)}
        r  = [Runner('1', 'A', 3600, '10', '100', '1'),
              Runner('2', 'B', 3720, '20', '100', '2'),
              Runner('3', 'C', 3840, '10', '200', '3'),
              Runner('4', 'D', 3960, '20', '200', '4')]
        assert self._run(r, ca, co).status == 'ok'

    def test_entrelacement_detecte(self):
        co = {'1': Course('1', 'A', [79])}
        ca = {'100': Category('100', 'H21', '1', 0, 120),
              '200': Category('200', 'D21', '1', 0, 120)}
        r  = [Runner('1', 'A', 3600, '10', '100', '1'),
              Runner('2', 'B', 3720, '20', '200', '2'),
              Runner('3', 'C', 3840, '30', '100', '3')]
        res = self._run(r, ca, co)
        assert res.status == 'error'
        assert 'H21' in res.violations[0].description
        assert 'A'   in res.violations[0].description


# ── Tests R3 : premiers postes ────────────────────────────────────────────────

class TestCheckPremiersPostes:

    def test_uniques_ok(self):
        co = {'1': Course('1', 'A', [79, 80]),
              '2': Course('2', 'B', [98, 80]),
              '3': Course('3', 'C', [100, 79])}
        assert check_premiers_postes(co).status == 'ok'

    def test_conflit_detecte(self):
        co = {'1': Course('1', 'A', [79, 80]),
              '2': Course('2', 'B', [79, 98])}
        res = check_premiers_postes(co)
        assert res.status == 'error'
        assert '79' in res.violations[0].description
        assert 'A'  in res.violations[0].description
        assert 'B'  in res.violations[0].description

    def test_circuit_vide_ignore(self):
        co = {'1': Course('1', 'A', [79]), '2': Course('2', 'Vide', [])}
        assert check_premiers_postes(co).status == 'ok'


# ── Tests R4 : plages continues ───────────────────────────────────────────────

class TestCheckPlagesContinues:

    def _run(self, runners, categories, courses, zt=45000):
        return check_plages_continues(runners, categories, courses, zt)

    def test_plages_ok(self):
        co = {'1': Course('1', 'A', [79])}
        ca = {'100': Category('100', 'H21', '1', 0, 120),
              '200': Category('200', 'D21', '1', 0, 120)}
        r  = [Runner('1', 'A', 3600, '10', '100', '1'),
              Runner('2', 'B', 3720, '10', '100', '2'),
              Runner('3', 'C', 3840, '20', '200', '3'),
              Runner('4', 'D', 3960, '20', '200', '4')]
        assert self._run(r, ca, co).status == 'ok'

    def test_intrusion_detectee(self):
        co = {'1': Course('1', 'A', [79])}
        ca = {'100': Category('100', 'H21', '1', 0, 120),
              '200': Category('200', 'D21', '1', 0, 120)}
        r  = [Runner('1', 'Alice', 3600, '10', '100', '1'),
              Runner('2', 'Xavier', 3720, '20', '200', '2'),
              Runner('3', 'Bob',   3840, '10', '100', '3')]
        res = self._run(r, ca, co)
        assert res.status == 'error'
        assert 'H21' in res.violations[0].description
        assert 'D21' in res.violations[0].description
        assert 'Xavier' in res.violations[0].runners[0]


# ── Tests R5 : coordonnees postes ─────────────────────────────────────────────

class TestCheckCoordonneesPostes:

    def test_tous_ok(self):
        ctrls = {'61': Control('61', '61', True, True)}
        assert check_coordonnees_postes(ctrls).status == 'ok'

    def test_xpos_manquant(self):
        ctrls = {'83': Control('83', '83', False, True)}
        res = check_coordonnees_postes(ctrls)
        assert res.status == 'error'
        assert '83' in res.violations[0].description
        assert 'xpos' in res.violations[0].description

    def test_ypos_manquant(self):
        ctrls = {'83': Control('83', '83', True, False)}
        res = check_coordonnees_postes(ctrls)
        assert 'ypos' in res.violations[0].description

    def test_les_deux_manquants(self):
        ctrls = {'83': Control('83', '83', False, False)}
        res = check_coordonnees_postes(ctrls)
        assert 'xpos' in res.violations[0].description
        assert 'ypos' in res.violations[0].description

    def test_aucun_controle(self):
        assert check_coordonnees_postes({}).status == 'ok'


# ── Tests R6 : circuits vides ─────────────────────────────────────────────────

class TestCheckCircuitsVides:

    def test_ok(self):
        assert check_circuits_vides({'1': Course('1', 'A', [79])}).status == 'ok'

    def test_circuit_vide_detecte(self):
        co = {'1': Course('1', 'A', [79]), '2': Course('2', 'Vide', [])}
        res = check_circuits_vides(co)
        assert res.status == 'error'
        assert 'Vide' in res.violations[0].description

    def test_plusieurs_vides(self):
        co = {'1': Course('1', 'A', []), '2': Course('2', 'B', []), '3': Course('3', 'C', [79])}
        assert len(check_circuits_vides(co).violations) == 2


# ── Tests R7 : categories vides ───────────────────────────────────────────────

class TestCheckCategoriesVides:

    def test_toutes_ok(self):
        cats = {'100': Category('100', 'H21', '1', 0, 120)}
        r    = [Runner('1', 'A', 3600, '10', '100', '1')]
        assert check_categories_vides(r, cats).status == 'ok'

    def test_categorie_vide_warning(self):
        cats = {'100': Category('100', 'H21', '1', 0, 120),
                '200': Category('200', 'D21', '1', 0, 120)}
        r    = [Runner('1', 'A', 3600, '10', '100', '1')]
        res  = check_categories_vides(r, cats)
        assert res.status == 'warning'
        assert 'D21' in res.violations[0].description


# ── Tests R8 : completude coureurs ────────────────────────────────────────────

class TestCheckCompletudeCoureurs:

    def _run(self, runners, categories=None, courses=None):
        if categories is None:
            categories = {'100': Category('100', 'H21', '1', 0, 120)}
        if courses is None:
            courses = {'1': Course('1', 'A', [79])}
        return check_completude_coureurs(runners, categories, courses)

    def test_coureur_complet_ok(self):
        assert self._run([Runner('1', 'Alice', 3600, '10', '100', '99')]).status == 'ok'

    def test_sans_card_no(self):
        res = self._run([Runner('1', 'Alice', 3600, '10', '100', None)])
        assert res.status == 'error'
        assert 'Alice' in res.violations[0].description
        assert 'CardNo' in res.violations[0].description

    def test_sans_depart(self):
        res = self._run([Runner('1', 'Alice', None, '10', '100', '99')])
        assert res.status == 'error'
        assert 'Alice' in res.violations[0].description
        assert 'depart' in res.violations[0].description

    def test_sans_categorie(self):
        res = self._run([Runner('1', 'Alice', 3600, '10', None, '99')])
        assert res.status == 'error'
        assert 'categorie' in res.violations[0].description

    def test_id_duplique(self):
        r = [Runner('1', 'Alice', 3600, '10', '100', '1'),
             Runner('1', 'Bob',   3720, '20', '100', '2')]
        res = self._run(r)
        assert res.status == 'error'
        dups = [v for v in res.violations if 'dupliqu' in v.description.lower()]
        assert len(dups) == 1
        assert 'Alice' in dups[0].description
        assert 'Bob'   in dups[0].description


# ── Tests check_meos_file ─────────────────────────────────────────────────────

class TestCheckMeosFile:

    def _build(self, **kwargs):
        return _xml(_minimal_body(**kwargs))

    def test_xml_invalide(self):
        with pytest.raises(ValueError):
            check_meos_file(b'not xml')

    def test_huit_regles(self):
        report = check_meos_file(self._build())
        assert len(report.results) == 8
        expected = {
            'club_consecutif', 'entrelacement', 'premiers_postes', 'plages_continues',
            'coordonnees_postes', 'circuits_vides', 'categories_vides', 'completude_coureurs',
        }
        assert {r.rule_id for r in report.results} == expected

    def test_fichier_valide_ok(self):
        report = check_meos_file(self._build())
        assert not report.has_errors

    def test_metadata(self):
        report = check_meos_file(_xml(_minimal_body(), name='Champ.', date='2026-03-28'))
        assert report.competition_name == 'Champ.'
        assert report.competition_date == '2026-03-28'
        assert report.n_courses == 1
        assert report.n_classes == 1
        assert report.n_runners == 1

    def test_n_runners_hors_tires_exclus(self):
        runners = _runner_list(
            ('1', 'Alice', 3600, '10', '100', '1'),
            ('2', 'Bob',   None, '10', '100', '2'),
        )
        report = check_meos_file(_xml(_minimal_body(runners=runners)))
        assert report.n_runners == 1

    def test_erreur_xpos_manquant(self):
        ctrls  = _control_list(('83', '83', None, '-11.7'))
        report = check_meos_file(_xml(_minimal_body(controls=ctrls)))
        rule   = next(r for r in report.results if r.rule_id == 'coordonnees_postes')
        assert rule.status == 'error'
        assert '83' in rule.violations[0].description

    def test_erreur_card_no_manquant(self):
        runners = _runner_list(('1', 'Alice', 3600, '10', '100', None))
        report  = check_meos_file(_xml(_minimal_body(runners=runners)))
        rule    = next(r for r in report.results if r.rule_id == 'completude_coureurs')
        assert rule.status == 'error'

    def test_warning_categorie_vide(self):
        cats = _class_list(('100', 'H21', '1', 3600, 120),
                           ('200', 'D21', '1', 4800, 120))
        report = check_meos_file(_xml(_minimal_body(cats=cats)))
        rule   = next(r for r in report.results if r.rule_id == 'categories_vides')
        assert rule.status == 'warning'


# ── Tests _fmt_time ───────────────────────────────────────────────────────────

class TestFmtTime:

    def test_heure_correcte(self):
        assert _fmt_time(3600, zero_time=45000) == '13:30'

    def test_zero(self):
        assert _fmt_time(0, zero_time=0) == '00:00'

    def test_minutes(self):
        assert _fmt_time(3720, zero_time=45000) == '13:32'


# ── Tests vue Django ──────────────────────────────────────────────────────────

class TestMeosCheckerView:

    def _get(self):
        from django.test import RequestFactory
        return RequestFactory().get('/checker/')

    def _post(self, xml_bytes):
        from django.test import RequestFactory
        from io import BytesIO
        from django.core.files.uploadedfile import InMemoryUploadedFile
        f = InMemoryUploadedFile(
            BytesIO(xml_bytes), 'meosfile', 'test.meosxml',
            'application/xml', len(xml_bytes), None,
        )
        return RequestFactory().post('/checker/', {'meosfile': f})

    def test_get_sans_rapport(self):
        from unittest.mock import patch
        with patch('results.views.render') as mock_render:
            from results.views import meos_checker_view
            meos_checker_view(self._get())
            _, template, ctx = mock_render.call_args[0]
        assert template == 'results/meos_checker.html'
        assert ctx.get('report') is None

    def test_post_valide_retourne_rapport(self):
        from unittest.mock import patch
        xml = _xml(_minimal_body())
        with patch('results.views.render') as mock_render:
            from results.views import meos_checker_view
            meos_checker_view(self._post(xml))
            _, _, ctx = mock_render.call_args[0]
        assert ctx['report'] is not None
        assert len(ctx['report'].results) == 8

    def test_post_xml_invalide_retourne_erreur(self):
        from unittest.mock import patch
        with patch('results.views.render') as mock_render:
            from results.views import meos_checker_view
            meos_checker_view(self._post(b'not xml'))
            _, _, ctx = mock_render.call_args[0]
        assert ctx.get('parse_error') is not None
        assert ctx.get('report') is None

    def test_post_sans_fichier(self):
        from unittest.mock import patch
        from django.test import RequestFactory
        req = RequestFactory().post('/checker/')
        with patch('results.views.render') as mock_render:
            from results.views import meos_checker_view
            meos_checker_view(req)
            _, _, ctx = mock_render.call_args[0]
        assert ctx.get('report') is None
        assert ctx.get('parse_error') is None
