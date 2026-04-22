"""
Tests unitaires — circuits et vue unifiée catégorie/circuit.

Architecture clé : _load_class_context détecte si class_id est un hash
8-char hex et charge le circuit en conséquence. Les vues d'analyse sont
partagées entre catégories et circuits sans duplication.

Couvre :
  - services.compute_course_hash()
  - services.get_courses_map()
  - views._load_class_context() — détection automatique hash/catégorie
  - views._controls_for()
  - views.class_results() en mode circuit → template course_results.html
  - views.superman_analysis() en mode circuit
  - views.performance_analysis() en mode circuit
  - views.regularity_analysis() en mode circuit
  - views.grouping_analysis() en mode circuit
  - views.grouping_index_analysis() en mode circuit
  - views.duel_analysis() en mode circuit
  - URLs circuit (aliases vers les mêmes vues)
  - competition_detail : courses_map dans le contexte
"""

from unittest.mock import patch, MagicMock
import pytest
import json

from results.models import STAT_OK, STAT_DNF


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_competitor(id=1, rt=5000, stat=STAT_OK, name='Coureur', org=1, cls=10, st=100000):
    c = MagicMock()
    c.id    = id
    c.rt    = rt
    c.stat  = stat
    c.name  = name
    c.org   = org
    c.cls   = cls
    c.st    = st
    c.is_ok = (stat == STAT_OK and rt > 0)
    c.status_label = 'OK'
    c.status_badge = 'success'
    return c


def make_cls(id=10, name='H21', ord_=10):
    c = MagicMock()
    c.id   = id
    c.name = name
    c.ord  = ord_
    return c


def make_cc(cls_id, ctrl, leg=1, ord_=0):
    cc = MagicMock()
    cc.id   = cls_id
    cc.ctrl = ctrl
    cc.leg  = leg
    cc.ord  = ord_
    return cc


def make_ctrl(id_, name):
    c = MagicMock()
    c.id   = id_
    c.name = name
    return c


def rf_get(url='/', **params):
    from django.test import RequestFactory
    if params:
        url += '?' + '&'.join(f'{k}={v}' for k, v in params.items())
    return RequestFactory().get(url)


def _make_course(hash_='abc12345', class_ids=None, classes=None,
                 controls_seq=None, n_controls=None):
    class_ids    = class_ids    or [10]
    classes      = classes      or [make_cls(10, 'H21')]
    controls_seq = controls_seq or []
    return {
        'hash':             hash_,
        'raw_key':          ','.join(str(c['ctrl_id']) for c in controls_seq),
        'controls_seq':     controls_seq,
        'control_name_map': {},
        'class_ids':        class_ids,
        'classes':          classes,
        'n_controls':       n_controls if n_controls is not None else len(controls_seq),
        'display_name':     ' / '.join(c.name for c in classes[:4]),
    }


def _setup_load_context(mock_get404, mock_gcm, MockComp, competitors,
                        course=None, course_hash='abc12345'):
    """Configure les mocks pour que _load_class_context retourne le circuit."""
    competition = MagicMock(); competition.cid = 1
    mock_get404.return_value = competition
    if course is None:
        course = _make_course(course_hash)
    mock_gcm.return_value = {course_hash: course}
    MockComp.objects.filter.return_value = competitors
    return competition, course


# ══════════════════════════════════════════════════════════════════════════════
# compute_course_hash
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeCourseHash:

    def _call(self, controls_seq):
        from results.services import compute_course_hash
        return compute_course_hash(controls_seq)

    def test_sequence_vide_donne_zeros(self):
        assert self._call([]) == '00000000'

    def test_meme_sequence_meme_hash(self):
        seq = [{'ctrl_id': 31}, {'ctrl_id': 32}]
        assert self._call(seq) == self._call(list(seq))

    def test_sequences_differentes_hashes_differents(self):
        assert self._call([{'ctrl_id': 31}]) != self._call([{'ctrl_id': 32}])

    def test_ordre_different_hash_different(self):
        assert self._call([{'ctrl_id': 31}, {'ctrl_id': 32}]) != \
               self._call([{'ctrl_id': 32}, {'ctrl_id': 31}])

    def test_longueur_8_chars_hex(self):
        import re
        h = self._call([{'ctrl_id': 31}])
        assert re.fullmatch(r'[0-9a-f]{8}', h)

    def test_ctrl_name_ignore(self):
        seq1 = [{'ctrl_id': 31, 'ctrl_name': 'NomA'}]
        seq2 = [{'ctrl_id': 31, 'ctrl_name': 'NomB'}]
        assert self._call(seq1) == self._call(seq2)

    def test_reproductible(self):
        seq = [{'ctrl_id': 31}, {'ctrl_id': 32}]
        assert self._call(seq) == self._call(seq) == self._call(seq)

    def test_un_seul_poste_non_zero(self):
        assert self._call([{'ctrl_id': 99}]) != '00000000'


# ══════════════════════════════════════════════════════════════════════════════
# get_courses_map
# ══════════════════════════════════════════════════════════════════════════════

class TestGetCoursesMap:

    @patch('results.services.Mopcontrol')
    @patch('results.services.Mopclasscontrol')
    @patch('results.services.Mopclass')
    def test_vide_si_aucune_categorie(self, MockClass, MockCC, MockCtrl):
        MockClass.objects.filter.return_value.order_by.return_value = []
        from results.services import get_courses_map
        assert get_courses_map(cid=1) == {}

    @patch('results.services.Mopcontrol')
    @patch('results.services.Mopclasscontrol')
    @patch('results.services.Mopclass')
    def test_une_categorie_un_circuit(self, MockClass, MockCC, MockCtrl):
        cls1 = make_cls(10, 'H21')
        MockClass.objects.filter.return_value.order_by.return_value = [cls1]
        MockCC.objects.filter.return_value.order_by.return_value = [
            make_cc(10, 31, 1, 0), make_cc(10, 32, 1, 1)
        ]
        MockCtrl.objects.filter.return_value = [make_ctrl(31, 'P31'), make_ctrl(32, 'P32')]

        from results.services import get_courses_map
        result = get_courses_map(cid=1)
        assert len(result) == 1
        course = list(result.values())[0]
        assert course['class_ids']  == [10]
        assert course['n_controls'] == 2
        assert len(course['hash'])  == 8

    @patch('results.services.Mopcontrol')
    @patch('results.services.Mopclasscontrol')
    @patch('results.services.Mopclass')
    def test_deux_categories_meme_circuit_un_seul_groupe(self, MockClass, MockCC, MockCtrl):
        cls_h21 = make_cls(10, 'H21'); cls_d21 = make_cls(11, 'D21')
        MockClass.objects.filter.return_value.order_by.return_value = [cls_h21, cls_d21]
        MockCC.objects.filter.return_value.order_by.return_value = [
            make_cc(10, 31), make_cc(10, 32), make_cc(11, 31), make_cc(11, 32),
        ]
        MockCtrl.objects.filter.return_value = [make_ctrl(31, 'P31'), make_ctrl(32, 'P32')]

        from results.services import get_courses_map
        result = get_courses_map(cid=1)
        assert len(result) == 1
        assert set(list(result.values())[0]['class_ids']) == {10, 11}

    @patch('results.services.Mopcontrol')
    @patch('results.services.Mopclasscontrol')
    @patch('results.services.Mopclass')
    def test_deux_circuits_differents(self, MockClass, MockCC, MockCtrl):
        MockClass.objects.filter.return_value.order_by.return_value = [
            make_cls(10, 'H21'), make_cls(11, 'H35')
        ]
        MockCC.objects.filter.return_value.order_by.return_value = [
            make_cc(10, 31), make_cc(10, 32),
            make_cc(11, 33), make_cc(11, 34),
        ]
        MockCtrl.objects.filter.return_value = []

        from results.services import get_courses_map
        assert len(get_courses_map(cid=1)) == 2

    @patch('results.services.Mopcontrol')
    @patch('results.services.Mopclasscontrol')
    @patch('results.services.Mopclass')
    def test_hash_coherent_avec_compute_course_hash(self, MockClass, MockCC, MockCtrl):
        MockClass.objects.filter.return_value.order_by.return_value = [make_cls(10, 'H21')]
        MockCC.objects.filter.return_value.order_by.return_value = [
            make_cc(10, 31, 1, 0), make_cc(10, 32, 1, 1)
        ]
        MockCtrl.objects.filter.return_value = []

        from results.services import get_courses_map, compute_course_hash
        courses = get_courses_map(cid=1)
        course  = list(courses.values())[0]
        assert compute_course_hash(course['controls_seq']) == course['hash']

    @patch('results.services.Mopcontrol')
    @patch('results.services.Mopclasscontrol')
    @patch('results.services.Mopclass')
    def test_display_name_une_categorie(self, MockClass, MockCC, MockCtrl):
        MockClass.objects.filter.return_value.order_by.return_value = [make_cls(10, 'H21')]
        MockCC.objects.filter.return_value.order_by.return_value = []
        MockCtrl.objects.filter.return_value = []

        from results.services import get_courses_map
        course = list(get_courses_map(cid=1).values())[0]
        assert course['display_name'] == 'H21'

    @patch('results.services.Mopcontrol')
    @patch('results.services.Mopclasscontrol')
    @patch('results.services.Mopclass')
    def test_display_name_plus_de_quatre(self, MockClass, MockCC, MockCtrl):
        classes = [make_cls(i, f'C{i}') for i in range(1, 7)]
        MockClass.objects.filter.return_value.order_by.return_value = classes
        MockCC.objects.filter.return_value.order_by.return_value = [make_cc(i, 31) for i in range(1, 7)]
        MockCtrl.objects.filter.return_value = []

        from results.services import get_courses_map
        course = list(get_courses_map(cid=1).values())[0]
        assert '+2' in course['display_name']

    @patch('results.services.Mopcontrol')
    @patch('results.services.Mopclasscontrol')
    @patch('results.services.Mopclass')
    def test_trois_requetes_db_exactement(self, MockClass, MockCC, MockCtrl):
        cls = make_cls(10, 'H21')
        MockClass.objects.filter.return_value.order_by.return_value = [cls]
        MockCC.objects.filter.return_value.order_by.return_value = []
        MockCtrl.objects.filter.return_value = []
        from results.services import get_courses_map
        get_courses_map(cid=42)
        MockClass.objects.filter.assert_called_once_with(cid=42)
        assert MockCC.objects.filter.call_count == 1


# ══════════════════════════════════════════════════════════════════════════════
# _load_class_context — détection hash/catégorie
# ══════════════════════════════════════════════════════════════════════════════

class TestLoadClassContextCourseDetection:
    """Vérifie que _load_class_context détecte correctement les hashes."""

    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_courses_map')
    @patch('results.views.get_object_or_404')
    def test_hash_8_hex_charge_course(self, mock_get404, mock_gcm, MockComp):
        competition = MagicMock(); competition.cid = 1
        mock_get404.return_value = competition
        cls1 = make_cls(10, 'H21')
        mock_gcm.return_value = {'abc12345': _make_course('abc12345', [10], [cls1])}
        MockComp.objects.filter.return_value = []

        from results.views import _load_class_context
        comp, cls, competitors, course = _load_class_context(1, 'abc12345')

        assert course is not None
        assert course['hash'] == 'abc12345'
        assert cls.name == 'abc12345'   # le nom = le hash dans les URLs

    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_courses_map')
    @patch('results.views.get_object_or_404')
    def test_nom_categorie_charge_classe(self, mock_get404, mock_gcm, MockComp):
        mock_gcm.return_value = {}
        # 3 calls to get_object_or_404 via side_effect: for comp, _resolve, and final cls load
        mock_get404.side_effect = [MagicMock(), MagicMock(), MagicMock()]
        MockComp.objects.filter.return_value = []

        from results.views import _load_class_context
        comp, cls, competitors, course = _load_class_context(1, 'H21')

        assert course is None

    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopclass')
    @patch('results.views.get_object_or_404')
    def test_entier_charge_classe(self, mock_get404, MockClass, MockComp):
        competition = MagicMock()
        cls_obj     = make_cls(10, 'H21')
        mock_get404.side_effect = [competition, cls_obj]
        MockComp.objects.filter.return_value = []

        from results.views import _load_class_context
        _, _, _, course = _load_class_context(1, 10)

        assert course is None

    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_courses_map')
    @patch('results.views.get_object_or_404')
    def test_hash_inconnu_leve_404(self, mock_get404, mock_gcm, MockComp):
        from django.http import Http404
        mock_get404.return_value = MagicMock()
        mock_gcm.return_value    = {}

        from results.views import _load_class_context
        with pytest.raises(Http404):
            _load_class_context(1, 'aaaaaaaa')

    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_courses_map')
    @patch('results.views.get_object_or_404')
    def test_hash_7_chars_traite_comme_categorie(self, mock_get404, mock_gcm, MockComp):
        """Un string qui ressemble à un hash mais avec 7 chars n'est pas détecté."""
        from django.http import Http404
        competition = MagicMock()
        mock_get404.side_effect = [competition, Http404()]

        from results.views import _load_class_context
        # 7 chars hex → pas reconnu comme hash → tentative catégorie → 404
        with pytest.raises(Http404):
            _load_class_context(1, 'abc1234')

    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_courses_map')
    @patch('results.views.get_object_or_404')
    def test_class_obj_attache_aux_competitors(self, mock_get404, mock_gcm, MockComp):
        competition = MagicMock()
        mock_get404.return_value = competition
        cls1 = make_cls(10, 'H21')
        mock_gcm.return_value = {'abc12345': _make_course('abc12345', [10], [cls1])}
        c = make_competitor(1, cls=10)
        MockComp.objects.filter.return_value = [c]

        from results.views import _load_class_context
        _, _, competitors, _ = _load_class_context(1, 'abc12345')

        assert hasattr(competitors[0], 'class_obj')
        assert competitors[0].class_obj is cls1

    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_courses_map')
    @patch('results.views.get_object_or_404')
    def test_competitors_de_toutes_les_categories_du_circuit(
        self, mock_get404, mock_gcm, MockComp
    ):
        competition = MagicMock()
        mock_get404.return_value = competition
        cls1 = make_cls(10, 'H21'); cls2 = make_cls(11, 'D21')
        mock_gcm.return_value = {
            'abc12345': _make_course('abc12345', [10, 11], [cls1, cls2])
        }
        c1 = make_competitor(1, cls=10); c2 = make_competitor(2, cls=11)
        MockComp.objects.filter.side_effect = [[c1], [c2]]

        from results.views import _load_class_context
        _, _, competitors, _ = _load_class_context(1, 'abc12345')

        assert {c.id for c in competitors} == {1, 2}


# ══════════════════════════════════════════════════════════════════════════════
# _controls_for
# ══════════════════════════════════════════════════════════════════════════════

class TestControlsFor:

    def test_retourne_controls_seq_du_course_si_circuit(self):
        from results.views import _controls_for
        course = {'controls_seq': [{'ctrl_id': 31}]}
        result = _controls_for(cid=1, cls=MagicMock(), course=course)
        assert result == [{'ctrl_id': 31}]

    @patch('results.views.get_class_controls', return_value=([{'ctrl_id': 99}], {}))
    def test_appelle_get_class_controls_si_categorie(self, mock_gcc):
        from results.views import _controls_for
        cls = make_cls(10, 'H21')
        result = _controls_for(cid=1, cls=cls, course=None)
        assert result == [{'ctrl_id': 99}]
        mock_gcc.assert_called_once_with(1, 10)

    @patch('results.views.get_class_controls', return_value=([], {}))
    def test_course_none_utilise_cid_et_cls_id(self, mock_gcc):
        from results.views import _controls_for
        cls = make_cls(42, 'H21')
        _controls_for(cid=7, cls=cls, course=None)
        mock_gcc.assert_called_once_with(7, 42)


# ══════════════════════════════════════════════════════════════════════════════
# class_results — sélection de template selon course
# ══════════════════════════════════════════════════════════════════════════════

class TestClassResultsTemplateSelection:
    """Vérifie le seul branchement de class_results : choix du template."""

    def _run(self, course=None, competitors=None):
        competitors = competitors or [make_competitor(1)]
        competition = MagicMock(); competition.cid = 1
        cls_obj     = make_cls(10, 'abc12345') if course else make_cls(10, 'H21')
        with patch('results.views._load_class_context',
                   return_value=(competition, cls_obj, competitors, course)), \
             patch('results.views.Mopclass') as MockClass, \
             patch('results.views.Mopteam') as MockTeam, \
             patch('results.views.get_org_map', return_value={}), \
             patch('results.views.get_radio_map', return_value={}), \
             patch('results.views.get_class_controls', return_value=([], {})), \
             patch('results.views.compute_splits', return_value=[]), \
             patch('results.views.mark_best_splits'), \
             patch('results.views.rank_splits'), \
             patch('results.views.render') as mock_render:
            MockClass.objects.filter.return_value.order_by.return_value = []
            MockTeam.objects.filter.return_value.exists.return_value = False
            from results.views import class_results
            class_results(rf_get(), cid=1, class_id='abc12345' if course else 'H21')
            _, template, ctx = mock_render.call_args[0]
            return template, ctx

    def test_template_course_results_si_circuit(self):
        course = _make_course()
        template, _ = self._run(course=course)
        assert template == 'results/course_results.html'

    def test_template_class_results_si_categorie(self):
        template, _ = self._run(course=None)
        assert template == 'results/class_results.html'

    def test_course_dans_contexte_si_circuit(self):
        course = _make_course()
        _, ctx = self._run(course=course)
        assert ctx['course'] is course

    def test_course_none_dans_contexte_si_categorie(self):
        _, ctx = self._run(course=None)
        assert ctx['course'] is None

    def test_classement_global_calcule_pour_circuit(self):
        course = _make_course()
        alice  = make_competitor(1, rt=4000, cls=10)
        bob    = make_competitor(2, rt=5000, cls=10)
        _, ctx = self._run(course=course, competitors=[alice, bob])
        ranked = {r.id: r.rank for r in ctx['results'] if r.is_ok}
        assert ranked[1] == 1
        assert ranked[2] == 2

    def test_cat_rank_attribue_en_mode_circuit(self):
        """En mode circuit, cat_rank = rang dans la catégorie d'origine."""
        course = _make_course()
        alice  = make_competitor(1, rt=4000, cls=10)
        bob    = make_competitor(2, rt=5000, cls=10)
        _, ctx = self._run(course=course, competitors=[alice, bob])
        alice_out = next(r for r in ctx['results'] if r.id == 1)
        bob_out   = next(r for r in ctx['results'] if r.id == 2)
        assert alice_out.cat_rank == 1
        assert bob_out.cat_rank   == 2

    def test_pas_de_cat_rank_en_mode_categorie(self):
        def make_competitor_no_cat_rank(id_):
            c = make_competitor(id_)
            if hasattr(c, 'cat_rank'):
                del c.cat_rank
            return c
        competitors = [make_competitor_no_cat_rank(1), make_competitor_no_cat_rank(2)]
        _, ctx = self._run(course=None, competitors=competitors)
        for r in ctx['results']:
            assert not hasattr(r, 'cat_rank') or r.cat_rank is None

    def test_course_hash_dans_contexte_circuit(self):
        course = _make_course('abc12345')
        _, ctx = self._run(course=course)
        assert ctx['course_hash'] == 'abc12345'

    def test_prev_next_none_en_mode_circuit(self):
        course = _make_course()
        _, ctx = self._run(course=course)
        assert ctx['prev_cls'] is None
        assert ctx['next_cls'] is None


# ══════════════════════════════════════════════════════════════════════════════
# Analyses en mode circuit — tests de fumée (smoke tests)
# Les vues utilisent _load_class_context unifié, donc le comportement
# pour les circuits est identique à celui des catégories (déjà testé dans
# test_views.py). On vérifie juste que le contexte `course` est bien transmis.
# ══════════════════════════════════════════════════════════════════════════════

def _run_analysis_view(view_fn, class_id, course, competitors=None):
    """Helper : exécute une vue d'analyse avec un circuit mocké."""
    competitors = competitors or [make_competitor(1, rt=5000), make_competitor(2, rt=6000)]
    competition = MagicMock(); competition.cid = 1
    cls_ns = MagicMock()
    cls_ns.id = class_id; cls_ns.name = class_id
    with patch('results.views._load_class_context',
               return_value=(competition, cls_ns, competitors, course)), \
         patch('results.views.get_org_map',   return_value={}), \
         patch('results.views.get_radio_map', return_value={}), \
         patch('results.views.render') as mock_render:
        view_fn(rf_get(), cid=1, class_id=class_id)
        _, template, ctx = mock_render.call_args[0]
        return template, ctx


class TestAnalysisViewsTransmitCourse:
    """Vérifie que chaque vue d'analyse transmet `course` dans le contexte."""

    def _course(self):
        return _make_course('abc12345')

    def test_superman_transmet_course(self):
        from results.views import superman_analysis
        _, ctx = _run_analysis_view(superman_analysis, 'abc12345', self._course())
        assert ctx['course'] is not None

    def test_superman_no_data_transmet_course(self):
        from results.views import superman_analysis
        dnf = make_competitor(1, rt=-1, stat=STAT_DNF); dnf.is_ok = False
        _, ctx = _run_analysis_view(superman_analysis, 'abc12345', self._course(), [dnf])
        assert ctx['course'] is not None
        assert ctx['no_data'] is True

    def test_performance_transmet_course(self):
        from results.views import performance_analysis
        _, ctx = _run_analysis_view(performance_analysis, 'abc12345', self._course())
        assert ctx['course'] is not None

    def test_regularity_transmet_course(self):
        from results.views import regularity_analysis
        c1 = make_competitor(1, rt=5000); c2 = make_competitor(2, rt=6000)
        _, ctx = _run_analysis_view(regularity_analysis, 'abc12345', self._course(), [c1, c2])
        assert ctx['course'] is not None

    def test_grouping_transmet_course(self):
        from results.views import grouping_analysis
        _, ctx = _run_analysis_view(grouping_analysis, 'abc12345', self._course())
        assert ctx['course'] is not None

    def test_grouping_index_transmet_course(self):
        from results.views import grouping_index_analysis
        c = make_competitor(1, st=100000, rt=50000)
        _, ctx = _run_analysis_view(grouping_index_analysis, 'abc12345', self._course(), [c])
        assert ctx['course'] is not None

    def test_duel_transmet_course(self):
        from results.views import duel_analysis
        with patch('results.views.Mopteam') as MockTeam:
            MockTeam.objects.filter.return_value.exists.return_value = False
            _, ctx = _run_analysis_view(duel_analysis, 'abc12345', self._course())
        assert ctx['course'] is not None

    def test_duel_no_relay_redirect_pour_circuit(self):
        """duel_analysis ne doit PAS rediriger vers relay pour un circuit."""
        from results.views import duel_analysis
        with patch('results.views.Mopteam') as MockTeam, \
             patch('results.views._load_class_context') as mock_lcc, \
             patch('results.views.get_org_map', return_value={}), \
             patch('results.views.get_radio_map', return_value={}), \
             patch('results.views.render') as mock_render, \
             patch('results.views.redirect') as mock_redirect:
            competition = MagicMock()
            cls_ns = MagicMock(); cls_ns.id = 'abc12345'; cls_ns.name = 'abc12345'
            mock_lcc.return_value = (
                competition, cls_ns, [make_competitor(1)], self._course()
            )
            duel_analysis(rf_get(), cid=1, class_id='abc12345')
            mock_redirect.assert_not_called()
            mock_render.assert_called_once()

    def test_class_results_pas_de_relay_redirect_pour_circuit(self):
        """class_results ne redirige pas vers relay pour un circuit."""
        course = self._course()
        competition = MagicMock(); competition.cid = 1
        cls_ns = MagicMock(); cls_ns.id = 'abc12345'; cls_ns.name = 'abc12345'
        with patch('results.views._load_class_context',
                   return_value=(competition, cls_ns, [], course)), \
             patch('results.views.Mopteam') as MockTeam, \
             patch('results.views.get_org_map', return_value={}), \
             patch('results.views.get_radio_map', return_value={}), \
             patch('results.views.render'), \
             patch('results.views.redirect') as mock_redirect:
            # Même si Mopteam existe pour ce cid (ne devrait pas être appelé)
            from results.views import class_results
            class_results(rf_get(), cid=1, class_id='abc12345')
            mock_redirect.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# URLs circuit — même vues, paramètre class_id = hash
# ══════════════════════════════════════════════════════════════════════════════

class TestCourseUrls:

    def test_course_results_url_definie(self):
        from django.urls import reverse
        url = reverse('results:course_results', kwargs={'cid': 1, 'class_id': 'abc12345'})
        assert '/course/abc12345/' in url

    def test_course_superman_url_definie(self):
        from django.urls import reverse
        url = reverse('results:course_superman', kwargs={'cid': 1, 'class_id': 'abc12345'})
        assert 'superman' in url

    def test_course_performance_url_definie(self):
        from django.urls import reverse
        url = reverse('results:course_performance', kwargs={'cid': 1, 'class_id': 'abc12345'})
        assert 'performance' in url

    def test_course_regularity_url_definie(self):
        from django.urls import reverse
        url = reverse('results:course_regularity', kwargs={'cid': 1, 'class_id': 'abc12345'})
        assert 'regularity' in url

    def test_course_grouping_url_definie(self):
        from django.urls import reverse
        url = reverse('results:course_grouping', kwargs={'cid': 1, 'class_id': 'abc12345'})
        assert 'grouping' in url

    def test_course_grouping_index_url_definie(self):
        from django.urls import reverse
        url = reverse('results:course_grouping_index', kwargs={'cid': 1, 'class_id': 'abc12345'})
        assert 'grouping-index' in url

    def test_course_duel_url_definie(self):
        from django.urls import reverse
        url = reverse('results:course_duel', kwargs={'cid': 1, 'class_id': 'abc12345'})
        assert 'duel' in url

    def test_course_urls_pointent_sur_memes_vues_que_class(self):
        """Les URLs /course/ doivent pointer vers les mêmes fonctions que /class/."""
        from results.urls import urlpatterns
        import results.views as v

        pairs = [
            ('class_results',  'course_results',  v.class_results),
            ('superman',       'course_superman',  v.superman_analysis),
            ('performance',    'course_performance', v.performance_analysis),
            ('regularity',     'course_regularity',  v.regularity_analysis),
            ('grouping',       'course_grouping',    v.grouping_analysis),
            ('grouping_index', 'course_grouping_index', v.grouping_index_analysis),
            ('duel',           'course_duel',       v.duel_analysis),
        ]
        url_map = {p.name: p.callback for p in urlpatterns if hasattr(p, 'name')}
        for class_name, course_name, expected_view in pairs:
            assert url_map.get(class_name)  is expected_view, f"{class_name} → mauvaise vue"
            assert url_map.get(course_name) is expected_view, f"{course_name} → mauvaise vue"

    def test_aucune_vue_course_dupliquee_dans_views(self):
        """Il ne doit pas y avoir de fonctions course_* séparées dans views.py."""
        import results.views as v
        for name in ('course_superman_analysis', 'course_performance_analysis',
                     'course_regularity_analysis', 'course_grouping_analysis',
                     'course_grouping_index_analysis', 'course_duel_analysis'):
            assert not hasattr(v, name), f"Fonction dupliquée trouvée : {name}"


# ══════════════════════════════════════════════════════════════════════════════
# competition_detail : courses_map dans le contexte
# ══════════════════════════════════════════════════════════════════════════════

class TestCompetitionDetailCourses:

    def _run(self, courses_map=None):
        competition = MagicMock(); competition.cid = 1
        with patch('results.views.get_object_or_404', return_value=competition), \
             patch('results.views.Mopclass') as MockClass, \
             patch('results.views.Mopteam') as MockTeam, \
             patch('results.views.Mopcompetitor') as MockComp, \
             patch('results.views.get_courses_map',
                   return_value=courses_map or {}) as mock_gcm, \
             patch('results.views.render') as mock_render:
            MockClass.objects.filter.return_value.order_by.return_value = []
            MockTeam.objects.filter.return_value.values_list.return_value.distinct.return_value = []
            comp_qs = MagicMock()
            comp_qs.count.return_value = 0
            comp_qs.filter.return_value.exclude.return_value.count.return_value = 0
            MockComp.objects.filter.return_value = comp_qs
            from results.views import competition_detail
            competition_detail(MagicMock(method='GET'), cid=1)
            _, _, ctx = mock_render.call_args[0]
            return ctx, mock_gcm

    def test_courses_map_present_dans_contexte(self):
        ctx, _ = self._run()
        assert 'courses_map' in ctx

    def test_courses_map_vide_si_aucun_circuit(self):
        ctx, _ = self._run({})
        assert ctx['courses_map'] == {}

    def test_courses_map_transmis_correctement(self):
        cm = {'abc12345': {'hash': 'abc12345', 'display_name': 'H21'}}
        ctx, _ = self._run(cm)
        assert 'abc12345' in ctx['courses_map']

    def test_get_courses_map_appele_avec_cid(self):
        _, mock_gcm = self._run()
        mock_gcm.assert_called_once_with(1)
