"""
Tests unitaires pour l'analyse Indice de performance.

Couvre :
  - services.build_leg_matrix()
  - services.compute_leg_refs()
  - views.performance_analysis() (DB mockée)
"""

from unittest.mock import patch, MagicMock
import pytest
import math

from results.models import STAT_OK


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_competitor(id, rt, stat=STAT_OK, name="Coureur", org=1, cls=10):
    c = MagicMock()
    c.id    = id
    c.rt    = rt
    c.stat  = stat
    c.name  = name
    c.org   = org
    c.cls   = cls
    c.is_ok = (stat == STAT_OK and rt > 0)
    return c


# ─── Tests build_leg_matrix ───────────────────────────────────────────────────

class TestBuildLegMatrix:

    def _call(self, finishers, controls_seq, radio_map):
        from results.services import build_leg_matrix
        return build_leg_matrix(finishers, controls_seq, radio_map)

    def test_troncon_simple(self):
        """Un coureur, un contrôle : leg0 = radio, leg1 = rt - radio."""
        c = make_competitor(1, rt=3000)
        controls = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        radio_map = {1: {31: 1200}}
        matrix = self._call([c], controls, radio_map)
        assert matrix[0][0] == 1200           # tronçon vers P31
        assert matrix[0][1] == 3000 - 1200    # tronçon vers arrivée

    def test_deux_controles(self):
        """leg0 = abs(P31), leg1 = abs(P32) - abs(P31), leg2 = rt - abs(P32)."""
        c = make_competitor(1, rt=5000)
        controls = [
            {'ctrl_id': 31, 'ctrl_name': 'P31'},
            {'ctrl_id': 32, 'ctrl_name': 'P32'},
        ]
        radio_map = {1: {31: 1200, 32: 2800}}
        matrix = self._call([c], controls, radio_map)
        assert matrix[0][0] == 1200
        assert matrix[0][1] == 1600
        assert matrix[0][2] == 2200

    def test_controle_manquant_cascade(self):
        """Si P31 manque, P32 et arrivée sont None."""
        c = make_competitor(1, rt=5000)
        controls = [
            {'ctrl_id': 31, 'ctrl_name': 'P31'},
            {'ctrl_id': 32, 'ctrl_name': 'P32'},
        ]
        radio_map = {1: {32: 2800}}   # P31 absent
        matrix = self._call([c], controls, radio_map)
        assert matrix[0][0] is None
        assert matrix[0][1] is None
        assert matrix[0][2] is None

    def test_plusieurs_coureurs(self):
        c1 = make_competitor(1, rt=5000)
        c2 = make_competitor(2, rt=6000)
        controls  = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        radio_map = {1: {31: 1200}, 2: {31: 1500}}
        matrix = self._call([c1, c2], controls, radio_map)
        assert matrix[0][0] == 1200
        assert matrix[1][0] == 1500

    def test_sans_controles_intermediaires(self):
        """Pas de contrôles radio → une seule colonne = rt."""
        c = make_competitor(1, rt=5000)
        matrix = self._call([c], [], {1: {}})
        assert len(matrix[0]) == 1
        assert matrix[0][0] == 5000

    def test_coureur_sans_radio(self):
        """Coureur sans aucun temps radio → tous None sauf arrivée."""
        c = make_competitor(1, rt=5000)
        controls  = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        matrix = self._call([c], controls, {})
        assert matrix[0][0] is None   # P31 manquant
        assert matrix[0][1] is None   # arrivée non calculable

    def test_liste_vide(self):
        matrix = self._call([], [], {})
        assert matrix == []


# ─── Tests compute_leg_refs ───────────────────────────────────────────────────

class TestComputeLegRefs:

    def _call(self, leg_matrix, n_legs, top_fraction=0.25):
        from results.services import compute_leg_refs
        return compute_leg_refs(leg_matrix, n_legs, top_fraction)

    def test_top25_quatre_coureurs(self):
        """Avec 4 coureurs, top 25% = le meilleur (ceil(4*0.25)=1)."""
        matrix = [[1000], [1200], [1400], [1600]]
        refs = self._call(matrix, n_legs=1)
        assert refs[0] == 1000.0

    def test_top25_huit_coureurs(self):
        """Avec 8 coureurs, top 25% = moyenne des 2 meilleurs."""
        matrix = [[t] for t in [1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700]]
        refs = self._call(matrix, n_legs=1)
        assert refs[0] == pytest.approx((1000 + 1100) / 2)

    def test_top50_explicite(self):
        """top_fraction=0.5 : moyenne des 50% meilleurs."""
        matrix = [[1000], [1200], [1400], [1600]]
        refs = self._call(matrix, n_legs=1, top_fraction=0.5)
        assert refs[0] == pytest.approx((1000 + 1200) / 2)

    def test_valeurs_none_ignorees(self):
        """Les None ne participent pas au calcul."""
        matrix = [[None], [1000], [1200], [1400]]
        refs = self._call(matrix, n_legs=1)
        assert refs[0] == 1000.0   # seul le meilleur non-None

    def test_toutes_none(self):
        """Si tous les temps d'un tronçon sont None → ref = None."""
        matrix = [[None], [None]]
        refs = self._call(matrix, n_legs=1)
        assert refs[0] is None

    def test_plusieurs_troncons(self):
        """Chaque tronçon est calculé indépendamment."""
        matrix = [
            [1000, 2000],
            [1200, 1800],
            [1400, 2200],
            [1600, 2400],
        ]
        refs = self._call(matrix, n_legs=2)
        assert refs[0] == 1000.0   # top 25% tronçon 0
        assert refs[1] == 1800.0   # top 25% tronçon 1 : ceil(4*0.25)=1 → meilleur = 1800

    def test_minimum_un_coureur(self):
        """Avec 1 seul coureur, la ref = son temps."""
        matrix = [[1234]]
        refs = self._call(matrix, n_legs=1)
        assert refs[0] == 1234.0


# ─── Tests performance_analysis (vue) ────────────────────────────────────────

class TestPerformanceAnalysisView:

    def _get(self, url='/'):
        from django.test import RequestFactory
        return RequestFactory().get(url)

    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_no_data_si_aucun_classe(self, MockCompetitor, mock_get404, mock_render):
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock_get404.side_effect = [competition, cls]
        dnf = make_competitor(1, rt=-1, stat=4)
        dnf.is_ok = False
        MockCompetitor.objects.filter.return_value = [dnf]

        from results.views import performance_analysis
        performance_analysis(self._get(), cid=1, class_id=10)

        _, template, context = mock_render.call_args[0]
        assert template == 'results/performance.html'
        assert context['no_data'] is True

    @patch('results.views.get_org_map',         return_value={1: 'COLE'})
    @patch('results.views.get_class_controls',  return_value=(
        [{'ctrl_id': 31, 'ctrl_name': 'P31'}], {}
    ))
    @patch('results.views.get_radio_map',       return_value={
        1: {31: 1200}, 2: {31: 1100}
    })
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_contexte_complet(
        self, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock_get404.side_effect = [competition, cls]
        c1 = make_competitor(1, rt=3000, name='Alice', org=1)
        c2 = make_competitor(2, rt=3600, name='Bob',   org=1)
        MockCompetitor.objects.filter.return_value = [c1, c2]

        from results.views import performance_analysis
        performance_analysis(self._get(), cid=1, class_id=10)

        _, template, context = mock_render.call_args[0]
        assert template == 'results/performance.html'
        assert context['no_data'] is False
        assert context['n_finishers'] == 2
        assert context['n_legs'] == 2       # 1 contrôle + arrivée
        assert 'series_json' in context
        assert 'leg_info_json' in context

    @patch('results.views.get_org_map',         return_value={1: 'COLE'})
    @patch('results.views.get_class_controls',  return_value=(
        [{'ctrl_id': 31, 'ctrl_name': 'P31'}], {}
    ))
    @patch('results.views.get_radio_map',       return_value={
        1: {31: 1200}, 2: {31: 1100}
    })
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_series_contient_indices(
        self, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """Vérifie que chaque série contient bien les champs attendus."""
        import json
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock_get404.side_effect = [competition, cls]
        c1 = make_competitor(1, rt=3000, name='Alice')
        c2 = make_competitor(2, rt=3600, name='Bob')
        MockCompetitor.objects.filter.return_value = [c1, c2]

        from results.views import performance_analysis
        performance_analysis(self._get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        series = json.loads(context['series_json'])

        assert len(series) == 2
        for s in series:
            assert 'id'      in s
            assert 'name'    in s
            assert 'rank'    in s
            assert 'indices' in s
            assert 'weights' in s
            assert 'mean_pi' in s
            assert 'std_pi'  in s
            assert len(s['indices']) == 2   # 1 ctrl + arrivée
            assert len(s['weights']) == 2

    @patch('results.views.get_org_map',         return_value={})
    @patch('results.views.get_class_controls',  return_value=(
        [{'ctrl_id': 31, 'ctrl_name': 'P31'}], {}
    ))
    @patch('results.views.get_radio_map',       return_value={
        1: {31: 1100}, 2: {31: 1200}, 3: {31: 1300}, 4: {31: 1400}
    })
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_indice_top25_correct(
        self, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """Avec 4 coureurs, ref = meilleur temps. IP du 1er ≈ 1.0."""
        import json
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock_get404.side_effect = [competition, cls]

        # rt=2000 pour tous → leg arrivée = rt - radio
        coureurs = [
            make_competitor(1, rt=2000, name='A'),  # P31=1100 → arrivée=900
            make_competitor(2, rt=2200, name='B'),  # P31=1200
            make_competitor(3, rt=2400, name='C'),  # P31=1300
            make_competitor(4, rt=2600, name='D'),  # P31=1400
        ]
        MockCompetitor.objects.filter.return_value = coureurs

        from results.views import performance_analysis
        performance_analysis(self._get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        series = json.loads(context['series_json'])

        # Le 1er coureur (Alice, P31=1100) doit avoir IP[0] ≈ 1.0
        # car ref = top 25% = meilleur = 1100, et son temps = 1100
        alice = next(s for s in series if s['name'] == 'A')
        assert alice['indices'][0] == pytest.approx(1.0, abs=1e-4)

        # Le 4e coureur (P31=1400) doit avoir IP[0] < 1.0
        denis = next(s for s in series if s['name'] == 'D')
        assert denis['indices'][0] < 1.0

    @patch('results.views.get_org_map',         return_value={})
    @patch('results.views.get_class_controls',  return_value=([], {}))
    @patch('results.views.get_radio_map',       return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_sans_controles_intermediaires(
        self, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """Fonctionne même sans contrôles radio (1 seul tronçon = arrivée)."""
        import json
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock_get404.side_effect = [competition, cls]

        c1 = make_competitor(1, rt=5000)
        c2 = make_competitor(2, rt=6000)
        MockCompetitor.objects.filter.return_value = [c1, c2]

        from results.views import performance_analysis
        performance_analysis(self._get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        assert context['no_data'] is False
        assert context['n_legs'] == 1

        series = json.loads(context['series_json'])
        # Un seul tronçon (arrivée), le 1er doit avoir IP ≈ 1.0
        assert series[0]['indices'][0] == pytest.approx(1.0, abs=1e-4)
