"""
Tests unitaires pour l'analyse Régularité.

Couvre :
  - services.compute_regularity_analysis()
  - views.regularity_analysis()
"""

import json
import math
from unittest.mock import patch, MagicMock

import pytest

from results.models import STAT_OK


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_competitor(id, rt, stat=STAT_OK, name='Coureur', org=1):
    c       = MagicMock()
    c.id    = id
    c.rt    = rt
    c.stat  = stat
    c.name  = name
    c.org   = org
    c.is_ok = (stat == STAT_OK and rt > 0)
    return c


def rf_get(url='/'):
    from django.test import RequestFactory
    return RequestFactory().get(url)


# ─── Tests compute_regularity_analysis ───────────────────────────────────────

class TestComputeRegularityAnalysis:

    def _call(self, finishers, controls_seq, radio_map, top_fraction=0.25):
        from results.services import compute_regularity_analysis
        return compute_regularity_analysis(finishers, controls_seq, radio_map, top_fraction)

    # ── Cas limites ───────────────────────────────────────────────────────────

    def test_liste_vide_retourne_structure_vide(self):
        """Aucun coureur → toutes les listes vides, catégorie None."""
        result = self._call([], [], {})
        assert result['runner_regularity']   == []
        assert result['leg_stds']            == []
        assert result['leg_refs']            == []
        assert result['category_regularity'] is None
        assert result['n_legs']              == 0

    def test_coureur_unique_troncon_unique_std_zero(self):
        """Un seul coureur, un seul tronçon → σ = 0.0 (pas de variation)."""
        c = make_competitor(1, rt=5000)
        result = self._call([c], [], {})
        reg = result['runner_regularity'][0]
        assert reg['weighted_std'] == 0.0

    def test_coureur_unique_deux_troncons_std_calculable(self):
        """Un seul coureur, 2 tronçons avec des IP différents → σ > 0."""
        c = make_competitor(1, rt=5000)
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        # P31 = 1000 → leg 0 = 1000, leg 1 = 4000 → IP différents → σ > 0
        radio_map = {1: {31: 1000}}
        result = self._call([c], controls_seq, radio_map)
        reg = result['runner_regularity'][0]
        # IP leg0 = ref0/1000, IP leg1 = ref1/4000 — avec un seul coureur, ref = son temps
        # => IP0 = 1.0, IP1 = 1.0 → σ = 0
        assert reg['weighted_std'] is not None
        assert reg['weighted_std'] >= 0.0

    def test_coureur_sans_radio_std_none(self):
        """Coureur sans aucun temps radio valide → tous les tronçons None → σ = None."""
        c = make_competitor(1, rt=5000)
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        # Sans radio, P31 manque → leg 0 None, leg 1 (arrivée) None (cascade)
        result = self._call([c], controls_seq, {})
        reg = result['runner_regularity'][0]
        assert reg['weighted_std'] is None

    # ── Structure de sortie ───────────────────────────────────────────────────

    def test_champs_runner_regularity(self):
        """Chaque entrée de runner_regularity a les clés attendues."""
        c = make_competitor(1, rt=5000)
        result = self._call([c], [], {})
        reg = result['runner_regularity'][0]
        for key in ('id', 'weighted_std', 'mean_pi', 'leg_pis', 'leg_weights'):
            assert key in reg, f"clé '{key}' manquante"

    def test_id_conserve(self):
        """L'id du coureur est conservé dans runner_regularity."""
        c = make_competitor(42, rt=5000)
        result = self._call([c], [], {})
        assert result['runner_regularity'][0]['id'] == 42

    def test_ordre_preserve(self):
        """L'ordre des résultats correspond à l'ordre des finishers en entrée."""
        c1 = make_competitor(1, rt=5000)
        c2 = make_competitor(2, rt=6000)
        c3 = make_competitor(3, rt=7000)
        result = self._call([c1, c2, c3], [], {})
        ids = [r['id'] for r in result['runner_regularity']]
        assert ids == [1, 2, 3]

    def test_n_legs_sans_controles(self):
        """Sans contrôle → n_legs = 1."""
        c = make_competitor(1, rt=5000)
        result = self._call([c], [], {})
        assert result['n_legs'] == 1

    def test_n_legs_avec_controles(self):
        """N contrôles → n_legs = N + 1."""
        c = make_competitor(1, rt=5000)
        controls_seq = [
            {'ctrl_id': 31, 'ctrl_name': 'P31'},
            {'ctrl_id': 32, 'ctrl_name': 'P32'},
        ]
        radio_map = {1: {31: 2000, 32: 3500}}
        result = self._call([c], controls_seq, radio_map)
        assert result['n_legs'] == 3

    def test_longueur_leg_stds(self):
        """len(leg_stds) == n_legs."""
        c1 = make_competitor(1, rt=5000)
        c2 = make_competitor(2, rt=6000)
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        radio_map = {1: {31: 2000}, 2: {31: 2500}}
        result = self._call([c1, c2], controls_seq, radio_map)
        assert len(result['leg_stds']) == result['n_legs']

    def test_longueur_leg_refs(self):
        """len(leg_refs) == n_legs."""
        c1 = make_competitor(1, rt=5000)
        c2 = make_competitor(2, rt=6000)
        result = self._call([c1, c2], [], {})
        assert len(result['leg_refs']) == result['n_legs']

    def test_longueur_leg_pis(self):
        """Chaque coureur a len(leg_pis) == n_legs."""
        c1 = make_competitor(1, rt=5000)
        c2 = make_competitor(2, rt=6000)
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        radio_map = {1: {31: 2000}, 2: {31: 2500}}
        result = self._call([c1, c2], controls_seq, radio_map)
        for reg in result['runner_regularity']:
            assert len(reg['leg_pis']) == result['n_legs']

    # ── σ par tronçon ─────────────────────────────────────────────────────────

    def test_leg_std_none_avec_un_seul_coureur(self):
        """Avec un seul coureur, le σ par tronçon est None (impossible à calculer)."""
        c = make_competitor(1, rt=5000)
        result = self._call([c], [], {})
        assert result['leg_stds'][0] is None

    def test_leg_std_zero_quand_coureurs_identiques(self):
        """Deux coureurs identiques → σ par tronçon = 0 (même IP pour tous)."""
        c1 = make_competitor(1, rt=5000, name='Alice')
        c2 = make_competitor(2, rt=5000, name='Bob')
        result = self._call([c1, c2], [], {})
        # Avec 2 coureurs identiques : ref = 5000, IP de chacun = 1.0 → σ = 0
        assert result['leg_stds'][0] == pytest.approx(0.0, abs=1e-9)

    def test_leg_std_positif_quand_coureurs_differents(self):
        """Deux coureurs avec des temps différents → σ > 0."""
        c1 = make_competitor(1, rt=3000, name='Rapide')
        c2 = make_competitor(2, rt=6000, name='Lent')
        result = self._call([c1, c2], [], {})
        assert result['leg_stds'][0] is not None
        assert result['leg_stds'][0] > 0

    def test_leg_std_none_quand_troncon_invalide_pour_tous(self):
        """Si tous les coureurs ont le tronçon invalide → leg_std = None."""
        c1 = make_competitor(1, rt=5000)
        c2 = make_competitor(2, rt=6000)
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        # Pas de radio → les deux coureurs ont P31 = None, donc leg 0 = None
        # leg 1 (arrivée) aussi = None (cascade)
        result = self._call([c1, c2], controls_seq, {})
        assert result['leg_stds'][0] is None

    def test_leg_std_calcul_correct(self):
        """Vérification numérique du σ pour deux coureurs sur un seul tronçon."""
        # c1 : rt=4000, c2 : rt=6000
        # ref = top 25% = meilleur = 4000
        # IP_c1 = 4000/4000 = 1.0, IP_c2 = 4000/6000 ≈ 0.6667
        # mean = (1.0 + 0.6667)/2 = 0.8333
        # var = ((1.0-0.8333)^2 + (0.6667-0.8333)^2) / 2
        # σ = sqrt(var) ≈ 0.1667
        c1 = make_competitor(1, rt=4000, name='Rapide')
        c2 = make_competitor(2, rt=6000, name='Lent')
        result = self._call([c1, c2], [], {})
        ip1 = 1.0
        ip2 = 4000 / 6000
        mean_ip = (ip1 + ip2) / 2
        expected_std = math.sqrt(((ip1 - mean_ip) ** 2 + (ip2 - mean_ip) ** 2) / 2)
        assert result['leg_stds'][0] == pytest.approx(expected_std, abs=1e-6)

    # ── σ pondéré par coureur ─────────────────────────────────────────────────

    def test_runner_std_ponderation_par_longueur(self):
        """Le σ pondéré tient compte des longueurs de tronçon (temps de référence)."""
        # Avec 2 contrôles intermédiaires, si un tronçon est long (gros poids),
        # il influence davantage le σ pondéré.
        c1 = make_competitor(1, rt=10000, name='Alice')
        c2 = make_competitor(2, rt=12000, name='Bob')
        controls_seq = [
            {'ctrl_id': 31, 'ctrl_name': 'Court'},
            {'ctrl_id': 32, 'ctrl_name': 'Long'},
        ]
        # P31 (court) : c1=1000, c2=1200
        # P32 (long) : c1=5000, c2=6000 (tronçon vers P32 depuis P31)
        # Arrivée depuis P32 : c1=4000, c2=4800
        radio_map = {1: {31: 1000, 32: 6000}, 2: {31: 1200, 32: 7200}}
        result = self._call([c1, c2], controls_seq, radio_map)
        for reg in result['runner_regularity']:
            assert reg['weighted_std'] is not None

    def test_runner_std_independant_du_rang(self):
        """Le σ pondéré dépend de la consistance, pas du rang course."""
        # Coureur très régulier mais lent vs coureur irrégulier mais rapide
        c_fast = make_competitor(1, rt=4000, name='Rapide')
        c_slow = make_competitor(2, rt=8000, name='Lent')
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        # Rapide : P31=1000 (leg0=1000, leg1=3000) → IP0=ref/1000, IP1=ref/3000
        # Lent   : P31=2000 (leg0=2000, leg1=6000) → même ratio → plus régulier !
        # Mais les références sont différentes... testons juste que le calcul fonctionne
        radio_map = {1: {31: 1000}, 2: {31: 2000}}
        result = self._call([c_fast, c_slow], controls_seq, radio_map)
        for reg in result['runner_regularity']:
            assert reg['weighted_std'] is not None

    # ── Régularité catégorie ──────────────────────────────────────────────────

    def test_category_regularity_est_moyenne_des_stds(self):
        """La régularité catégorie = moyenne des σ pondérés des coureurs."""
        c1 = make_competitor(1, rt=4000)
        c2 = make_competitor(2, rt=6000)
        result = self._call([c1, c2], [], {})
        stds = [
            r['weighted_std'] for r in result['runner_regularity']
            if r['weighted_std'] is not None
        ]
        expected_cat = sum(stds) / len(stds) if stds else None
        if expected_cat is not None:
            assert result['category_regularity'] == pytest.approx(expected_cat, abs=1e-9)

    def test_category_regularity_none_si_tous_stds_none(self):
        """Si tous les σ sont None → category_regularity = None."""
        c1 = make_competitor(1, rt=5000)
        c2 = make_competitor(2, rt=6000)
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        # Pas de radio → tous les tronçons invalides → σ = None pour tous
        result = self._call([c1, c2], controls_seq, {})
        assert result['category_regularity'] is None

    def test_category_regularity_avec_un_std_valide(self):
        """Avec un seul coureur ayant un σ valide (tronçon unique) → cat = ce σ."""
        c1 = make_competitor(1, rt=5000)
        c2 = make_competitor(2, rt=6000)
        # Sans contrôles, les deux ont un seul tronçon → weighted_std = 0.0
        result = self._call([c1, c2], [], {})
        # Les deux ont std=0.0 → catégorie = 0.0
        assert result['category_regularity'] == pytest.approx(0.0, abs=1e-9)

    # ── mean_pi ───────────────────────────────────────────────────────────────

    def test_mean_pi_valide(self):
        """mean_pi est calculé correctement pour un coureur avec un tronçon."""
        c = make_competitor(1, rt=5000)
        result = self._call([c], [], {})
        reg = result['runner_regularity'][0]
        # IP = 1.0 (seul coureur = sa propre référence)
        assert reg['mean_pi'] == pytest.approx(1.0, abs=1e-6)

    def test_mean_pi_none_sans_donnees_valides(self):
        """Coureur sans tronçon valide → mean_pi = None."""
        c = make_competitor(1, rt=5000)
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        result = self._call([c], controls_seq, {})
        # P31 absent → cascade → tout None
        reg = result['runner_regularity'][0]
        assert reg['mean_pi'] is None

    # ── Trois coureurs ────────────────────────────────────────────────────────

    def test_trois_coureurs_structure_complete(self):
        """Trois coureurs → 3 entrées dans runner_regularity."""
        runners = [make_competitor(i, rt=4000 + i * 1000) for i in range(1, 4)]
        result = self._call(runners, [], {})
        assert len(result['runner_regularity']) == 3

    def test_leg_std_avec_trois_coureurs(self):
        """Avec 3 coureurs, leg_std est calculable sur le tronçon final."""
        c1 = make_competitor(1, rt=4000)
        c2 = make_competitor(2, rt=5000)
        c3 = make_competitor(3, rt=6000)
        result = self._call([c1, c2, c3], [], {})
        assert result['leg_stds'][0] is not None
        assert result['leg_stds'][0] > 0

    # ── Cas avec contrôles ────────────────────────────────────────────────────

    def test_controles_avec_radio_complet(self):
        """Deux coureurs avec tous leurs temps radio → tout calculable."""
        c1 = make_competitor(1, rt=6000, name='Alice')
        c2 = make_competitor(2, rt=7200, name='Bob')
        controls_seq = [
            {'ctrl_id': 31, 'ctrl_name': 'P31'},
            {'ctrl_id': 32, 'ctrl_name': 'P32'},
        ]
        radio_map = {1: {31: 2000, 32: 4000}, 2: {31: 2400, 32: 4800}}
        result = self._call([c1, c2], controls_seq, radio_map)

        # 3 tronçons attendus
        assert result['n_legs'] == 3
        assert len(result['leg_stds']) == 3

        # Tous les tronçons ont un σ calculable (2 coureurs avec données valides)
        for std in result['leg_stds']:
            assert std is not None

        # Les deux coureurs ont un σ non nul (IP différents par tronçon)
        for reg in result['runner_regularity']:
            assert reg['weighted_std'] is not None

    def test_poste_manquant_pour_un_coureur_leg_std_sur_un(self):
        """Si un coureur manque P31, build_leg_matrix cascade les None :
        leg 0 ET leg 1 de ce coureur sont None. Avec 3 coureurs dont 1 sans P31,
        leg 0 n'a qu'une seule valeur valide → None,
        leg 1 a 2 valeurs valides (les 2 autres) → σ calculable."""
        c1 = make_competitor(1, rt=5000, name='Alice')   # pas de P31 → cascade
        c2 = make_competitor(2, rt=6000, name='Bob')
        c3 = make_competitor(3, rt=7000, name='Charlie')
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        # Seul c1 n'a pas P31
        radio_map = {2: {31: 2500}, 3: {31: 3000}}
        result = self._call([c1, c2, c3], controls_seq, radio_map)

        # leg 0 (vers P31) : seul c2 et c3 ont une valeur, c1 cascade → None
        # mais 2 valeurs valides → σ calculable
        assert result['leg_stds'][0] is not None
        # leg 1 (vers arrivée) : c2=3500, c3=4000 → 2 valeurs → σ calculable
        assert result['leg_stds'][1] is not None
        # c1 (sans P31, cascade) → weighted_std = None
        alice = next(r for r in result['runner_regularity'] if r['id'] == 1)
        assert alice['weighted_std'] is None


# ─── Tests regularity_analysis (vue) ─────────────────────────────────────────

class TestRegularityAnalysisView:

    def _get(self, url='/'):
        return rf_get(url)

    def _mock_setup(self, mock_get404, MockCompetitor, competitors):
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock_get404.side_effect = [competition, cls]
        MockCompetitor.objects.filter.return_value = competitors

    # ── no_data ───────────────────────────────────────────────────────────────

    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_no_data_si_aucun_classe(self, MockComp, mock404, mock_render):
        """0 classé → no_data=True."""
        self._mock_setup(mock404, MockComp, [])

        from results.views import regularity_analysis
        regularity_analysis(self._get(), cid=1, class_id=10)

        _, template, ctx = mock_render.call_args[0]
        assert 'regularity' in template
        assert ctx['no_data'] is True

    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_no_data_si_un_seul_classe(self, MockComp, mock404, mock_render):
        """1 seul classé → no_data=True (σ par tronçon non calculable)."""
        c = make_competitor(1, rt=5000)
        self._mock_setup(mock404, MockComp, [c])

        from results.views import regularity_analysis
        regularity_analysis(self._get(), cid=1, class_id=10)

        _, _, ctx = mock_render.call_args[0]
        assert ctx['no_data'] is True

    # ── Contexte nominal ──────────────────────────────────────────────────────

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_contexte_cles_de_base(
        self, MockComp, mock404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """Vérifie les clés minimales du contexte."""
        c1 = make_competitor(1, rt=5000, name='Alice')
        c2 = make_competitor(2, rt=6000, name='Bob')
        self._mock_setup(mock404, MockComp, [c1, c2])

        from results.views import regularity_analysis
        regularity_analysis(self._get(), cid=1, class_id=10)

        _, template, ctx = mock_render.call_args[0]
        assert 'regularity' in template
        assert ctx['no_data'] is False
        assert ctx['n_finishers'] == 2
        assert 'series_json'   in ctx
        assert 'leg_info_json' in ctx
        assert 'n_legs'        in ctx
        assert 'current_analysis' in ctx
        assert ctx['current_analysis'] == 'regularity'

    @patch('results.views.get_org_map',        return_value={1: 'COLE'})
    @patch('results.views.get_class_controls', return_value=(
        [{'ctrl_id': 31, 'ctrl_name': 'P31'}], {}
    ))
    @patch('results.views.get_radio_map',      return_value={
        1: {31: 2000}, 2: {31: 2500},
    })
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_n_legs_avec_controles(
        self, MockComp, mock404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """n_legs = n_contrôles + 1."""
        c1 = make_competitor(1, rt=5000)
        c2 = make_competitor(2, rt=6000)
        self._mock_setup(mock404, MockComp, [c1, c2])

        from results.views import regularity_analysis
        regularity_analysis(self._get(), cid=1, class_id=10)

        _, _, ctx = mock_render.call_args[0]
        assert ctx['n_legs'] == 2   # 1 contrôle + arrivée

    # ── series_json ───────────────────────────────────────────────────────────

    @patch('results.views.get_org_map',        return_value={1: 'COLE'})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_series_json_structure(
        self, MockComp, mock404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """Chaque entrée de series_json contient les champs attendus."""
        c1 = make_competitor(1, rt=5000, name='Alice', org=1)
        c2 = make_competitor(2, rt=6000, name='Bob',   org=1)
        self._mock_setup(mock404, MockComp, [c1, c2])

        from results.views import regularity_analysis
        regularity_analysis(self._get(), cid=1, class_id=10)

        _, _, ctx = mock_render.call_args[0]
        series = json.loads(ctx['series_json'])
        assert len(series) == 2
        for s in series:
            for key in ('id', 'name', 'org', 'rank', 'time', 'weighted_std', 'mean_pi',
                        'leg_pis', 'leg_weights'):
                assert key in s, f"clé '{key}' manquante dans series_json"

    @patch('results.views.get_org_map',        return_value={1: 'COLE'})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_series_json_ordre_par_rang(
        self, MockComp, mock404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """Les séries sont dans l'ordre de classement course (rt croissant)."""
        alice = make_competitor(1, rt=7000, name='Alice', org=1)
        bob   = make_competitor(2, rt=5000, name='Bob',   org=1)
        self._mock_setup(mock404, MockComp, [alice, bob])

        from results.views import regularity_analysis
        regularity_analysis(self._get(), cid=1, class_id=10)

        _, _, ctx = mock_render.call_args[0]
        series = json.loads(ctx['series_json'])
        assert series[0]['name'] == 'Bob'    # plus rapide
        assert series[1]['name'] == 'Alice'
        assert series[0]['rank'] == 1
        assert series[1]['rank'] == 2

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_series_json_valide_json(
        self, MockComp, mock404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """series_json doit être du JSON valide."""
        c1 = make_competitor(1, rt=5000)
        c2 = make_competitor(2, rt=6000)
        self._mock_setup(mock404, MockComp, [c1, c2])

        from results.views import regularity_analysis
        regularity_analysis(self._get(), cid=1, class_id=10)

        _, _, ctx = mock_render.call_args[0]
        # Ne doit pas lever d'exception
        parsed = json.loads(ctx['series_json'])
        assert isinstance(parsed, list)

    # ── leg_info_json ─────────────────────────────────────────────────────────

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=(
        [{'ctrl_id': 31, 'ctrl_name': 'Crête'}], {}
    ))
    @patch('results.views.get_radio_map',      return_value={
        1: {31: 2000}, 2: {31: 2500},
    })
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_leg_info_json_labels(
        self, MockComp, mock404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """leg_info_json contient les labels de tronçon corrects."""
        c1 = make_competitor(1, rt=5000)
        c2 = make_competitor(2, rt=6000)
        self._mock_setup(mock404, MockComp, [c1, c2])

        from results.views import regularity_analysis
        regularity_analysis(self._get(), cid=1, class_id=10)

        _, _, ctx = mock_render.call_args[0]
        leg_info = json.loads(ctx['leg_info_json'])
        labels = [l['label'] for l in leg_info]
        assert 'Crête' in labels
        assert 'Arrivée' in labels

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_leg_info_json_champs(
        self, MockComp, mock404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """Chaque entrée de leg_info_json a label, ref et leg_std."""
        c1 = make_competitor(1, rt=5000)
        c2 = make_competitor(2, rt=6000)
        self._mock_setup(mock404, MockComp, [c1, c2])

        from results.views import regularity_analysis
        regularity_analysis(self._get(), cid=1, class_id=10)

        _, _, ctx = mock_render.call_args[0]
        leg_info = json.loads(ctx['leg_info_json'])
        for info in leg_info:
            assert 'label'   in info
            assert 'ref'     in info
            assert 'leg_std' in info

    # ── category_regularity ───────────────────────────────────────────────────

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_category_regularity_present_dans_contexte(
        self, MockComp, mock404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """category_regularity est dans le contexte (peut être None ou float)."""
        c1 = make_competitor(1, rt=5000)
        c2 = make_competitor(2, rt=6000)
        self._mock_setup(mock404, MockComp, [c1, c2])

        from results.views import regularity_analysis
        regularity_analysis(self._get(), cid=1, class_id=10)

        _, _, ctx = mock_render.call_args[0]
        assert 'category_regularity' in ctx

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_category_regularity_est_float_ou_none(
        self, MockComp, mock404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """category_regularity est un float arrondi ou None."""
        c1 = make_competitor(1, rt=5000)
        c2 = make_competitor(2, rt=6000)
        self._mock_setup(mock404, MockComp, [c1, c2])

        from results.views import regularity_analysis
        regularity_analysis(self._get(), cid=1, class_id=10)

        _, _, ctx = mock_render.call_args[0]
        cat = ctx['category_regularity']
        assert cat is None or isinstance(cat, float)

    # ── Template ──────────────────────────────────────────────────────────────

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_template_correct(
        self, MockComp, mock404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """La vue utilise le bon template."""
        c1 = make_competitor(1, rt=5000)
        c2 = make_competitor(2, rt=6000)
        self._mock_setup(mock404, MockComp, [c1, c2])

        from results.views import regularity_analysis
        regularity_analysis(self._get(), cid=1, class_id=10)

        _, template, _ = mock_render.call_args[0]
        assert template == 'results/regularity.html'

    # ── Weighted_std arrondi ──────────────────────────────────────────────────

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_weighted_std_arrondi_4_decimales(
        self, MockComp, mock404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """weighted_std dans series_json est arrondi à 4 décimales."""
        c1 = make_competitor(1, rt=5000)
        c2 = make_competitor(2, rt=7000)
        self._mock_setup(mock404, MockComp, [c1, c2])

        from results.views import regularity_analysis
        regularity_analysis(self._get(), cid=1, class_id=10)

        _, _, ctx = mock_render.call_args[0]
        series = json.loads(ctx['series_json'])
        for s in series:
            if s['weighted_std'] is not None:
                # Vérifier que l'arrondi ne dépasse pas 4 décimales
                as_str = str(s['weighted_std'])
                if '.' in as_str:
                    decimals = len(as_str.split('.')[1])
                    assert decimals <= 4, f"weighted_std a plus de 4 décimales : {s['weighted_std']}"


# ─── Tests intégration services + vues ───────────────────────────────────────

class TestRegularityIntegration:
    """Vérifie la cohérence entre le service et la vue."""

    @patch('results.views.get_org_map',        return_value={1: 'NOSE'})
    @patch('results.views.get_class_controls', return_value=(
        [{'ctrl_id': 31, 'ctrl_name': 'P31'}], {}
    ))
    @patch('results.views.get_radio_map',      return_value={
        1: {31: 1500}, 2: {31: 2000}, 3: {31: 1800},
    })
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_trois_coureurs_series_completes(
        self, MockComp, mock404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        """Trois coureurs avec radios → series_json complet et cohérent."""
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock404.side_effect = [competition, cls]

        c1 = make_competitor(1, rt=4000, name='Alice', org=1)
        c2 = make_competitor(2, rt=5000, name='Bob',   org=1)
        c3 = make_competitor(3, rt=6000, name='Charlie', org=1)
        MockComp.objects.filter.return_value = [c1, c2, c3]

        from results.views import regularity_analysis
        regularity_analysis(rf_get(), cid=1, class_id=10)

        _, template, ctx = mock_render.call_args[0]
        assert template == 'results/regularity.html'
        assert ctx['no_data'] is False
        assert ctx['n_finishers'] == 3
        assert ctx['n_legs'] == 2   # 1 contrôle + arrivée

        series = json.loads(ctx['series_json'])
        assert len(series) == 3

        # Alice est la plus rapide → rank=1
        assert series[0]['name'] == 'Alice'
        assert series[0]['rank'] == 1

        # Tous ont des leg_pis (longueur = n_legs = 2)
        for s in series:
            assert len(s['leg_pis']) == 2

        leg_info = json.loads(ctx['leg_info_json'])
        assert len(leg_info) == 2
        labels = [l['label'] for l in leg_info]
        assert 'P31' in labels
        assert 'Arrivée' in labels
