"""
Tests unitaires — analyses pendant la course (coureurs OK uniquement).

Les analyses ne sont plus bloquées pendant la course : elles se calculent dès
les premières arrivées en ne prenant en compte QUE les coureurs ayant un
statut OK (stat = 1, rt > 0). Les coureurs encore en course (stat = 0), non
partis (st = 0) ou avec un statut non-OK (DNF, DNS, …) n'apparaissent pas.

Tant que la course est en cours (``race_in_progress``), les vues posent
``partial_analysis=True`` avec les compteurs ``n_ok`` / ``n_total`` pour le
bandeau « analyse partielle ».

Couvre :
  - les 7 vues d'analyse : calculées même quand un coureur parti est sans
    statut, avec ``partial_analysis=True`` (catégorie et circuit)
  - exclusion des non-OK (grouping, grouping_index, duel, recapitulatif)
  - recapitulatif_csv : export 200 pendant la course, lignes OK uniquement
  - rendu des templates : bandeau partiel, plus de message de blocage
"""

from unittest.mock import patch, MagicMock
import pytest

from django.test import RequestFactory

from results.models import STAT_OK, STAT_UNKNOWN, STAT_DNF
from results import views


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_competitor(id, *, st=1, stat=STAT_UNKNOWN, rt=0, is_ok=None):
    """Construit un MagicMock représentant un Mopcompetitor."""
    c = MagicMock()
    c.id    = id
    c.name  = f'Coureur {id}'
    c.org   = 1
    c.st    = st
    c.stat  = stat
    c.rt    = rt
    c.rank  = None
    c.is_ok = (stat == STAT_OK and rt > 0) if is_ok is None else is_ok
    return c


def _get(url='/'):
    return RequestFactory().get(url)


# Départ toujours dans le passé (1 s après minuit)
ST_PASSE = 10

# Services de calcul appelés par chaque vue d'analyse
VIEW_SERVICES = {
    'superman_analysis':       ['rank_finishers', 'get_org_map', 'get_class_controls',
                                'get_radio_map', 'build_leg_matrix'],
    'performance_analysis':    ['rank_finishers', 'get_org_map', 'get_class_controls',
                                'get_radio_map', 'build_leg_matrix', 'compute_leg_refs'],
    'regularity_analysis':     ['rank_finishers', 'get_org_map', 'get_class_controls',
                                'get_radio_map', 'compute_regularity_analysis'],
    'grouping_analysis':       ['rank_finishers', 'get_org_map', 'get_class_controls',
                                'get_radio_map', 'build_abs_time_series'],
    'grouping_index_analysis': ['rank_finishers', 'get_org_map', 'get_class_controls',
                                'get_radio_map', 'compute_grouping_index'],
    'duel_analysis':           ['rank_finishers', 'get_org_map', 'get_class_controls',
                                'get_radio_map', 'compute_splits', 'get_negative_time_stats'],
    'recapitulatif_analysis':  ['_load_recapitulatif_data'],
}

ANALYSIS_VIEWS = [
    pytest.param(views.superman_analysis,       'superman',       id='superman'),
    pytest.param(views.performance_analysis,    'performance',    id='performance'),
    pytest.param(views.regularity_analysis,     'regularity',     id='regularity'),
    pytest.param(views.grouping_analysis,       'grouping',       id='grouping'),
    pytest.param(views.grouping_index_analysis, 'grouping_index', id='grouping_index'),
    pytest.param(views.duel_analysis,           'duel',           id='duel'),
    pytest.param(views.recapitulatif_analysis,  'recapitulatif',  id='recapitulatif'),
]


class _ViewRunner:
    """Exécute une vue d'analyse avec tous ses services mockés."""

    def __init__(self, view_fn, competitors=None, course=None):
        self.view_fn    = view_fn
        self.competition = MagicMock(); self.competition.cid = 1
        self.cls        = MagicMock(); self.cls.id = 10; self.cls.name = 'H21'
        self.ok         = None
        self._competitors = competitors
        self._course      = course
        self.rank_override = None
        self.entered    = False

    def __enter__(self):
        names = VIEW_SERVICES[self.view_fn.__name__]
        self._patches = [patch(f'results.views.{n}') for n in names]
        self.mocks = {n: p.start() for n, p in zip(names, self._patches)}
        self.patch_ctx  = patch('results.views._load_class_context',
                                return_value=(self.competition, self.cls,
                                              self._competitors, self._course))
        self.mock_ctx   = self.patch_ctx.start()
        self.patch_team = patch('results.views.Mopteam')
        self.mock_team  = self.patch_team.start()
        self.mock_team.objects.filter.return_value.exists.return_value = False
        self.patch_render = patch('results.views.render')
        self.mock_render  = self.patch_render.start()
        self.entered = True

        if 'rank_finishers' in self.mocks:
            if self.rank_override is not None:
                self.mocks['rank_finishers'].return_value = self.rank_override
            else:
                self.mocks['rank_finishers'].return_value = (
                    [self.ok, make_competitor(98, st=ST_PASSE, stat=STAT_OK, rt=5200)],
                    [], 5000)
        if 'get_org_map' in self.mocks:
            self.mocks['get_org_map'].return_value = {}
        if 'get_class_controls' in self.mocks:
            self.mocks['get_class_controls'].return_value = ([], {})
        if 'get_radio_map' in self.mocks:
            self.mocks['get_radio_map'].return_value = {}
        if 'build_leg_matrix' in self.mocks:
            self.mocks['build_leg_matrix'].return_value = [[500], [600]]
        if 'compute_leg_refs' in self.mocks:
            self.mocks['compute_leg_refs'].return_value = [1000]
        if 'compute_regularity_analysis' in self.mocks:
            self.mocks['compute_regularity_analysis'].return_value = {
                'runner_regularity': [
                    {'weighted_std': 1.0, 'mean_pi': 1.0,
                     'leg_pis': [1.0], 'leg_weights': [1000]},
                    {'weighted_std': 1.2, 'mean_pi': 1.1,
                     'leg_pis': [1.1], 'leg_weights': [1000]},
                ],
                'leg_refs': [1000], 'leg_stds': [0.5], 'n_legs': 1,
                'category_regularity': 0.5,
            }
        if 'build_abs_time_series' in self.mocks:
            self.mocks['build_abs_time_series'].return_value = []
        if 'compute_grouping_index' in self.mocks:
            self.mocks['compute_grouping_index'].return_value = []
        if 'compute_splits' in self.mocks:
            self.mocks['compute_splits'].return_value = []
        if 'get_negative_time_stats' in self.mocks:
            self.mocks['get_negative_time_stats'].return_value = {}
        if '_load_recapitulatif_data' in self.mocks:
            self.mocks['_load_recapitulatif_data'].return_value = \
                ([], [], [], [], [], None, None, None, [])
        return self

    def __exit__(self, *exc):
        self.patch_render.stop()
        self.patch_team.stop()
        self.patch_ctx.stop()
        for p in self._patches:
            p.stop()
        return False

    def run(self, competitors=None, course=None):
        if competitors is not None:
            self._competitors = competitors
        if course is not None:
            self._course = course
        self.ok = next((c for c in self._competitors if c.is_ok),
                       make_competitor(99, st=ST_PASSE, stat=STAT_OK, rt=5000))
        with self:
            self.view_fn(_get(), cid=1, class_id=10)
            _, template, ctx = self.mock_render.call_args[0]
        return template, ctx


# ─── Vues calculées pendant la course (plus de blocage) ──────────────────────

class TestAnalysisViewsDuringRace:

    @pytest.mark.parametrize('view_fn,analysis_key', ANALYSIS_VIEWS)
    def test_calculee_meme_si_coureur_en_course(self, view_fn, analysis_key):
        """Un coureur parti sans statut ne bloque plus l'analyse."""
        en_course = make_competitor(1, st=ST_PASSE, stat=STAT_UNKNOWN)
        ok        = make_competitor(2, st=ST_PASSE, stat=STAT_OK, rt=5000)
        runner = _ViewRunner(view_fn)
        tpl, ctx = runner.run([en_course, ok])
        assert ctx['partial_analysis'] is True
        assert ctx['n_ok'] == 1
        assert ctx['n_total'] == 2
        assert ctx.get('analysis_locked') is not True
        assert ctx.get('no_data') is not True
        assert ctx['current_analysis'] == analysis_key
        # Le calcul est bien lancé (plus aucun blocage)
        if 'rank_finishers' in VIEW_SERVICES[view_fn.__name__]:
            runner.mocks['rank_finishers'].assert_called()

    @pytest.mark.parametrize('view_fn,analysis_key', ANALYSIS_VIEWS)
    def test_partiel_en_course_mode_circuit(self, view_fn, analysis_key):
        """Même comportement en mode circuit (hash)."""
        en_course = make_competitor(1, st=ST_PASSE, stat=STAT_UNKNOWN)
        ok        = make_competitor(2, st=ST_PASSE, stat=STAT_OK, rt=5000)
        course    = {'hash': 'abc12345', 'controls_seq': [], 'classes': [],
                     'display_name': 'H21'}
        runner = _ViewRunner(view_fn)
        tpl, ctx = runner.run([en_course, ok], course=course)
        assert ctx['partial_analysis'] is True
        assert ctx['n_ok'] == 1
        assert ctx['n_total'] == 2
        assert ctx['course'] is course

    @pytest.mark.parametrize('view_fn,analysis_key', ANALYSIS_VIEWS)
    def test_plus_de_partiel_course_finie(self, view_fn, analysis_key):
        """Tous les coureurs ont un statut définitif → pas de bandeau partiel."""
        ok  = make_competitor(1, st=ST_PASSE, stat=STAT_OK, rt=5000)
        dnf = make_competitor(2, st=ST_PASSE, stat=STAT_DNF)
        runner = _ViewRunner(view_fn)
        tpl, ctx = runner.run([ok, dnf])
        assert ctx['partial_analysis'] is False
        assert ctx['n_ok'] == 1
        assert ctx['n_total'] == 2


# ─── Exclusion des coureurs non-OK ───────────────────────────────────────────

class TestExclusionNonOk:

    def test_grouping_exclut_les_coureurs_en_course(self):
        """Regroupement : seuls les OK passent à build_abs_time_series."""
        en_course = make_competitor(1, st=ST_PASSE, stat=STAT_UNKNOWN)
        ok        = make_competitor(2, st=ST_PASSE, stat=STAT_OK, rt=5000)
        runner = _ViewRunner(views.grouping_analysis)
        _, ctx = runner.run([en_course, ok])
        sent = runner.mocks['build_abs_time_series'].call_args[0][0]
        assert [c.id for c in sent] == [2]
        assert ctx['n_runners'] == 0  # série mockée vide

    def test_grouping_index_exclut_les_coureurs_en_course(self):
        """Lièvre / Suiveur : seuls les OK passent à compute_grouping_index."""
        en_course = make_competitor(1, st=ST_PASSE, stat=STAT_UNKNOWN)
        ok        = make_competitor(2, st=ST_PASSE, stat=STAT_OK, rt=5000)
        runner = _ViewRunner(views.grouping_index_analysis)
        _, ctx = runner.run([en_course, ok])
        sent = runner.mocks['compute_grouping_index'].call_args[0][0]
        assert [c.id for c in sent] == [2]

    def test_grouping_n_donnees_sans_ok(self):
        """Regroupement : aucun coureur OK → no_data."""
        en_course = make_competitor(1, st=ST_PASSE, stat=STAT_UNKNOWN)
        dnf       = make_competitor(2, st=ST_PASSE, stat=STAT_DNF)
        runner = _ViewRunner(views.grouping_analysis)
        _, ctx = runner.run([en_course, dnf])
        assert ctx['no_data'] is True

    def test_duel_exclut_les_non_finishers(self):
        """Duel : seuls les finishers (OK) sont comparés, pas les non-OK."""
        en_course = make_competitor(1, st=ST_PASSE, stat=STAT_UNKNOWN)
        dnf       = make_competitor(3, st=ST_PASSE, stat=STAT_DNF)
        ok        = make_competitor(2, st=ST_PASSE, stat=STAT_OK, rt=5000)
        runner = _ViewRunner(views.duel_analysis)
        # rank_finishers renvoie le peloton OK d'un côté, non-OK de l'autre :
        # la vue ne doit utiliser que les finishers.
        runner.rank_override = ([ok], [dnf, en_course], 5000)
        _, ctx = runner.run([en_course, dnf, ok])
        assert ctx['n_runners'] == 1
        assert runner.mocks['compute_splits'].call_count == 1
        assert runner.mocks['compute_splits'].call_args[0][0] == 2

    def test_recapitulatif_exclut_les_non_finishers(self):
        """Récapitulatif : seuls les finishers (OK) sont dans le tableau."""
        en_course = make_competitor(1, st=ST_PASSE, stat=STAT_UNKNOWN)
        dnf       = make_competitor(3, st=ST_PASSE, stat=STAT_DNF)
        ok        = make_competitor(2, st=ST_PASSE, stat=STAT_OK, rt=5000)
        with patch('results.views._load_class_context',
                   return_value=(MagicMock(), MagicMock(),
                                 [en_course, dnf, ok], None)), \
             patch('results.views.Mopteam'), \
             patch('results.views.get_org_map', return_value={}), \
             patch('results.views.get_class_controls', return_value=([], {})), \
             patch('results.views.get_radio_map', return_value={}), \
             patch('results.views.rank_finishers',
                   return_value=([ok], [dnf, en_course], 5000)), \
             patch('results.views._get_adjacent_classes', return_value=(None, None)), \
             patch('results.views.compute_splits', return_value=[]), \
             patch('results.views.mark_best_splits'), \
             patch('results.views.rank_splits'), \
             patch('results.views.compute_error_estimates', return_value={}):
            competition, cls, course, results, controls_seq, prev_cls, next_cls, \
                leader_time, leg_error_data = views._load_recapitulatif_data(1, 10)
        assert [c.id for c in results] == [2]
        assert [c.id for c in leg_error_data] == []  # pas d'erreurs sans peloton
        assert leader_time == 5000


# ─── Rendu des templates : bandeau partiel ───────────────────────────────────

class TestPartialTemplates:
    """Les 7 pages d'analyse affichent le bandeau « analyse partielle »."""

    @pytest.mark.parametrize('template', [
        'results/superman.html',
        'results/performance.html',
        'results/regularity.html',
        'results/grouping.html',
        'results/grouping_index.html',
        'results/duel.html',
        'results/recapitulatif.html',
    ])
    def test_bandeau_partiel_affiche(self, template):
        from types import SimpleNamespace
        from django.template.loader import render_to_string
        ctx = {
            'competition':      SimpleNamespace(cid=1, name='Test', date=None),
            'cls':              SimpleNamespace(id=10, name='H21', cid=1),
            'course':           None,
            'current_analysis': 'x',
            'partial_analysis': True,
            'n_ok':             1,
            'n_total':          5,
            'no_data':          True,
        }
        html = render_to_string(template, ctx)
        assert 'Analyse partielle' in html
        assert '1 coureur arrivé sur 5' in html
        assert 'Analyse indisponible pendant la course' not in html

    def test_pas_de_bandeau_sans_course_en_cours(self):
        """Course terminée (pas de partiel) → pas de bandeau."""
        from types import SimpleNamespace
        from django.template.loader import render_to_string
        ctx = {
            'competition':      SimpleNamespace(cid=1, name='Test', date=None),
            'cls':              SimpleNamespace(id=10, name='H21', cid=1),
            'course':           None,
            'current_analysis': 'regularity',
            'partial_analysis': False,
            'n_ok':             2,
            'n_total':          2,
            'no_data':          True,
        }
        html = render_to_string('results/regularity.html', ctx)
        assert 'Analyse partielle' not in html
        assert 'minimum 2 requis' in html


# ─── Export CSV du récapitulatif ─────────────────────────────────────────────

class TestRecapitulatifCsv:

    def test_csv_200_pendant_course_ok_uniquement(self):
        """Course en cours → export CSV disponible, lignes OK uniquement."""
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10; cls.name = 'H21'
        en_course = make_competitor(1, st=ST_PASSE, stat=STAT_UNKNOWN)
        ok        = make_competitor(2, st=ST_PASSE, stat=STAT_OK, rt=5000)
        with patch('results.views._load_class_context',
                   return_value=(competition, cls, [en_course, ok], None)), \
             patch('results.views.Mopteam') as MockTeam, \
             patch('results.views.get_org_map', return_value={}), \
             patch('results.views.get_class_controls', return_value=([], {})), \
             patch('results.views.get_radio_map', return_value={}), \
             patch('results.views.rank_finishers',
                   return_value=([ok], [en_course], 5000)), \
             patch('results.views._get_adjacent_classes', return_value=(None, None)), \
             patch('results.views.compute_splits', return_value=[]), \
             patch('results.views.mark_best_splits'), \
             patch('results.views.rank_splits'), \
             patch('results.views.compute_error_estimates', return_value={}):
            MockTeam.objects.filter.return_value.exists.return_value = False
            resp = views.recapitulatif_csv(_get(), cid=1, class_id=10)
        assert resp.status_code == 200
        assert 'text/csv' in resp['Content-Type']
        body = resp.content.decode('utf-8')
        assert 'Coureur 2' in body
        assert 'Coureur 1' not in body

    def test_csv_200_course_finie(self):
        """Course terminée → export CSV normal (tous les OK)."""
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10; cls.name = 'H21'
        ok1 = make_competitor(1, st=ST_PASSE, stat=STAT_OK, rt=5000)
        ok2 = make_competitor(2, st=ST_PASSE, stat=STAT_OK, rt=5200)
        with patch('results.views._load_class_context',
                   return_value=(competition, cls, [ok1, ok2], None)), \
             patch('results.views.Mopteam') as MockTeam, \
             patch('results.views.get_org_map', return_value={}), \
             patch('results.views.get_class_controls', return_value=([], {})), \
             patch('results.views.get_radio_map', return_value={}), \
             patch('results.views.rank_finishers',
                   return_value=([ok1, ok2], [], 5000)), \
             patch('results.views._get_adjacent_classes', return_value=(None, None)), \
             patch('results.views.compute_splits', return_value=[]), \
             patch('results.views.mark_best_splits'), \
             patch('results.views.rank_splits'), \
             patch('results.views.compute_error_estimates', return_value={}):
            MockTeam.objects.filter.return_value.exists.return_value = False
            resp = views.recapitulatif_csv(_get(), cid=1, class_id=10)
        assert resp.status_code == 200
        body = resp.content.decode('utf-8')
        assert 'Coureur 1' in body
        assert 'Coureur 2' in body