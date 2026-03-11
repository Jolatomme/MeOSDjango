"""
Tests unitaires pour l'analyse Regroupement des coureurs.

Couvre :
  - services.build_abs_time_series()
  - views.grouping_analysis()
"""

from unittest.mock import patch, MagicMock
import pytest
import json

from results.models import STAT_OK

STAT_MP  = 3
STAT_DNF = 4


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_runner(id, st, rt, stat=STAT_OK, name='Coureur', org=1):
    """Construit un MagicMock représentant un Mopcompetitor."""
    c      = MagicMock()
    c.id   = id
    c.st   = st
    c.rt   = rt
    c.stat = stat
    c.name = name
    c.org  = org
    c.is_ok = (stat == STAT_OK and rt > 0)
    return c


# ─── Tests build_abs_time_series ──────────────────────────────────────────────

class TestBuildAbsTimeSeries:

    def _call(self, runners, controls_seq, radio_map):
        from results.services import build_abs_time_series
        return build_abs_time_series(runners, controls_seq, radio_map)

    def test_sans_controles_intermediaires(self):
        """Pas de contrôle → 2 points : départ et arrivée."""
        c = make_runner(1, st=100000, rt=50000)
        series = self._call([c], [], {})
        assert len(series) == 1
        s = series[0]
        assert s['points'][0] == 100000           # départ absolu
        assert s['points'][1] == 100000 + 50000   # arrivée absolue
        assert len(s['points']) == 2

    def test_un_controle(self):
        """Un contrôle radio → 3 points : départ, poste, arrivée."""
        c  = make_runner(1, st=100000, rt=60000)
        cs = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        rm = {1: {31: 20000}}   # passage à P31 = 20000 dixièmes après le départ

        series = self._call([c], cs, rm)
        s = series[0]
        assert s['points'][0] == 100000           # départ
        assert s['points'][1] == 100000 + 20000   # P31 absolu
        assert s['points'][2] == 100000 + 60000   # arrivée absolue

    def test_deux_controles(self):
        """Deux contrôles → 4 points."""
        c  = make_runner(1, st=100000, rt=90000)
        cs = [
            {'ctrl_id': 31, 'ctrl_name': 'P31'},
            {'ctrl_id': 32, 'ctrl_name': 'P32'},
        ]
        rm = {1: {31: 20000, 32: 50000}}

        series = self._call([c], cs, rm)
        s = series[0]
        assert len(s['points']) == 4
        assert s['points'][0] == 100000
        assert s['points'][1] == 120000
        assert s['points'][2] == 150000
        assert s['points'][3] == 190000

    def test_poste_manquant_donne_none(self):
        """Si un radio est manquant → None uniquement pour ce poste."""
        c  = make_runner(1, st=100000, rt=90000)
        cs = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        rm = {1: {}}   # P31 absent du radio_map

        series = self._call([c], cs, rm)
        s = series[0]
        assert s['points'][1] is None             # P31 manquant → None
        assert s['points'][2] == 100000 + 90000   # arrivée calculable

    def test_poste_manquant_ne_cascade_pas(self):
        """build_abs_time_series calcule chaque poste indépendamment
        (≠ build_leg_matrix qui cascade les None pour les tronçons).
        P32 peut être connu même si P31 manque."""
        c  = make_runner(1, st=100000, rt=90000)
        cs = [
            {'ctrl_id': 31, 'ctrl_name': 'P31'},
            {'ctrl_id': 32, 'ctrl_name': 'P32'},
        ]
        rm = {1: {32: 50000}}   # P31 manquant, P32 connu

        series = self._call([c], cs, rm)
        s = series[0]
        assert s['points'][1] is None             # P31 manquant → None
        assert s['points'][2] == 100000 + 50000   # P32 calculable

    def test_coureur_sans_heure_depart_exclu(self):
        """Un coureur avec st=0 est exclu de la série."""
        c_avec    = make_runner(1, st=100000, rt=50000)
        c_sans_st = make_runner(2, st=0, rt=50000)

        series = self._call([c_avec, c_sans_st], [], {})
        ids = [s['id'] for s in series]
        assert 1 in ids
        assert 2 not in ids

    def test_dnf_inclus_avec_flag(self):
        """Un coureur DNF avec st > 0 est inclus, has_finish=False."""
        c = make_runner(1, st=100000, rt=-1, stat=STAT_DNF)

        series = self._call([c], [], {})
        assert len(series) == 1
        s = series[0]
        assert s['has_finish'] is False
        assert s['points'][-1] is None

    def test_classé_has_finish_true(self):
        """Un coureur classé a has_finish=True et le dernier point est non None."""
        c = make_runner(1, st=100000, rt=50000)
        series = self._call([c], [], {})
        s = series[0]
        assert s['has_finish'] is True
        assert s['points'][-1] == 150000

    def test_champs_presents(self):
        """Tous les champs attendus sont présents dans chaque série."""
        c = make_runner(1, st=100000, rt=50000, name='Alice')
        series = self._call([c], [], {})
        s = series[0]
        for field in ('id', 'name', 'rank', 'time', 'st_abs', 'points', 'has_finish'):
            assert field in s, f"champ '{field}' manquant"

    def test_rang_attribue_correctement(self):
        """Le rank reflète l'ordre dans la liste reçue."""
        c1 = make_runner(1, st=100000, rt=50000, name='Alice')
        c2 = make_runner(2, st=200000, rt=60000, name='Bob')
        series = self._call([c1, c2], [], {})
        assert series[0]['rank'] == 1
        assert series[1]['rank'] == 2

    def test_plusieurs_coureurs_departs_differents(self):
        """Deux coureurs avec des départs différents → abs_time différents même
        pour le même temps de course."""
        c1 = make_runner(1, st=100000, rt=50000)   # part à 100000
        c2 = make_runner(2, st=200000, rt=50000)   # part à 200000, même rt
        cs = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        rm = {1: {31: 20000}, 2: {31: 20000}}

        series = self._call([c1, c2], cs, rm)
        # P31 absolu : c1=120000, c2=220000 — différents malgré même temps de course
        assert series[0]['points'][1] == 120000
        assert series[1]['points'][1] == 220000

    def test_liste_vide(self):
        series = self._call([], [], {})
        assert series == []

    def test_st_absolu_stocke(self):
        """st_abs doit contenir l'heure de départ absolue brute (dixièmes)."""
        c = make_runner(1, st=370800, rt=71480)
        series = self._call([c], [], {})
        assert series[0]['st_abs'] == 370800


# ─── Tests grouping_analysis (vue) ───────────────────────────────────────────

class TestGroupingAnalysisView:

    def _get(self, url='/'):
        from django.test import RequestFactory
        return RequestFactory().get(url)

    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_no_data_si_aucun_depart(self, MockCompetitor, mock_get404, mock_render):
        """Si aucun coureur n'a d'heure de départ → no_data=True."""
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock_get404.side_effect = [competition, cls]

        # Coureur sans heure de départ
        c = make_runner(1, st=0, rt=50000)
        MockCompetitor.objects.filter.return_value = [c]

        from results.views import grouping_analysis
        grouping_analysis(self._get(), cid=1, class_id=10)

        _, template, context = mock_render.call_args[0]
        assert template == 'results/grouping.html'
        assert context['no_data'] is True

    @patch('results.views.get_org_map',        return_value={1: 'COLE'})
    @patch('results.views.get_class_controls', return_value=(
        [{'ctrl_id': 31, 'ctrl_name': 'P31'}], {}
    ))
    @patch('results.views.get_radio_map', return_value={
        1: {31: 20000}, 2: {31: 22000}
    })
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_contexte_complet(
        self, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """Vérifie les clés présentes dans le contexte."""
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock_get404.side_effect = [competition, cls]

        c1 = make_runner(1, st=100000, rt=60000, name='Alice', org=1)
        c2 = make_runner(2, st=110000, rt=70000, name='Bob',   org=1)
        MockCompetitor.objects.filter.return_value = [c1, c2]

        from results.views import grouping_analysis
        grouping_analysis(self._get(), cid=1, class_id=10)

        _, template, context = mock_render.call_args[0]
        assert template == 'results/grouping.html'
        assert context['no_data'] is False
        assert context['n_runners'] == 2
        assert context['n_controls'] == 1
        assert 'series_json' in context
        assert 'x_labels_json' in context

    @patch('results.views.get_org_map',        return_value={1: 'COLE'})
    @patch('results.views.get_class_controls', return_value=(
        [{'ctrl_id': 31, 'ctrl_name': 'P31'}], {}
    ))
    @patch('results.views.get_radio_map', return_value={1: {31: 20000}})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_series_json_bien_forme(
        self, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """Vérifie la structure JSON des séries."""
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock_get404.side_effect = [competition, cls]

        c1 = make_runner(1, st=100000, rt=60000, name='Alice')
        MockCompetitor.objects.filter.return_value = [c1]

        from results.views import grouping_analysis
        grouping_analysis(self._get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        series = json.loads(context['series_json'])

        assert len(series) == 1
        s = series[0]
        assert s['name'] == 'Alice'
        assert s['org']  == 'COLE'
        # points : départ + P31 + arrivée = 3 points
        assert len(s['points']) == 3
        assert s['points'][0] == 100000            # départ absolu
        assert s['points'][1] == 100000 + 20000    # P31 absolu
        assert s['points'][2] == 100000 + 60000    # arrivée absolue

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_x_labels_corrects(
        self, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """Sans contrôle radio → x_labels = ['Départ', 'Arrivée']."""
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock_get404.side_effect = [competition, cls]

        c = make_runner(1, st=100000, rt=50000)
        MockCompetitor.objects.filter.return_value = [c]

        from results.views import grouping_analysis
        grouping_analysis(self._get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        x_labels = json.loads(context['x_labels_json'])
        assert x_labels == ['Départ', 'Arrivée']

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=(
        [{'ctrl_id': 31, 'ctrl_name': 'Crête'},
         {'ctrl_id': 32, 'ctrl_name': 'Lac'}], {}
    ))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_x_labels_avec_controles(
        self, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """Avec 2 contrôles → x_labels = ['Départ', 'Crête', 'Lac', 'Arrivée']."""
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock_get404.side_effect = [competition, cls]

        c = make_runner(1, st=100000, rt=50000)
        MockCompetitor.objects.filter.return_value = [c]

        from results.views import grouping_analysis
        grouping_analysis(self._get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        x_labels = json.loads(context['x_labels_json'])
        assert x_labels == ['Départ', 'Crête', 'Lac', 'Arrivée']

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_dnf_inclus(
        self, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """Les coureurs DNF avec st>0 sont inclus dans la vue."""
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock_get404.side_effect = [competition, cls]

        ok  = make_runner(1, st=100000, rt=50000, stat=STAT_OK,  name='Alice')
        dnf = make_runner(2, st=105000, rt=-1,    stat=STAT_DNF, name='Bob')
        MockCompetitor.objects.filter.return_value = [ok, dnf]

        from results.views import grouping_analysis
        grouping_analysis(self._get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        assert context['n_runners'] == 2

        series = json.loads(context['series_json'])
        noms = [s['name'] for s in series]
        assert 'Alice' in noms
        assert 'Bob'   in noms

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_tri_par_heure_de_depart(
        self, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """Les coureurs sont triés par heure de départ croissante (st)."""
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock_get404.side_effect = [competition, cls]

        # Bob part en premier (st=100000), Alice en deuxième (st=120000)
        alice = make_runner(1, st=120000, rt=50000, name='Alice')
        bob   = make_runner(2, st=100000, rt=55000, name='Bob')
        # ORM retourne dans un ordre quelconque
        MockCompetitor.objects.filter.return_value = [alice, bob]

        from results.views import grouping_analysis
        grouping_analysis(self._get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        series = json.loads(context['series_json'])

        # Bob (st=100000) doit apparaître en premier
        assert series[0]['name'] == 'Bob'
        assert series[1]['name'] == 'Alice'


# ─── Tests grouping_analysis — classement réel (vrai rang course) ─────────────

class TestGroupingRealRank:
    """Vérifie que series['rank'] reflète le vrai classement course,
    pas l'ordre de départ ni la position dans build_abs_time_series."""

    def _get(self):
        from django.test import RequestFactory
        return RequestFactory().get('/')

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_rang_reflete_classement_course(
        self, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """Bob part en 1er (st plus petit) mais Alice est plus rapide (rt plus petit).
        Alice doit avoir rank=1, Bob rank=2 dans les series.
        """
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock_get404.side_effect = [competition, cls]

        # Bob part avant Alice mais arrive après
        alice = make_runner(1, st=110000, rt=50000, name='Alice')  # part 2e, arrive 1re
        bob   = make_runner(2, st=100000, rt=60000, name='Bob')    # part 1er, arrive 2e
        MockCompetitor.objects.filter.return_value = [alice, bob]

        from results.views import grouping_analysis
        grouping_analysis(self._get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        series = json.loads(context['series_json'])

        # Retrouver par nom
        s_alice = next(s for s in series if s['name'] == 'Alice')
        s_bob   = next(s for s in series if s['name'] == 'Bob')

        assert s_alice['rank'] == 1, "Alice (rt=50000) doit être rank=1"
        assert s_bob['rank']   == 2, "Bob (rt=60000) doit être rank=2"

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_dnf_recoit_rank_none(
        self, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """Un coureur DNF doit avoir rank=None (pas un entier)."""
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock_get404.side_effect = [competition, cls]

        alice = make_runner(1, st=100000, rt=50000, stat=STAT_OK,  name='Alice')
        bob   = make_runner(2, st=110000, rt=-1,    stat=STAT_DNF, name='Bob')
        MockCompetitor.objects.filter.return_value = [alice, bob]

        from results.views import grouping_analysis
        grouping_analysis(self._get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        series = json.loads(context['series_json'])
        s_bob = next(s for s in series if s['name'] == 'Bob')
        assert s_bob['rank'] is None, "Un DNF doit avoir rank=None dans les séries"

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_rang_non_affecte_par_ordre_depart(
        self, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """Trois coureurs avec des départs et des temps différents.
        Le classement doit être uniquement basé sur rt (temps de course).
        """
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock_get404.side_effect = [competition, cls]

        # Ordre départ : C (st=100k), A (st=110k), B (st=120k)
        # Ordre arrivée (rt) : B=40k, A=50k, C=60k
        c_a = make_runner(1, st=110000, rt=50000, name='A')
        c_b = make_runner(2, st=120000, rt=40000, name='B')
        c_c = make_runner(3, st=100000, rt=60000, name='C')
        MockCompetitor.objects.filter.return_value = [c_a, c_b, c_c]

        from results.views import grouping_analysis
        grouping_analysis(self._get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        series = json.loads(context['series_json'])

        rank_map = {s['name']: s['rank'] for s in series}
        assert rank_map['B'] == 1   # rt=40000, le plus rapide
        assert rank_map['A'] == 2   # rt=50000
        assert rank_map['C'] == 3   # rt=60000

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_time_fmt_present_dans_series(
        self, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """Chaque série doit contenir time_fmt (temps formaté pour affichage)."""
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock_get404.side_effect = [competition, cls]

        c = make_runner(1, st=100000, rt=50000, name='Alice')
        MockCompetitor.objects.filter.return_value = [c]

        from results.views import grouping_analysis
        grouping_analysis(self._get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        series = json.loads(context['series_json'])
        assert 'time_fmt' in series[0], "time_fmt doit être présent dans chaque série"
        # rt=50000 dixièmes = 5000s = 83min20s
        assert series[0]['time_fmt'] != '—'

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_time_fmt_tiret_pour_dnf(
        self, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """Un coureur DNF (rt <= 0) doit avoir time_fmt='—'."""
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock_get404.side_effect = [competition, cls]

        c = make_runner(1, st=100000, rt=-1, stat=STAT_DNF, name='Bob')
        MockCompetitor.objects.filter.return_value = [c]

        from results.views import grouping_analysis
        grouping_analysis(self._get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        series = json.loads(context['series_json'])
        s_bob = next(s for s in series if s['name'] == 'Bob')
        assert s_bob['time_fmt'] == '—'


# ─── Tests invariants de couleur tableau/graphique ────────────────────────────
#
# La pastille de couleur dans le tableau et la ligne dans le graphique doivent
# avoir la même couleur. Le frontend JS calcule la couleur via :
#   PALETTE[SERIES.indexOf(s) % PALETTE.length]
# (identique pour buildDatasets et buildTable).
#
# Les tests suivants vérifient les invariants Python dont dépend cette logique :
#   1. La position (index) de chaque coureur dans series_json est stable et
#      reflète l'ordre de départ (pas le classement).
#   2. L'identité de chaque coureur est conservée (champ `id` présent).
#   3. Le champ `rank` est indépendant de la position dans SERIES.
# ─────────────────────────────────────────────────────────────────────────────

class TestGroupingColorInvariants:
    """Vérifie les invariants Python dont dépend la cohérence des couleurs
    entre le tableau récapitulatif et le graphique."""

    def _get(self):
        from django.test import RequestFactory
        return RequestFactory().get('/')

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_position_series_independante_du_rang(
        self, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """L'index dans SERIES (= couleur) est basé sur l'heure de départ,
        pas sur le classement. Un coureur rapide parti tard peut être en
        position 1 dans SERIES tout en ayant rank=1 — mais si un coureur
        part en 1er et arrive 2e, sa position dans SERIES (→ couleur) doit
        rester 0 indépendamment de son rang."""
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock_get404.side_effect = [competition, cls]

        # Bob part en 1er (st=100k) mais arrive 2e (rt=60k) → index 0 dans SERIES
        # Alice part en 2e (st=110k) mais arrive 1re (rt=40k) → index 1 dans SERIES
        bob   = make_runner(2, st=100000, rt=60000, name='Bob')
        alice = make_runner(1, st=110000, rt=40000, name='Alice')
        MockCompetitor.objects.filter.return_value = [alice, bob]

        from results.views import grouping_analysis
        grouping_analysis(self._get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        series = json.loads(context['series_json'])

        # Position dans SERIES (index = couleur du graphique)
        idx_bob   = next(i for i, s in enumerate(series) if s['name'] == 'Bob')
        idx_alice = next(i for i, s in enumerate(series) if s['name'] == 'Alice')

        assert idx_bob   == 0, "Bob (st=100k, part en 1er) doit être à l'index 0"
        assert idx_alice == 1, "Alice (st=110k, part en 2e) doit être à l'index 1"

        # Vérifier que le rang est bien inversé par rapport à la position
        s_bob   = series[idx_bob]
        s_alice = series[idx_alice]
        assert s_bob['rank']   == 2, "Bob arrive 2e"
        assert s_alice['rank'] == 1, "Alice arrive 1re"

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_champ_id_present_dans_series(
        self, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """Chaque entrée de series_json doit contenir un champ `id` permettant
        au frontend de relier la ligne du tableau au dataset du graphique."""
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock_get404.side_effect = [competition, cls]

        c1 = make_runner(42, st=100000, rt=50000, name='Alice')
        c2 = make_runner(99, st=110000, rt=55000, name='Bob')
        MockCompetitor.objects.filter.return_value = [c1, c2]

        from results.views import grouping_analysis
        grouping_analysis(self._get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        series = json.loads(context['series_json'])

        for s in series:
            assert 'id' in s, f"Le champ 'id' est manquant pour le coureur '{s.get('name')}'"

        ids = [s['id'] for s in series]
        assert 42 in ids
        assert 99 in ids

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_ordre_series_stable_avec_dnf(
        self, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """La présence de coureurs DNF ne doit pas perturber les index dans SERIES
        (et donc les couleurs). Un DNF conserve sa position basée sur st."""
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock_get404.side_effect = [competition, cls]

        # Alice part en 1er, Bob (DNF) en 2e, Charlie en 3e
        alice   = make_runner(1, st=100000, rt=50000, stat=STAT_OK,  name='Alice')
        bob_dnf = make_runner(2, st=110000, rt=-1,    stat=STAT_DNF, name='Bob')
        charlie = make_runner(3, st=120000, rt=55000, stat=STAT_OK,  name='Charlie')
        MockCompetitor.objects.filter.return_value = [alice, bob_dnf, charlie]

        from results.views import grouping_analysis
        grouping_analysis(self._get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        series = json.loads(context['series_json'])

        names_in_order = [s['name'] for s in series]
        # L'ordre de départ doit être préservé : Alice(0), Bob(1), Charlie(2)
        assert names_in_order.index('Alice')   < names_in_order.index('Bob'),   \
            "Alice (st=100k) doit précéder Bob (st=110k)"
        assert names_in_order.index('Bob')     < names_in_order.index('Charlie'), \
            "Bob (st=110k) doit précéder Charlie (st=120k)"
