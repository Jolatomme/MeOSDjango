"""
Tests unitaires pour l'indice de regroupement lièvre / suiveur.

Couvre :
  - services._hare_integral()
  - services.compute_grouping_index()
  - views.grouping_index_analysis()

Exécution :
    pytest results/test_grouping_index.py -v
"""

from unittest.mock import patch, MagicMock
import pytest


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_runner(id, st, rt, stat=1, name='Coureur', org=1):
    c       = MagicMock()
    c.id    = id
    c.st    = st
    c.rt    = rt
    c.stat  = stat
    c.name  = name
    c.org   = org
    c.is_ok = (stat == 1 and rt > 0)
    return c


# Seuils par défaut en dixièmes de seconde (7 s et 20 s)
T1 = 70
T2 = 200


# ─── Tests _hare_integral ─────────────────────────────────────────────────────

class TestHareIntegral:

    def _call(self, d0, d1, t1=T1, t2=T2):
        from results.services import _hare_integral
        return _hare_integral(d0, d1, t1, t2)

    # ── Cas limites ───────────────────────────────────────────────────────────

    def test_toujours_derriere_zero(self):
        """Coureur toujours derrière → 0."""
        assert self._call(-50, -50) == pytest.approx(0.0)

    def test_toujours_trop_devant_zero(self):
        """Coureur toujours > T2 devant → 0."""
        assert self._call(300, 300) == pytest.approx(0.0)

    def test_toujours_dans_zone_100(self):
        """Toujours dans [0, T1] → 1.0."""
        assert self._call(30, 50) == pytest.approx(1.0)

    def test_ecart_constant_nul_demi(self):
        """Deux coureurs pointent exactement ensemble sur tout le tronçon → 0.5.
        (Spec : 'Deux coureurs qui poinçonnent au même moment reçoivent un
         indice de lièvre de 50%'.)"""
        assert self._call(0, 0) == pytest.approx(0.5)

    # ── Zone de transition ────────────────────────────────────────────────────

    def test_mi_zone_transition(self):
        """Écart constant = (T1+T2)/2 → h = 0.5."""
        d = (T1 + T2) / 2          # 135 dixièmes
        result = self._call(d, d)
        assert result == pytest.approx(0.5, abs=1e-6)

    def test_juste_sur_t1(self):
        """Écart constant = T1 → h = 1.0."""
        assert self._call(T1, T1) == pytest.approx(1.0)

    def test_juste_sur_t2(self):
        """Écart constant = T2 → h = 0.0."""
        assert self._call(T2, T2) == pytest.approx(0.0)

    # ── Cas avec croisement (exemple du cahier des charges) ──────────────────

    def test_croisement_spec_coureur_a(self):
        """Spec : A poinçonne 11 s après B au départ du tronçon, 5 s avant B
        à l'arrivée → croisement à 69% → indice lièvre de A = 31%.

        Ici d0 = -110 (A derrière B) et d1 = +50 (A devant B).
        _hare_integral(d0=-110, d1=+50) = intégrale de h(delta_A_devant_B).
        """
        # d > 0  ↔  A devant B
        # Au départ : B est devant A de 11 s (110 dixièmes) → d0 = -110
        # À l'arrivée : A est devant B de 5 s (50 dixièmes) → d1 = +50
        result = self._call(-110, 50)
        # Croisement à f* = 110 / (110 + 50) ≈ 0.6875 ≈ 69%
        # Sur [f*, 1] (≈ 31%), A est en tête avec un écart faible dans T1 → ~100%
        # Indice ≈ 0.31 × 1.0 = ~31%
        assert result == pytest.approx(0.31, abs=0.02)

    def test_croisement_spec_coureur_b(self):
        """B devant A au départ (110 dixièmes d'avance), A double B vers 69%.
        B est devant A : d0 = +110, d1 = -50.

        Le spec annonce 53% mais contient une erreur arithmétique :
        il écrit (69+100)/2 = 34.5 au lieu de 84.5.
        En recalculant avec la définition correcte :
          [0, 25%]  : indice moyen = (h(110) + h(70))/2 = (69.2% + 100%)/2 = 84.6%
          [25%, 69%]: h = 100% (B dans zone T1)
          [69%, 100%]: h = 0%  (B est derrière A)
          → indice total ≈ 0.25×84.6 + 0.44×100 + 0.31×0 ≈ 65.1%
        Notre valeur analytique exacte est 64.9%, cohérente avec ce calcul.
        """
        result = self._call(110, -50)
        assert result == pytest.approx(0.649, abs=0.002)

    # ── Invariant : hare + follow ≤ 1 ────────────────────────────────────────

    def test_hare_plus_follower_inferieur_ou_egal_1_zone_transition(self):
        """Pour d dans ]T1, T2[, hare(d) + hare(-d) < 1.

        hare(-d) = 0 car -d < 0 (le second coureur est derrière).
        hare(d) est dans ]0, 1[ car d est dans la zone de transition.
        La somme est donc hare(d) < 1.
        Le spec précise : la somme 'ne peut jamais dépasser 100%', pas qu'elle vaut 100%.
        """
        d = (T1 + T2) // 2   # 135 dixièmes, au milieu de la transition → hare = 0.5
        h  = self._call( d,  d)   # 0.5
        hm = self._call(-d, -d)   # 0.0  (-d < 0 → h = 0)
        assert h  == pytest.approx(0.5, abs=1e-6)
        assert hm == pytest.approx(0.0, abs=1e-6)
        assert h + hm < 1.0

    def test_hare_plus_follower_egal_1_dans_zone_t1(self):
        """Pour 0 < d ≤ T1, hare(d) = 1 et hare(-d) = 0 → somme = 1."""
        d = T1 // 2    # 35 dixièmes, clairement dans [0, T1]
        h  = self._call( d,  d)
        hm = self._call(-d, -d)
        assert h  == pytest.approx(1.0, abs=1e-9)
        assert hm == pytest.approx(0.0, abs=1e-9)
        assert h + hm == pytest.approx(1.0, abs=1e-9)

    def test_hare_plus_follower_inferieur_ou_egal_1_ecart_variable(self):
        """Pour tout écart variable, hare + follow ≤ 1 (invariant du spec)."""
        d0, d1 = 30, 120
        h  = self._call( d0,  d1)
        hm = self._call(-d0, -d1)
        assert h + hm <= 1.0 + 1e-9

    def test_resultat_entre_0_et_1(self):
        """L'intégrale est toujours dans [0, 1]."""
        for d0, d1 in [(-200, 200), (50, 250), (0, 400), (-T2, T2)]:
            r = self._call(d0, d1)
            assert 0.0 <= r <= 1.0 + 1e-9, f"hors [0,1] pour d0={d0}, d1={d1}"


# ─── Tests compute_grouping_index ─────────────────────────────────────────────

class TestComputeGroupingIndex:

    def _call(self, runners, controls_seq, radio_map, t1=7, t2=20):
        from results.services import compute_grouping_index
        return compute_grouping_index(runners, controls_seq, radio_map, t1, t2)

    # ── Coureur seul ──────────────────────────────────────────────────────────

    def test_coureur_seul_global_none(self):
        """Un seul coureur → aucune paire → global_index = None."""
        c = make_runner(1, st=100000, rt=50000)
        res = self._call([c], [], {})
        assert res[0]['global_index'] is None

    def test_coureur_seul_leg_none(self):
        """Un seul coureur → tous les leg_indices = None."""
        c  = make_runner(1, st=100000, rt=50000)
        cs = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        rm = {1: {31: 20000}}
        res = self._call([c], cs, rm)
        assert all(v is None for v in res[0]['leg_indices'])

    # ── Coureur sans heure de départ ──────────────────────────────────────────

    def test_coureur_sans_st_exclus(self):
        """Un coureur avec st=0 produit global_index=None et legs=None."""
        c = make_runner(1, st=0, rt=50000)
        res = self._call([c], [], {})
        assert res[0]['global_index'] is None

    # ── Deux coureurs ensemble ────────────────────────────────────────────────

    def test_deux_coureurs_separes_ignorés(self):
        """Deux coureurs séparés de plus de T2 dès le départ → aucune interaction."""
        # Départ : c1=0s, c2=100000 (séparation énorme)
        c1 = make_runner(1, st=0,      rt=50000)
        c2 = make_runner(2, st=100000, rt=50000)
        res = self._call([c1, c2], [], {}, t1=7, t2=20)
        assert res[0]['global_index'] is None
        assert res[1]['global_index'] is None

    def test_deux_coureurs_identiques_indice_nul(self):
        """Deux coureurs avec exactement les mêmes heures de passage :
        hare = follow = 0.5 → indice net = follow - hare = 0."""
        c1 = make_runner(1, st=100000, rt=50000)
        c2 = make_runner(2, st=100000, rt=50000)
        res = self._call([c1, c2], [], {}, t1=7, t2=20)
        # _hare_integral(0,0) = 0.5 = follow_ik = hare_ik → net = 0
        assert res[0]['global_index'] == pytest.approx(0.0, abs=1e-4)
        assert res[1]['global_index'] == pytest.approx(0.0, abs=1e-4)

    def test_coureur_nettement_devant_negatif(self):
        """Coureur A constamment 5 s devant B (< T1=7s) → net < 0 pour A."""
        # Départ : A=100000, B=100050 (5 s = 50 dixièmes)
        # Arrivée : même écart
        c1 = make_runner(1, st=100000, rt=50000)
        c2 = make_runner(2, st=100050, rt=50000)
        res = self._call([c1, c2], [], {}, t1=7, t2=20)
        # c1 est devant c2 de 50 dixièmes (< T1=70) → hare=1, follow=0 → net=-1
        assert res[0]['global_index'] is not None
        assert res[0]['global_index'] < 0       # c1 lièvre
        assert res[1]['global_index'] is not None
        assert res[1]['global_index'] > 0       # c2 suiveur

    def test_antisymmetrie(self):
        """Les indices de c1 et c2 sont opposés (lièvre ↔ suiveur)."""
        c1 = make_runner(1, st=100000, rt=50000)
        c2 = make_runner(2, st=100050, rt=50000)
        res = self._call([c1, c2], [], {}, t1=7, t2=20)
        g1 = res[0]['global_index']
        g2 = res[1]['global_index']
        assert g1 is not None and g2 is not None
        assert g1 == pytest.approx(-g2, abs=1e-4)

    # ── Nombre de tronçons ────────────────────────────────────────────────────

    def test_nombre_leg_indices_sans_controles(self):
        """Sans contrôle intermédiaire → 1 seul tronçon (départ→arrivée)."""
        c1 = make_runner(1, st=100000, rt=50000)
        c2 = make_runner(2, st=100000, rt=50000)
        res = self._call([c1, c2], [], {})
        assert len(res[0]['leg_indices']) == 1

    def test_nombre_leg_indices_avec_controles(self):
        """Avec N contrôles → N+1 tronçons."""
        c1 = make_runner(1, st=100000, rt=60000)
        c2 = make_runner(2, st=100000, rt=60000)
        cs = [
            {'ctrl_id': 31, 'ctrl_name': 'P31'},
            {'ctrl_id': 32, 'ctrl_name': 'P32'},
        ]
        rm = {1: {31: 20000, 32: 40000}, 2: {31: 20000, 32: 40000}}
        res = self._call([c1, c2], cs, rm)
        assert len(res[0]['leg_indices']) == 3  # 2 contrôles + 1

    # ── Tronçon avec poste manquant ────────────────────────────────────────────

    def test_poste_manquant_leg_none(self):
        """Si un coureur n'a pas de passage à un contrôle → leg = None."""
        c1 = make_runner(1, st=100000, rt=60000)
        c2 = make_runner(2, st=100000, rt=60000)
        cs = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        # c1 manque P31
        rm = {2: {31: 20000}}
        res = self._call([c1, c2], cs, rm)
        # Le tronçon 0 (Départ→P31) est invalide pour c1
        assert res[0]['leg_indices'][0] is None

    # ── Champs de sortie ───────────────────────────────────────────────────────

    def test_champs_presents(self):
        """Vérification des clés dans le résultat."""
        c = make_runner(1, st=100000, rt=50000)
        res = self._call([c], [], {})
        for key in ('id', 'leg_indices', 'leg_ref_ids', 'global_index'):
            assert key in res[0]

    def test_leg_ref_ids_none_si_seul(self):
        """Un coureur seul n'a pas de partenaire dominant → tous None."""
        c = make_runner(1, st=100000, rt=50000)
        res = self._call([c], [], {})
        assert all(v is None for v in res[0]['leg_ref_ids'])

    def test_leg_ref_ids_pointe_vers_partenaire(self):
        """Avec deux coureurs, le ref_id pointe vers l'autre coureur."""
        c1 = make_runner(1, st=100000, rt=50000)
        c2 = make_runner(2, st=100030, rt=50000)
        res = self._call([c1, c2], [], {}, t1=7, t2=20)
        # Chacun a l'autre comme partenaire dominant
        assert res[0]['leg_ref_ids'][0] == 2
        assert res[1]['leg_ref_ids'][0] == 1

    def test_leg_ref_ids_none_si_hors_groupe(self):
        """Deux coureurs séparés de plus de T2 → ref_id = None."""
        c1 = make_runner(1, st=0,      rt=50000)
        c2 = make_runner(2, st=100000, rt=50000)
        res = self._call([c1, c2], [], {}, t1=7, t2=20)
        assert res[0]['leg_ref_ids'][0] is None
        assert res[1]['leg_ref_ids'][0] is None

    def test_id_conserve(self):
        """L'id du coureur est conservé dans le résultat."""
        c = make_runner(42, st=100000, rt=50000)
        res = self._call([c], [], {})
        assert res[0]['id'] == 42

    def test_ordre_preserve(self):
        """L'ordre des résultats correspond à l'ordre des coureurs en entrée."""
        runners = [make_runner(i, st=100000 + i * 100, rt=50000) for i in range(5)]
        res = self._call(runners, [], {})
        assert [r['id'] for r in res] == [0, 1, 2, 3, 4]

    # ── Trois coureurs ────────────────────────────────────────────────────────

    def test_trois_coureurs_groupe_serre(self):
        """Trois coureurs partant quasi ensemble → les deux suiveurs ont un
        indice positif, le lièvre un indice négatif."""
        # c1 part en tête, c2 et c3 collés derrière (3 s = 30 dixièmes < T1)
        c1 = make_runner(1, st=100000, rt=50000)
        c2 = make_runner(2, st=100030, rt=50000)  # +3 s
        c3 = make_runner(3, st=100060, rt=50000)  # +6 s
        res = self._call([c1, c2, c3], [], {}, t1=7, t2=20)
        g1 = res[0]['global_index']
        g2 = res[1]['global_index']
        g3 = res[2]['global_index']
        assert g1 is not None and g1 < 0, "c1 devrait être lièvre"
        assert g3 is not None and g3 > 0, "c3 devrait être suiveur"
        # c2 est entre les deux
        assert g2 is not None


# ─── Tests vue grouping_index_analysis ───────────────────────────────────────

class TestGroupingIndexView:

    def _get(self, url='/', params=None):
        from django.test import RequestFactory
        url_with_params = url
        if params:
            url_with_params = url + '?' + '&'.join(f'{k}={v}' for k, v in params.items())
        return RequestFactory().get(url_with_params)

    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_no_data_si_aucun_depart(self, MockComp, mock404, mock_render):
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock404.side_effect = [competition, cls]
        c = make_runner(1, st=0, rt=0)
        MockComp.objects.filter.return_value = [c]

        from results.views import grouping_index_analysis
        grouping_index_analysis(self._get(), cid=1, class_id=10)

        _, template, ctx = mock_render.call_args[0]
        assert 'grouping_index' in template
        assert ctx['no_data'] is True

    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.rank_finishers', return_value=([], [], None))
    def test_rendu_nominal(self, mock_rf, mock_rm, mock_gc, mock_gom,
                           MockComp, mock404, mock_render):
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock404.side_effect = [competition, cls]
        c = make_runner(1, st=100000, rt=50000)
        MockComp.objects.filter.return_value = [c]

        from results.views import grouping_index_analysis
        grouping_index_analysis(self._get(), cid=1, class_id=10)

        _, template, ctx = mock_render.call_args[0]
        assert 'grouping_index' in template
        assert ctx['no_data'] is False
        assert 'results_json' in ctx
        assert 'leg_labels_json' in ctx
        assert ctx['t1'] == 7
        assert ctx['t2'] == 20

    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.rank_finishers', return_value=([], [], None))
    def test_seuils_custom_via_get(self, mock_rf, mock_rm, mock_gc, mock_gom,
                                   MockComp, mock404, mock_render):
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock404.side_effect = [competition, cls]
        c = make_runner(1, st=100000, rt=50000)
        MockComp.objects.filter.return_value = [c]

        from results.views import grouping_index_analysis
        grouping_index_analysis(self._get(params={'t1': '5', 't2': '15'}),
                                cid=1, class_id=10)

        _, _, ctx = mock_render.call_args[0]
        assert ctx['t1'] == 5
        assert ctx['t2'] == 15

    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.rank_finishers', return_value=([], [], None))
    def test_seuils_invalides_remis_par_defaut(self, mock_rf, mock_rm, mock_gc,
                                               mock_gom, MockComp, mock404, mock_render):
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10
        mock404.side_effect = [competition, cls]
        c = make_runner(1, st=100000, rt=50000)
        MockComp.objects.filter.return_value = [c]

        from results.views import grouping_index_analysis
        grouping_index_analysis(self._get(params={'t1': 'abc', 't2': 'xyz'}),
                                cid=1, class_id=10)

        _, _, ctx = mock_render.call_args[0]
        assert ctx['t1'] == 7
        assert ctx['t2'] == 20
