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
    rank_live, race_start_clock, race_in_progress, format_clock,
)

NOW = datetime(2025, 8, 14, 12, 0, 0)   # 12:00:00 → 432000 (1/10 s depuis minuit)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_competitor(id=1, st=100000, stat=0, rt=0, name='Coureur', org=1, cls=10):
    c = MagicMock()
    c.id = id; c.st = st; c.stat = stat; c.rt = rt
    c.name = name; c.org = org; c.cls = cls
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


# ══════════════════════════════════════════════════════════════════════════════
# rank_live
# ══════════════════════════════════════════════════════════════════════════════

class TestRankLive:
    def _rank(self, competitors, radio_map=None):
        return rank_live(competitors, radio_map or {}, NOW)

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

    def test_sans_poincon_virtuellement_en_tete(self):
        a = make_competitor(1, st=200000)
        b = make_competitor(2, st=300000)
        c = make_competitor(3, st=250000)   # parti plus tôt que b, avec poinçons
        radio_map = {3: {101: 5000}}
        ranked = self._rank([a, b, c], radio_map)
        # sans poinçon d'abord (tri par st), puis ceux qui ont pointé
        assert [r.id for r in ranked] == [1, 2, 3]
        assert a.live_rank == 1 and b.live_rank == 2

    def test_progression_nb_postes(self):
        fast = make_competitor(1, st=200000)   # 2 postes
        slow = make_competitor(2, st=200000)   # 1 poste
        radio_map = {1: {101: 3000, 102: 6000}, 2: {101: 3000}}
        ranked = self._rank([fast, slow], radio_map)
        assert [r.id for r in ranked] == [1, 2]
        assert fast.live_rank == 1

    def test_egalite_progression_temps_au_dernier_poste(self):
        rapide = make_competitor(1, st=200000)
        lent = make_competitor(2, st=200000)
        radio_map = {1: {101: 3000, 102: 6000}, 2: {101: 3000, 102: 9000}}
        ranked = self._rank([rapide, lent], radio_map)
        assert [r.id for r in ranked] == [1, 2]
        assert rapide.last_time == 6000

    def test_arrives_tries_par_rt(self):
        a = make_competitor(1, st=100000, stat=STAT_OK, rt=6000)
        b = make_competitor(2, st=100000, stat=STAT_OK, rt=5000)
        ranked = self._rank([a, b])
        assert [r.id for r in ranked] == [2, 1]
        assert a.live_group == 'arrives' and a.live_rank == 2

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


# ══════════════════════════════════════════════════════════════════════════════
# live_results (page)
# ══════════════════════════════════════════════════════════════════════════════

class TestLiveResultsView:
    def _run(self, competitors=None, course=None):
        competitors = competitors or []
        cls = SimpleNamespace(id=10, name='H21')
        with patch('results.views._load_class_context',
                   return_value=(MagicMock(cid=1, name='Test'), cls,
                                 competitors, course)), \
             patch('results.views.Mopteam') as MockTeam, \
             patch('results.views.get_org_map', return_value={}), \
             patch('results.views.get_radio_map', return_value={}), \
             patch('results.views._controls_for', return_value=[]), \
             patch('results.views.rank_live', return_value=competitors), \
             patch('results.views.race_start_clock', return_value=None), \
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
        r.class_obj = None
        return r

    def _run(self, competitors=None, course=None, class_name='H21'):
        competitors = competitors or []
        cls = SimpleNamespace(id=10, name=class_name)
        with patch('results.views._load_class_context',
                   return_value=(MagicMock(), cls, competitors, course)), \
             patch('results.views.Mopteam') as MockTeam, \
             patch('results.views.get_org_map', return_value={1: 'Club'}), \
             patch('results.views.get_radio_map', return_value={}), \
             patch('results.views._controls_for', return_value=[
                 {'ctrl_id': 101, 'ctrl_name': '1-101'},
                 {'ctrl_id': 102, 'ctrl_name': '2-102'},
             ]), \
             patch('results.views.rank_live', return_value=competitors), \
             patch('results.views.race_start_clock', return_value=180000):
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
        assert r['last_ctrl'] == 101
        assert r['last_punch_clock'] == 205000

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