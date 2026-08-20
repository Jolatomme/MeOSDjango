"""
Tests du suivi live (postes radio) — sans base de données (tout est mocké).

Couvre :
  - services.rank_live / race_start_clock / race_in_progress / format_clock
  - views.live_results (page) et api_live_results (JSON)
  - urls live (catégorie + circuit, page + API)
"""

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.test import RequestFactory
from django.urls import reverse, resolve

from results.models import (
    STAT_OK, STAT_MP, STAT_DNF, STAT_DNS, STAT_OCC,
)
from results.services import (
    rank_live, race_start_clock, race_end_clock, race_state,
    race_in_progress, mark_negative_times, mark_presumed_prestart, format_clock,
)

NOW = datetime(2025, 8, 14, 12, 0, 0)   # 12:00:00 → 432000 (1/10 s depuis minuit)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_competitor(id=1, st=100000, stat=0, rt=0, name='Coureur', org=1, cls=10,
                    prel=False):
    c = MagicMock()
    c.id = id; c.st = st; c.stat = stat; c.rt = rt
    c.name = name; c.org = org; c.cls = cls
    c.prel = prel
    c.is_ok = (stat == STAT_OK and rt > 0)
    c.status_label = 'Inconnu'; c.status_badge = 'info'
    return c


def make_runner(id=1, group='en_course', rank=1):
    c = make_competitor(id=id)
    c.live_group = group; c.live_rank = rank
    c.n_punches = 0; c.last_ctrl = None; c.last_time = None
    c.last_punch_clock = None
    c.class_obj = None
    return c


def rf_get(url='/'):
    return RequestFactory().get(url)


def patch_live_view(defaults=None):
    """Paches communs des vues live (catégorie simple)."""
    defaults = defaults or {}
    ctx = {
        'competition': MagicMock(cid=1, name='Test'),
        'cls': MagicMock(id=10, name='H21'),
        'competitors': [],
        'course': None,
    }
    ctx.update(defaults)
    return [
        patch('results.views._load_class_context',
              return_value=(ctx['competition'], ctx['cls'], ctx['competitors'], ctx['course'])),
        patch('results.views.Mopteam'),
        patch('results.views.get_org_map', return_value={}),
        patch('results.views.get_radio_map', return_value={}),
        patch('results.views.rank_live', return_value=[]),
        patch('results.views.race_start_clock', return_value=None),
    ]


# ══════════════════════════════════════════════════════════════════════════════
# format_clock
# ══════════════════════════════════════════════════════════════════════════════

class TestFormatClock:
    def _call(self, s):
        return format_clock(s)

    def test_matin(self):       assert self._call(370800) == '10:18:00'
    def test_minuit(self):      assert self._call(0) == '00:00:00'
    def test_petite_heure(self): assert self._call(36610) == '01:01:01'
    def test_passe_minuit(self): assert self._call(900000) == '01:00:00'
    def test_negatif(self):     assert self._call(-370800) == '-10:18:00'
    def test_invalide(self):    assert self._call(None) == '-'
    def test_unite_dixiemes(self): assert self._call(370801) == '10:18:00'


# ══════════════════════════════════════════════════════════════════════════════
# race_start_clock / race_in_progress
# ══════════════════════════════════════════════════════════════════════════════

class TestRaceStartClock:
    def test_min_st(self):
        cs = [make_competitor(1, st=300000), make_competitor(2, st=200000)]
        assert race_start_clock(cs) == 200000

    def test_st_zero_ignores(self):
        cs = [make_competitor(1, st=0), make_competitor(2, st=0)]
        assert race_start_clock(cs) is None


class TestRaceInProgress:
    def test_coureur_en_course(self):
        cs = [make_competitor(1, st=100000, stat=0), make_competitor(2, st=200000, stat=1, rt=5000)]
        assert race_in_progress(cs, NOW) is True

    def test_tous_arrives(self):
        cs = [make_competitor(1, st=100000, stat=1, rt=5000)]
        assert race_in_progress(cs, NOW) is False

    def test_statut_definitif_pas_en_course(self):
        cs = [make_competitor(1, st=100000, stat=STAT_MP)]
        assert race_in_progress(cs, NOW) is False


class TestRaceEndClock:
    def test_max_st_rt_des_arrives(self):
        c1 = make_competitor(1, st=200000, rt=5000, stat=STAT_OK)
        c2 = make_competitor(2, st=300000, rt=10000, stat=STAT_OK)
        assert race_end_clock([c1, c2]) == 310000

    def test_ignore_non_arrives(self):
        c1 = make_competitor(1, st=200000, rt=5000, stat=STAT_OK)
        c2 = make_competitor(2, st=200000, rt=0, stat=STAT_DNF)
        assert race_end_clock([c1, c2]) == 205000

    def test_aucun_arrive(self):
        cs = [make_competitor(1, st=100000, stat=STAT_DNS)]
        assert race_end_clock(cs) is None


class TestRaceState:
    def test_finished_sans_en_course_ni_en_attente(self):
        cs = [make_runner(1, group='arrives'), make_runner(2, group='termine')]
        assert race_state(cs, NOW, race_start=100000) == 'finished'

    def test_upcoming_premier_depart_futur(self):
        cs = [make_runner(1, group='en_attente')]
        assert race_state(cs, NOW, race_start=500000) == 'upcoming'

    def test_upcoming_sans_depart(self):
        c = make_runner(1, group='en_attente')
        c.st = 0
        assert race_state([c], NOW, race_start=None) == 'upcoming'

    def test_finished_prime_sur_upcoming(self):
        cs = [make_runner(1, group='arrives'), make_runner(2, group='termine')]
        assert race_state(cs, NOW, race_start=None) == 'finished'

    def test_live_avec_coureur_en_course(self):
        cs = [make_runner(1, group='en_course'), make_runner(2, group='arrives')]
        assert race_state(cs, NOW, race_start=100000) == 'live'

    def test_live_avec_attente_restante(self):
        cs = [make_runner(1, group='arrives'), make_runner(2, group='en_attente')]
        assert race_state(cs, NOW, race_start=100000) == 'live'


# ══════════════════════════════════════════════════════════════════════════════
# rank_live
# ══════════════════════════════════════════════════════════════════════════════

class TestRankLive:
    def _rank(self, competitors, radio_map=None, controls=None):
        return rank_live(competitors, radio_map or {}, NOW, controls or [])

    def test_heure_depart_passee_en_course(self):
        c = make_competitor(1, st=100000)
        self._rank([c])
        assert c.live_group == 'en_course'

    def test_heure_depart_future_en_attente(self):
        c = make_competitor(1, st=500000)
        self._rank([c])
        assert c.live_group == 'en_attente'

    def test_st_zero_en_attente(self):
        c = make_competitor(1, st=0)
        self._rank([c])
        assert c.live_group == 'en_attente'

    def test_sans_info_virtuellement_en_tete_avant_premier_radio(self):
        # N est parti depuis peu (écoulé 100 < 5000 au 1er poste radio) → reste devant
        n = make_competitor(1, st=431900)
        i = make_competitor(2, st=431900)
        radio_map = {2: {101: 5000}}
        ranked = self._rank([n, i], radio_map, [
            {'ctrl_id': 101, 'ctrl_name': '1-101'},
            {'ctrl_id': 102, 'ctrl_name': '2-102'},
        ])
        assert [r.id for r in ranked] == [1, 2]
        assert n.live_rank == 1 and i.live_rank == 2

    def test_sans_info_descend_derriere_informe(self):
        # N court depuis longtemps (écoulé 52000 > 5000 au 1er poste radio) → passe derrière
        n = make_competitor(1, st=380000)
        i = make_competitor(2, st=380000)
        radio_map = {2: {101: 5000}}
        ranked = self._rank([n, i], radio_map, [
            {'ctrl_id': 101, 'ctrl_name': '1-101'},
            {'ctrl_id': 102, 'ctrl_name': '2-102'},
        ])
        assert [r.id for r in ranked] == [2, 1]
        assert i.live_rank == 1

    def test_sans_controls_seq_tri_par_st(self):
        # Sans ordre de circuit : personne n'a d'info de position → tri par st
        a = make_competitor(1, st=200000)
        b = make_competitor(2, st=300000)
        c = make_competitor(3, st=250000)
        radio_map = {3: {101: 5000}}
        ranked = self._rank([a, b, c], radio_map)
        assert [r.id for r in ranked] == [1, 3, 2]
        assert a.live_rank == 1

    def test_progression_nb_postes(self):
        fast = make_competitor(1, st=200000)   # position 2 (postes 101, 102)
        slow = make_competitor(2, st=200000)   # position 1 (poste 101)
        radio_map = {1: {101: 3000, 102: 6000}, 2: {101: 3000}}
        ranked = self._rank([fast, slow], radio_map, [
            {'ctrl_id': 101, 'ctrl_name': '1-101'},
            {'ctrl_id': 102, 'ctrl_name': '2-102'},
            {'ctrl_id': 103, 'ctrl_name': '3-103'},
        ])
        assert [r.id for r in ranked] == [1, 2]
        assert fast.live_rank == 1
        assert fast.progress_pos == 2
        assert slow.progress_pos == 1

    def test_egalite_progression_temps_au_dernier_poste(self):
        rapide = make_competitor(1, st=200000)
        lent = make_competitor(2, st=200000)
        radio_map = {1: {101: 3000, 102: 6000}, 2: {101: 3000, 102: 9000}}
        ranked = self._rank([rapide, lent], radio_map, [
            {'ctrl_id': 101, 'ctrl_name': '1-101'},
            {'ctrl_id': 102, 'ctrl_name': '2-102'},
        ])
        assert [r.id for r in ranked] == [1, 2]
        assert rapide.last_time == 6000

    def test_progress_pos_position_reelle_du_poste(self):
        """progress_pos = position du poste dans le parcours, pas le nombre de poinçons."""
        c = make_competitor(1, st=100000)
        radio_map = {1: {103: 5000}}
        controls = [{'ctrl_id': cid, 'ctrl_name': str(i)}
                    for i, cid in enumerate([101, 102, 103, 104, 105, 106, 107, 108, 109], start=1)]
        self._rank([c], radio_map, controls)
        assert c.progress_pos == 3
        assert c.n_punches == 1

    def test_progress_pos_ignore_poincon_hors_parcours(self):
        c = make_competitor(1, st=100000)
        radio_map = {1: {150: 2000, 103: 6000}}
        controls = [{'ctrl_id': cid, 'ctrl_name': str(i)}
                    for i, cid in enumerate([101, 102, 103], start=1)]
        self._rank([c], radio_map, controls)
        assert c.progress_pos == 3
        assert c.last_ctrl == 103

    def test_progress_pos_zero_sans_poincon(self):
        c = make_competitor(1, st=100000)
        self._rank([c])
        assert c.progress_pos == 0

    def test_first_radio_time_temps_au_poste_le_moins_avance(self):
        c = make_competitor(1, st=100000)
        radio_map = {1: {101: 3000, 103: 9000}}
        controls = [{'ctrl_id': cid, 'ctrl_name': str(i)}
                    for i, cid in enumerate([101, 102, 103], start=1)]
        self._rank([c], radio_map, controls)
        assert c.first_radio_time == 3000
        assert c.last_time == 9000

    def test_tri_informe_plus_avance_dabord(self):
        a = make_competitor(1, st=200000)   # position 2
        b = make_competitor(2, st=200000)   # position 1
        radio_map = {1: {101: 3000, 102: 6000}, 2: {101: 1000}}
        ranked = self._rank([a, b], radio_map, [
            {'ctrl_id': 101, 'ctrl_name': '1-101'},
            {'ctrl_id': 102, 'ctrl_name': '2-102'},
            {'ctrl_id': 103, 'ctrl_name': '3-103'},
        ])
        assert [r.id for r in ranked] == [1, 2]

    def test_dernier_poste_pointe_groupe_valid_gec(self):
        """Dernier poste du parcours pointé (radio) → groupe valid_gec."""
        c = make_competitor(1, st=100000)
        radio_map = {1: {101: 3000, 102: 6000, 103: 9000}}
        controls = [{'ctrl_id': cid, 'ctrl_name': str(i)}
                    for i, cid in enumerate([101, 102, 103], start=1)]
        ranked = self._rank([c], radio_map, controls)
        assert c.live_group == 'valid_gec'
        assert [r.id for r in ranked] == [1]
        assert c.live_rank == 1

    def test_avant_dernier_poste_reste_en_course(self):
        c = make_competitor(1, st=100000)
        radio_map = {1: {101: 3000, 102: 6000}}
        controls = [{'ctrl_id': cid, 'ctrl_name': str(i)}
                    for i, cid in enumerate([101, 102, 103], start=1)]
        self._rank([c], radio_map, controls)
        assert c.live_group == 'en_course'

    def test_valid_gec_pas_sans_ordre_de_circuit(self):
        """Sans controls_seq, impossible de savoir que le parcours est terminé."""
        c = make_competitor(1, st=100000)
        radio_map = {1: {101: 3000, 102: 6000, 103: 9000}}
        self._rank([c], radio_map)
        assert c.live_group == 'en_course'

    def test_valid_gec_tries_par_temps_au_dernier_poste(self):
        rapide = make_competitor(1, st=200000)
        lent = make_competitor(2, st=200000)
        radio_map = {1: {101: 3000, 102: 6000, 103: 8000},
                     2: {101: 3000, 102: 6000, 103: 11000}}
        controls = [{'ctrl_id': cid, 'ctrl_name': str(i)}
                    for i, cid in enumerate([101, 102, 103], start=1)]
        ranked = self._rank([rapide, lent], radio_map, controls)
        assert [r.id for r in ranked] == [1, 2]
        assert rapide.live_group == 'valid_gec'
        assert rapide.live_rank == 1
        assert lent.live_rank == 2

    def test_valid_gec_separe_du_groupe_en_course(self):
        """Le groupe valid_gec s'affiche après en_course, rangs séparés."""
        ec = make_competitor(1, st=100000)          # en course (position 2)
        vg = make_competitor(2, st=100000)          # valid_gec (dernier poste)
        radio_map = {1: {101: 3000, 102: 6000},
                     2: {101: 3000, 102: 6000, 103: 9000}}
        controls = [{'ctrl_id': cid, 'ctrl_name': str(i)}
                    for i, cid in enumerate([101, 102, 103], start=1)]
        ranked = self._rank([ec, vg], radio_map, controls)
        assert [r.live_group for r in ranked] == ['en_course', 'valid_gec']
        assert ec.live_rank == 1 and vg.live_rank == 1

    def test_arrives_tries_par_rt(self):
        a = make_competitor(1, st=100000, stat=STAT_OK, rt=6000)
        b = make_competitor(2, st=100000, stat=STAT_OK, rt=5000)
        ranked = self._rank([a, b])
        assert [r.id for r in ranked] == [2, 1]
        assert a.live_group == 'arrives' and a.live_rank == 2

    def test_prel_ok_va_en_valid_gec(self):
        """Résultat préliminaire (arrivée radio, carte non lue — prel=true)
        → groupe valid_gec, même avec stat=1 et rt>0."""
        c = make_competitor(1, st=100000, stat=STAT_OK, rt=6000, prel=True)
        self._rank([c])
        assert c.live_group == 'valid_gec'
        assert c.live_rank == 1

    def test_prel_ok_valid_gec_sans_ordre_de_circuit(self):
        """Le passage en valid_gec ne dépend pas de progress_pos : prel=true
        signifie que le parcours est terminé."""
        c = make_competitor(1, st=100000, stat=STAT_OK, rt=6000, prel=True)
        self._rank([c], {1: {101: 3000, 102: 6000}})
        assert c.live_group == 'valid_gec'

    def test_prel_false_ok_reste_arrives(self):
        """Sans prel (résultat officiel) : stat=1 + rt>0 → arrives."""
        c = make_competitor(1, st=100000, stat=STAT_OK, rt=6000, prel=False)
        self._rank([c])
        assert c.live_group == 'arrives'
        assert c.live_rank == 1

    def test_prel_true_puis_officiel_passe_en_arrives(self):
        """Transition arrivée radio → lecture GEC : prel retiré au diff
        suivant, le coureur passe de valid_gec à arrives."""
        c = make_competitor(1, st=100000, stat=STAT_OK, rt=6000, prel=True)
        self._rank([c])
        assert c.live_group == 'valid_gec'
        c.prel = False
        self._rank([c])
        assert c.live_group == 'arrives'

    def test_prel_trie_par_temps_au_dernier_poste(self):
        """Deux préliminaires : tri comme valid_gec (temps au dernier poste)."""
        rapide = make_competitor(1, st=200000, stat=STAT_OK, rt=8000, prel=True)
        lent   = make_competitor(2, st=200000, stat=STAT_OK, rt=11000, prel=True)
        radio_map = {1: {101: 3000, 102: 6000, 103: 8000},
                     2: {101: 3000, 102: 6000, 103: 11000}}
        controls = [{'ctrl_id': cid, 'ctrl_name': str(i)}
                    for i, cid in enumerate([101, 102, 103], start=1)]
        ranked = self._rank([rapide, lent], radio_map, controls)
        assert [r.id for r in ranked] == [1, 2]
        assert rapide.live_group == 'valid_gec' and rapide.live_rank == 1
        assert lent.live_group == 'valid_gec' and lent.live_rank == 2

    def test_rt_negatif_stat_ok_va_dans_arrives_sans_rang(self):
        c = make_competitor(1, st=100000, stat=STAT_OK, rt=-500)
        self._rank([c])
        assert c.live_group == 'arrives'
        assert c.live_rank is None
        assert c.neg_time is True

    def test_rt_negatif_statut_definitif_reste_termine(self):
        c = make_competitor(1, st=100000, stat=STAT_DNF, rt=-500)
        self._rank([c])
        assert c.live_group == 'termine'
        assert c.live_rank is None

    def test_arrive_negatif_au_milieu_rangs_sequentiels(self):
        neg = make_competitor(1, st=100000, stat=STAT_OK, rt=5500)
        neg.neg_time = True
        a = make_competitor(2, st=100000, stat=STAT_OK, rt=5000)
        b = make_competitor(3, st=100000, stat=STAT_OK, rt=6000)
        ranked = self._rank([neg, a, b])
        assert [r.id for r in ranked] == [2, 1, 3]
        assert a.live_rank == 1
        assert neg.live_rank is None
        assert b.live_rank == 3

    def test_en_course_troncon_negatif_sans_rang(self):
        c = make_competitor(1, st=100000, stat=0)
        c.neg_time = True
        self._rank([c])
        assert c.live_group == 'en_course'
        assert c.live_rank is None

    def test_ordre_finished_done_waiting(self):
        c_dnf = make_competitor(1, st=100000, stat=STAT_DNF, name='BBB')
        c_dns = make_competitor(2, st=900000, stat=STAT_DNS, name='CCC')
        c_mp  = make_competitor(3, st=100000, stat=STAT_MP, name='AAA')
        c_fin = make_competitor(4, st=50000, stat=STAT_OK, rt=4000)
        c_wait = make_competitor(5, st=900000)
        ranked = self._rank([c_dnf, c_dns, c_mp, c_fin, c_wait])
        assert [r.live_group for r in ranked] == ['arrives', 'en_attente', 'termine', 'termine', 'termine']
        # PM avant Abandon avant DNS, puis par nom
        done = [r.id for r in ranked if r.live_group == 'termine']
        assert done == [3, 1, 2]

    def test_mp_avec_poincons_reste_definitif(self):
        c = make_competitor(1, st=100000, stat=STAT_MP)
        radio_map = {1: {101: 5000}}
        self._rank([c], radio_map)
        assert c.live_group == 'termine'

    def test_mp_rt_sentinelle_non_marque_negatif(self):
        """PM non classé (rt=-1) avec poinçons monotones → pas de temps
        négatif, malgré la sentinelle rt=-1."""
        c = make_competitor(1, st=100000, stat=STAT_MP, rt=-1)
        self._rank([c], {1: {101: 3000, 102: 6000}}, CONTROLS)
        assert c.neg_time is False
        assert c.live_group == 'termine'

    def test_occ_peut_etre_en_course(self):
        c = make_competitor(1, st=100000, stat=STAT_OCC)
        c.is_ok = False
        self._rank([c])
        assert c.live_group == 'en_course'

    def test_annotations(self):
        c = make_competitor(1, st=100000)
        radio_map = {1: {101: 3000, 102: 9000}}
        self._rank([c], radio_map)
        assert c.n_punches == 2
        assert c.last_ctrl == 102
        assert c.last_time == 9000
        assert c.last_punch_clock == 109000   # st + temps au dernier poste

    def test_poincons_non_positifs_ignores(self):
        c = make_competitor(1, st=100000)
        radio_map = {1: {101: -1, 102: 0, 103: 5000}}
        self._rank([c], radio_map)
        assert c.n_punches == 1
        assert c.last_ctrl == 103

    def test_dernier_poste_selon_ordre_du_circuit(self):
        """Le dernier poste suit l'ordre du circuit, pas l'id du poste."""
        c = make_competitor(1, st=100000)
        radio_map = {1: {53: 210, 31: 310, 179: 520, 52: 630, 54: 660}}
        controls = [
            {'ctrl_id': 53, 'ctrl_name': 'P53'},
            {'ctrl_id': 55, 'ctrl_name': 'P55'},
            {'ctrl_id': 31, 'ctrl_name': 'P31'},
            {'ctrl_id': 179, 'ctrl_name': 'P179'},
            {'ctrl_id': 52, 'ctrl_name': 'P52'},
            {'ctrl_id': 54, 'ctrl_name': 'P54'},
        ]
        self._rank([c], radio_map, controls)
        assert c.n_punches == 5
        assert c.last_ctrl == 54
        assert c.last_time == 660
        assert c.last_punch_clock == 100660

    def test_dernier_poste_sans_ordre_du_circuit_fall_back_temps(self):
        """Sans controls_seq, le poste le plus avancé reste déterminé."""
        c = make_competitor(1, st=100000)
        radio_map = {1: {53: 210, 54: 660}}
        self._rank([c], radio_map)
        assert c.last_ctrl == 54
        assert c.last_time == 660


# ══════════════════════════════════════════════════════════════════════════════
# mark_negative_times
# ══════════════════════════════════════════════════════════════════════════════

CONTROLS = [
    {'ctrl_id': 101, 'ctrl_name': '1-101'},
    {'ctrl_id': 102, 'ctrl_name': '2-102'},
]


class TestMarkNegativeTimes:
    def _mark(self, competitor, radio_map=None, controls=None):
        mark_negative_times([competitor], controls or CONTROLS, radio_map or {})
        return competitor.neg_time

    def test_troncon_radio_negatif(self):
        c = make_competitor(1, st=100000)
        assert self._mark(c, {1: {101: 6000, 102: 3000}}) is True

    def test_arrivee_avant_dernier_poste(self):
        c = make_competitor(1, st=100000, stat=STAT_OK, rt=2000)
        assert self._mark(c, {1: {101: 5000, 102: 7000}}) is True

    def test_rt_negatif(self):
        c = make_competitor(1, st=100000, stat=STAT_OK, rt=-500)
        assert self._mark(c) is True

    def test_rt_sentinelle_non_classifie_pas_negatif(self):
        """PM/DNF avec rt=-1 (sentinelle « non classé ») et poinçons
        monotones → pas de temps négatif."""
        c = make_competitor(1, st=100000, stat=STAT_MP, rt=-1)
        assert self._mark(c, {1: {101: 3000, 102: 6000}}) is False

    def test_rt_sentinelle_dnf_pas_negatif(self):
        c = make_competitor(1, st=100000, stat=STAT_DNF, rt=-1)
        assert self._mark(c, {1: {101: 3000, 102: 6000}}) is False

    def test_cas_sain(self):
        c = make_competitor(1, st=100000, stat=STAT_OK, rt=9000)
        assert self._mark(c, {1: {101: 3000, 102: 6000}}) is False

    def test_arrivee_apres_dernier_poste_saine(self):
        c = make_competitor(1, st=100000, stat=STAT_OK, rt=9000)
        assert self._mark(c, {1: {101: 3000, 102: 6000}}) is False

    def test_aucun_poincon_rt_positif_sain(self):
        c = make_competitor(1, st=100000, stat=STAT_OK, rt=5000)
        assert self._mark(c) is False

    def test_poincon_avant_depart_negatif(self):
        """Un poinçon antérieur au départ (temps relatif négatif) → neg_time."""
        c = make_competitor(1, st=100000, stat=STAT_OK, rt=9000)
        assert self._mark(c, {1: {101: 210, 102: -350}}) is True

    def test_poincon_avant_depart_unique(self):
        c = make_competitor(1, st=100000, stat=STAT_OK, rt=9000)
        assert self._mark(c, {1: {101: -350}}) is True


class TestPresumedPrestartLive:
    """OK définitif + poste attesté manquant → badge « Temps négatif » live."""

    def _mark(self, competitors, radio_map=None):
        for c in competitors:
            c.neg_time = False
        mark_presumed_prestart(competitors, CONTROLS, radio_map or {})
        return competitors

    def _ok(self, id, **kw):
        kw.setdefault('rt', 9000)
        c = make_competitor(id, stat=STAT_OK, **kw)
        c.tstat = STAT_OK
        return c

    def test_poste_atteste_manquant_marque(self):
        c1 = self._ok(1)
        c2 = self._ok(2)
        self._mark([c1, c2], {1: {101: 3000}, 2: {101: 3000, 102: 6000}})
        assert c1.neg_time is True
        assert c1.prestart_ctrls == {102}
        assert c2.neg_time is False

    def test_poste_non_atteste_non_marque(self):
        c1 = self._ok(1)
        c2 = self._ok(2)
        self._mark([c1, c2], {1: {101: 3000}, 2: {101: 3000}})
        assert c1.neg_time is False

    def test_statut_ok_non_definitif_non_marque(self):
        c1 = self._ok(1)
        c1.tstat = 0
        c2 = self._ok(2)
        self._mark([c1, c2], {1: {101: 3000}, 2: {101: 3000, 102: 6000}})
        assert c1.neg_time is False

    def test_live_sans_rang_pour_presume(self):
        """Coureur présumé → neg_time → exclu du classement live."""
        c1 = self._ok(1)
        c2 = self._ok(2, rt=8000)
        self._mark([c1, c2], {1: {101: 3000}, 2: {101: 3000, 102: 6000}})
        ranked = rank_live([c1, c2], {1: {101: 3000}, 2: {101: 3000, 102: 6000}},
                           NOW, CONTROLS)
        assert c1.live_group == 'arrives'
        assert c1.live_rank is None
        assert c2.live_rank == 1


# ══════════════════════════════════════════════════════════════════════════════
# live_results (page)
# ══════════════════════════════════════════════════════════════════════════════

class TestLiveResultsView:
    def _run(self, competitors=None, course=None, race_start=None):
        competitors = competitors or []
        cls = SimpleNamespace(id=10, name='H21')
        with patch('results.views._load_class_context',
                   return_value=(MagicMock(cid=1, name='Test'), cls,
                                 competitors, course)), \
             patch('results.views.Mopteam') as MockTeam, \
             patch('results.views._get_adjacent_classes', return_value=(None, None)), \
             patch('results.views.get_org_map', return_value={}), \
             patch('results.views.get_radio_map', return_value={}), \
             patch('results.views._controls_for', return_value=[]), \
             patch('results.views.rank_live', return_value=competitors), \
             patch('results.views.race_start_clock', return_value=race_start), \
             patch('results.views.render') as mock_render:
            MockTeam.objects.filter.return_value.exists.return_value = False
            from results.views import live_results
            live_results(rf_get(), cid=1, class_id='H21')
            _, template, ctx = mock_render.call_args[0]
            return template, ctx

    def test_page_rendue(self):
        template, ctx = self._run()
        assert template == 'results/live_results.html'
        assert 'live' in ctx and 'groups' in ctx

    def test_contexte_complet(self):
        _, ctx = self._run()
        assert ctx['current_analysis'] == 'live'
        assert ctx['race_start_clock'] is None
        assert ctx['competition'].cid == 1

    def test_circuit_utilise_meme_template(self):
        course = {'hash': 'abc12345', 'display_name': 'Circuit', 'class_ids': [10],
                  'controls_seq': [], 'classes': []}
        template, _ = self._run(course=course)
        assert template == 'results/live_results.html'

    def test_prev_next_cls_presents(self):
        prev = SimpleNamespace(id=9, name='H20')
        next_ = SimpleNamespace(id=11, name='D35')
        with patch('results.views._load_class_context',
                   return_value=(MagicMock(cid=1, name='Test'),
                                 SimpleNamespace(id=10, name='H21'), [], None)), \
             patch('results.views.Mopteam') as MockTeam, \
             patch('results.views._get_adjacent_classes', return_value=(prev, next_)), \
             patch('results.views.get_org_map', return_value={}), \
             patch('results.views.get_radio_map', return_value={}), \
             patch('results.views._controls_for', return_value=[]), \
             patch('results.views.rank_live', return_value=[]), \
             patch('results.views.race_start_clock', return_value=None), \
             patch('results.views.render') as mock_render:
            MockTeam.objects.filter.return_value.exists.return_value = False
            from results.views import live_results
            live_results(rf_get(), cid=1, class_id='H21')
            _, _, ctx = mock_render.call_args[0]
            assert ctx['prev_cls'] is prev
            assert ctx['next_cls'] is next_

    def test_prev_next_none_en_mode_circuit(self):
        course = {'hash': 'abc12345', 'display_name': 'Circuit', 'class_ids': [10],
                  'controls_seq': [], 'classes': []}
        _, ctx = self._run(course=course)
        assert ctx['prev_cls'] is None
        assert ctx['next_cls'] is None

    def test_race_state_finished_sans_coureurs(self):
        _, ctx = self._run()
        assert ctx['race_state'] == 'finished'
        assert ctx['race_end_clock'] is not None

    def test_race_state_live_avec_coureur_en_course(self):
        runner = make_runner(id=5, group='en_course')
        _, ctx = self._run(competitors=[runner], race_start=100000)
        assert ctx['race_state'] == 'live'
        assert ctx['race_end_clock'] is None

    def test_race_state_upcoming_avec_depart_futur(self):
        runner = make_runner(id=5, group='en_attente')
        with patch('results.views._load_class_context',
                   return_value=(MagicMock(cid=1, name='Test'),
                                 SimpleNamespace(id=10, name='H21'),
                                 [runner], None)), \
             patch('results.views.Mopteam') as MockTeam, \
             patch('results.views._get_adjacent_classes', return_value=(None, None)), \
             patch('results.views.get_org_map', return_value={}), \
             patch('results.views.get_radio_map', return_value={}), \
             patch('results.views._controls_for', return_value=[]), \
             patch('results.views.rank_live', return_value=[runner]), \
             patch('results.views.race_start_clock', return_value=863990), \
             patch('results.views.render') as mock_render:
            MockTeam.objects.filter.return_value.exists.return_value = False
            from results.views import live_results
            live_results(rf_get(), cid=1, class_id='H21')
            _, _, ctx = mock_render.call_args[0]
            assert ctx['race_state'] == 'upcoming'
            assert ctx['race_end_clock'] is None

    def test_relais_redirige(self):
        with patch('results.views._load_class_context',
                   return_value=(MagicMock(), MagicMock(id=10, name='H21'), [], None)), \
             patch('results.views.Mopteam') as MockTeam, \
             patch('results.views.render') as mock_render:
            MockTeam.objects.filter.return_value.exists.return_value = True
            from results.views import live_results
            resp = live_results(rf_get(), cid=1, class_id='H21')
            mock_render.assert_not_called()
            assert resp.status_code in (301, 302)

    def test_org_object_attache_aux_concurrents(self):
        runner = SimpleNamespace(id=5, org=3, org_obj=None, live_group='en_course')
        template, _ = self._run(competitors=[runner])
        assert template == 'results/live_results.html'
        # org_map est vide → org_obj reste None, mais la boucle est exécutée
        assert runner.org_obj is None

    def test_org_object_resolu_depuis_org_map(self):
        org = MagicMock(name='CLUB')
        runner = SimpleNamespace(id=5, org=3, org_obj=None, live_group='en_course')
        with patch('results.views._load_class_context',
                   return_value=(MagicMock(cid=1, name='Test'),
                                 SimpleNamespace(id=10, name='H21'),
                                 [runner], None)), \
             patch('results.views.Mopteam') as MockTeam, \
             patch('results.views._get_adjacent_classes', return_value=(None, None)), \
             patch('results.views.get_org_map', return_value={3: org}), \
             patch('results.views.get_radio_map', return_value={}), \
             patch('results.views._controls_for', return_value=[]), \
             patch('results.views.rank_live', return_value=[runner]), \
             patch('results.views.race_start_clock', return_value=None), \
             patch('results.views.render') as mock_render:
            MockTeam.objects.filter.return_value.exists.return_value = False
            from results.views import live_results
            live_results(rf_get(), cid=1, class_id='H21')
            mock_render.assert_called_once()
            assert runner.org_obj is org


# ══════════════════════════════════════════════════════════════════════════════
# api_live_results (JSON)
# ══════════════════════════════════════════════════════════════════════════════

class TestApiLiveResults:
    def _runner(self, id=1, group='en_course', rank=1):
        r = MagicMock()
        r.id = id; r.name = 'Alice'; r.org = 1; r.stat = 0
        r.status_label = 'Inconnu'; r.status_badge = 'info'
        r.live_group = group; r.live_rank = rank
        r.st = 200000; r.rt = None
        r.is_ok = False
        r.n_punches = 1; r.last_ctrl = 101
        r.last_time = 5000; r.last_punch_clock = 205000
        r.progress_pos = 3
        r.class_obj = None
        return r

    def _run(self, competitors=None, course=None, class_name='H21', race_start=180000,
             radio_map=None):
        competitors = competitors or []
        cls = SimpleNamespace(id=10, name=class_name)
        with patch('results.views._load_class_context',
                   return_value=(MagicMock(), cls, competitors, course)), \
             patch('results.views.Mopteam') as MockTeam, \
             patch('results.views.get_org_map', return_value={1: 'Club'}), \
             patch('results.views.get_radio_map', return_value=radio_map or {}), \
             patch('results.views._controls_for', return_value=[
                 {'ctrl_id': 101, 'ctrl_name': '1-101'},
                 {'ctrl_id': 102, 'ctrl_name': '2-102'},
             ]), \
             patch('results.views.rank_live', return_value=competitors), \
             patch('results.views.race_start_clock', return_value=race_start):
            MockTeam.objects.filter.return_value.exists.return_value = False
            from results.views import api_live_results
            return json.loads(api_live_results(rf_get(), cid=1, class_id='H21').content)

    def test_json_complet(self):
        data = self._run(competitors=[self._runner()])
        assert data['success'] is True
        assert 'server_now' in data
        assert data['race_start_clock'] == 180000
        assert data['is_course'] is False
        assert data['cls_name'] == 'H21'
        assert data['n_controls'] == 2
        assert data['controls'][0]['ctrl_name'] == '1-101'
        r = data['runners'][0]
        assert r['name'] == 'Alice'
        assert r['group'] == 'en_course'
        assert r['rank'] == 1
        assert r['n_punches'] == 1
        assert r['progress_pos'] == 3
        assert r['last_ctrl'] == 101
        assert r['last_punch_clock'] == 205000
        assert r['radio_punches'] == []

    def test_radio_punches_tries_et_filtres_au_parcours(self):
        r = self._runner(id=1)
        data = self._run(competitors=[r], radio_map={1: {101: 3000, 102: 6000, 150: 9000}})
        assert data['runners'][0]['radio_punches'] == [
            {'ctrl': 101, 'time': 3000},
            {'ctrl': 102, 'time': 6000},
        ]

    def test_race_state_live(self):
        data = self._run(competitors=[self._runner()])
        assert data['race_state'] == 'live'
        assert data['race_end_clock'] is None

    def test_race_state_finished_avec_dernier_arrive(self):
        r = self._runner(id=1, group='arrives')
        r.is_ok = True; r.rt = 5000
        data = self._run(competitors=[r])
        assert data['race_state'] == 'finished'
        assert data['race_end_clock'] == 200000 + 5000

    def test_race_state_upcoming_depart_futur(self):
        r = self._runner(id=1, group='en_attente')
        data = self._run(competitors=[r], race_start=863990)
        assert data['race_state'] == 'upcoming'
        assert data['race_end_clock'] is None

    def test_neg_time_renvoye_avec_rt_negatif(self):
        r = self._runner(id=1, group='arrives')
        r.stat = STAT_OK; r.rt = -500; r.neg_time = True
        data = self._run(competitors=[r])
        assert data['runners'][0]['rt'] == -500
        assert data['runners'][0]['neg_time'] is True

    def test_neg_time_faux_par_defaut(self):
        data = self._run(competitors=[self._runner()])
        assert data['runners'][0]['neg_time'] is False

    def test_json_course_inclut_categorie(self):
        course = {'hash': 'abc12345', 'display_name': 'Circuit',
                  'class_ids': [10], 'controls_seq': [], 'classes': []}
        runner = self._runner()
        runner.class_obj = SimpleNamespace(id=10, name='H21')
        data = self._run(competitors=[runner], course=course)
        assert data['is_course'] is True
        assert data['course']['hash'] == 'abc12345'
        assert data['runners'][0]['class_name'] == 'H21'

    def test_relais_422(self):
        with patch('results.views._load_class_context',
                   return_value=(MagicMock(), MagicMock(id=10, name='H21'), [], None)), \
             patch('results.views.Mopteam') as MockTeam, \
             patch('results.views.render') as mock_render:
            MockTeam.objects.filter.return_value.exists.return_value = True
            from results.views import api_live_results
            resp = api_live_results(rf_get(), cid=1, class_id='H21')
            assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# URLs
# ══════════════════════════════════════════════════════════════════════════════

class TestLiveUrls:
    def test_reverse_live_classe(self):
        assert reverse('results:live', kwargs={'cid': 1, 'class_id': 'H21'}) == '/competition/1/class/H21/live/'

    def test_reverse_live_circuit(self):
        assert reverse('results:course_live', kwargs={'cid': 1, 'class_id': 'abc12345'}) == '/competition/1/course/abc12345/live/'

    def test_reverse_api_live(self):
        assert reverse('results:api_live_results', kwargs={'cid': 1, 'class_id': 'H21'}) == '/api/1/class/H21/live/'
        assert reverse('results:api_course_live_results', kwargs={'cid': 1, 'class_id': 'abc12345'}) == '/api/1/course/abc12345/live/'

    def test_resolve_live(self):
        from results.views import live_results, api_live_results
        assert resolve('/competition/1/class/H21/live/').func == live_results
        assert resolve('/api/1/class/H21/live/').func == api_live_results