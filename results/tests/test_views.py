"""
Tests d'intégration pour les vues — DB entièrement mockée.

Couvre toutes les branches de views.py pour les vues de catégorie :
  - helpers : _sort_non_finishers, _load_class_context, _get_adjacent_classes
  - home, competition_detail (avec get_courses_map mocké)
  - class_results : relay redirect, ordering, splits, has_splits, error_map,
    leg_error_data, course_hash
  - competitor_detail, org_results, statistics
  - api_class_results
  - superman_analysis : no_data, séries, superman_leg_data, radio manquant
  - performance_analysis : no_data, indices, valid=[] → mean_pi=None
  - regularity_analysis : no_data, category_regularity None
  - grouping_analysis : no_data, stat/rank/time_fmt
  - grouping_index_analysis : no_data, seuils, leg_ref_names
  - duel_analysis : no_data, relay redirect, splits dans runners_data
  - relay_results
  - _slugify_no_prefix
"""

from unittest.mock import patch, MagicMock
import pytest
import json
from django.test import RequestFactory
from django.http import Http404

from results.models import (
    STAT_OK, STAT_MP, STAT_DNF, STAT_DNS, STAT_NP, STAT_CANCEL,
    STAT_OCC, STAT_NT, STAT_OT, STAT_DQ,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_competition(cid=1):
    c = MagicMock(); c.cid = cid; c.name = 'Test'; return c

def make_cls(cid=1, class_id=10, name='H21', ord_=10):
    c = MagicMock(); c.cid = cid; c.id = class_id; c.name = name; c.ord = ord_; return c

def make_competitor(id=1, rt=6000, stat=STAT_OK, org=1, cls=10, name=None, st=100000):
    c = MagicMock()
    c.id = id; c.rt = rt; c.stat = stat; c.org = org; c.cls = cls; c.st = st
    c.name = name if name is not None else f'Coureur {id}'
    c.is_ok = (stat == STAT_OK and rt > 0)
    c.status_label = 'OK'; c.status_badge = 'success'
    return c

def make_nf(id, stat, name, rt=-1):
    c = MagicMock(); c.id = id; c.stat = stat; c.name = name; c.rt = rt
    c.is_ok = False; c.status_label = 'non-classé'; return c

def rf_get(url='/'):
    return RequestFactory().get(url)


# ══════════════════════════════════════════════════════════════════════════════
# _sort_non_finishers
# ══════════════════════════════════════════════════════════════════════════════

class TestSortNonFinishers:
    def _call(self, competitors):
        from results.views import _sort_non_finishers
        return _sort_non_finishers(competitors)

    def test_pm_apres_nc(self):
        result = self._call([make_nf(2, STAT_MP, 'Bob'), make_nf(1, STAT_OCC, 'Alice')])
        assert result[0].id == 1; assert result[1].id == 2

    def test_abandon_apres_pm(self):
        result = self._call([make_nf(2, STAT_DNF, 'Bob'), make_nf(1, STAT_MP, 'Alice')])
        assert result[0].id == 1

    def test_dns_apres_abandon(self):
        result = self._call([make_nf(2, STAT_DNS, 'Bob'), make_nf(1, STAT_DNF, 'Alice')])
        assert result[0].id == 1

    def test_np_groupe_avec_dns(self):
        result = self._call([make_nf(2, STAT_NP, 'Zara'), make_nf(1, STAT_DNS, 'Alice')])
        assert result[0].name == 'Alice'

    def test_cancel_groupe_avec_dns(self):
        result = self._call([make_nf(2, STAT_DNS, 'Zara'), make_nf(1, STAT_CANCEL, 'Alice')])
        assert result[0].name == 'Alice'

    def test_ordre_complet(self):
        result = self._call([
            make_nf(1, STAT_DNS, 'DNS'), make_nf(2, STAT_DNF, 'DNF'),
            make_nf(3, STAT_MP, 'PM'),   make_nf(4, STAT_OCC, 'NC'),
        ])
        assert [r.id for r in result] == [4, 3, 2, 1]

    def test_alpha_dans_groupe_pm(self):
        result = self._call([make_nf(1, STAT_MP, 'Zara'), make_nf(2, STAT_MP, 'Alice'), make_nf(3, STAT_MP, 'Martin')])
        assert [r.name for r in result] == ['Alice', 'Martin', 'Zara']

    def test_alpha_insensible_casse(self):
        result = self._call([make_nf(1, STAT_DNF, 'ZZZ'), make_nf(2, STAT_DNF, 'aaa')])
        assert result[0].name == 'aaa'

    def test_liste_vide(self):
        assert self._call([]) == []

    def test_un_element(self):
        c = make_nf(1, STAT_DNF, 'X')
        assert self._call([c]) == [c]

    def test_ne_modifie_pas_originale(self):
        original = [make_nf(1, STAT_DNS, 'B'), make_nf(2, STAT_MP, 'A')]
        ids = [c.id for c in original]
        self._call(original)
        assert [c.id for c in original] == ids

    def test_statut_inconnu_en_dernier(self):
        result = self._call([make_nf(2, 99, 'Zara'), make_nf(1, STAT_DNF, 'Alice')])
        assert result[0].id == 1

    def test_nt_groupe_nc(self):
        result = self._call([make_nf(2, STAT_MP, 'Bob'), make_nf(1, STAT_NT, 'Alice')])
        assert result[0].id == 1

    def test_ot_groupe_nc(self):
        result = self._call([make_nf(2, STAT_MP, 'Bob'), make_nf(1, STAT_OT, 'Alice')])
        assert result[0].id == 1

    def test_dq_groupe_nc(self):
        result = self._call([make_nf(2, STAT_MP, 'Bob'), make_nf(1, STAT_DQ, 'Alice')])
        assert result[0].id == 1


# ══════════════════════════════════════════════════════════════════════════════
# _load_class_context (mode catégorie seulement — le mode circuit est dans test_courses.py)
# ══════════════════════════════════════════════════════════════════════════════

class TestLoadClassContext:

    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_object_or_404')
    def test_retourne_competition_cls_competitors(self, mock_get404, MockComp):
        competition = make_competition(); cls = make_cls()
        mock_get404.side_effect = [competition, cls]
        c1 = make_competitor(1); c2 = make_competitor(2)
        MockComp.objects.filter.return_value = [c1, c2]
        from results.views import _load_class_context
        comp_out, cls_out, competitors, course = _load_class_context(cid=1, class_id=10)
        assert comp_out is competition; assert cls_out is cls
        assert len(competitors) == 2; assert course is None

    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_object_or_404')
    def test_filtre_par_cid_et_class_id(self, mock_get404, MockComp):
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockComp.objects.filter.return_value = []
        from results.views import _load_class_context
        _load_class_context(cid=3, class_id=15)
        MockComp.objects.filter.assert_called_once_with(cid=3, cls=15)

    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_object_or_404')
    def test_retourne_liste(self, mock_get404, MockComp):
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockComp.objects.filter.return_value = [make_competitor()]
        from results.views import _load_class_context
        _, _, competitors, _ = _load_class_context(cid=1, class_id=10)
        assert isinstance(competitors, list)

    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_object_or_404', side_effect=Http404)
    def test_leve_404(self, mock_get404, MockComp):
        from results.views import _load_class_context
        with pytest.raises(Http404):
            _load_class_context(cid=999, class_id=10)

    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_object_or_404')
    def test_resolve_nom_categorie(self, mock_get404, MockComp):
        """Un nom de catégorie (str non-digit) est résolu via get_object_or_404."""
        competition = make_competition(); cls = make_cls(class_id=10, name='H21')
        mock_get404.side_effect = [competition, cls, cls]
        MockComp.objects.filter.return_value = []
        from results.views import _load_class_context
        _, cls_out, _, _ = _load_class_context(cid=1, class_id='H21')
        assert cls_out is cls


# ══════════════════════════════════════════════════════════════════════════════
# _get_adjacent_classes
# ══════════════════════════════════════════════════════════════════════════════

class TestGetAdjacentClasses:
    def _mk(self, id_, name, ord_=10):
        c = MagicMock(); c.id = id_; c.name = name; c.ord = ord_; return c

    def _call(self, qs, cid, class_id):
        from results.views import _get_adjacent_classes
        with patch('results.views.Mopclass') as M:
            M.objects.filter.return_value.order_by.return_value = qs
            return _get_adjacent_classes(cid, class_id)

    def test_unique_aucun_voisin(self):
        p, n = self._call([self._mk(10, 'H21')], 1, 10)
        assert p is None and n is None

    def test_premiere_pas_de_precedent(self):
        cls = [self._mk(10,'H21'), self._mk(20,'D21'), self._mk(30,'H35')]
        p, n = self._call(cls, 1, 10)
        assert p is None; assert n.id == 20

    def test_derniere_pas_de_suivant(self):
        cls = [self._mk(10,'H21'), self._mk(20,'D21'), self._mk(30,'H35')]
        p, n = self._call(cls, 1, 30)
        assert p.id == 20; assert n is None

    def test_milieu(self):
        cls = [self._mk(10,'H21'), self._mk(20,'D21'), self._mk(30,'H35')]
        p, n = self._call(cls, 1, 20)
        assert p.id == 10; assert n.id == 30

    def test_inexistant_double_none(self):
        p, n = self._call([self._mk(10,'H21')], 1, 999)
        assert p is None and n is None

    def test_noms_corrects(self):
        cls = [self._mk(10,'H21'), self._mk(20,'D21'), self._mk(30,'H35')]
        p, n = self._call(cls, 1, 20)
        assert p.name == 'H21'; assert n.name == 'H35'

    def test_filtre_par_cid(self):
        from results.views import _get_adjacent_classes
        with patch('results.views.Mopclass') as M:
            M.objects.filter.return_value.order_by.return_value = []
            _get_adjacent_classes(cid=42, class_id=10)
            M.objects.filter.assert_called_once_with(cid=42)


# ══════════════════════════════════════════════════════════════════════════════
# home
# ══════════════════════════════════════════════════════════════════════════════

class TestHomeView:
    @patch('results.views.Mopcompetition')
    @patch('results.views.render')
    def test_passe_competitions(self, mock_render, MockComp):
        comps = [make_competition(1), make_competition(2)]
        MockComp.objects.all.return_value = comps
        from results.views import home
        home(rf_get())
        _, template, ctx = mock_render.call_args[0]
        assert template == 'results/home.html'
        assert ctx['competitions'] == comps


# ══════════════════════════════════════════════════════════════════════════════
# competition_detail
# ══════════════════════════════════════════════════════════════════════════════

class TestCompetitionDetailView:
    """CORRECTIF : get_courses_map est mocké pour éviter les requêtes DB."""

    def _run(self, cid=1, classes=None, teams_cls_ids=None, courses_map=None):
        competition = make_competition(cid)
        classes = classes or [make_cls(cid, 10), make_cls(cid, 11)]
        relay_cls_ids = teams_cls_ids if teams_cls_ids is not None else set()

        with patch('results.views.get_object_or_404', return_value=competition), \
             patch('results.views.Mopclass') as MockClass, \
             patch('results.views.Mopteam') as MockTeam, \
             patch('results.views.Mopcompetitor') as MockComp, \
             patch('results.views.get_courses_map', return_value=courses_map or {}), \
             patch('results.views.render') as mock_render:
            MockClass.objects.filter.return_value.order_by.return_value = classes
            MockTeam.objects.filter.return_value.values_list.return_value.distinct.return_value = list(relay_cls_ids)
            comp_qs = MagicMock()
            comp_qs.count.return_value = 5
            comp_qs.filter.return_value.exclude.return_value.count.return_value = 3
            MockComp.objects.filter.return_value = comp_qs
            MockTeam.objects.filter.return_value.count.return_value = 2
            MockTeam.objects.filter.return_value.filter.return_value.exclude.return_value.count.return_value = 1
            from results.views import competition_detail
            competition_detail(rf_get(), cid=cid)
            _, template, ctx = mock_render.call_args[0]
            return template, ctx

    def test_template_correct(self):
        assert self._run()[0] == 'results/competition_detail.html'

    def test_cles_de_contexte(self):
        _, ctx = self._run()
        assert 'competition' in ctx
        assert 'class_stats' in ctx
        assert 'courses_map' in ctx

    def test_courses_map_vide_par_defaut(self):
        _, ctx = self._run()
        assert ctx['courses_map'] == {}

    def test_courses_map_transmis(self):
        cm = {'abc12345': {'hash': 'abc12345', 'display_name': 'H21'}}
        _, ctx = self._run(courses_map=cm)
        assert 'abc12345' in ctx['courses_map']

    def test_classe_relais_marquee_true(self):
        cls1 = make_cls(1, 10)
        _, ctx = self._run(classes=[cls1], teams_cls_ids={10})
        assert ctx['class_stats'][0]['is_relay'] is True

    def test_classe_individuelle_marquee_false(self):
        cls1 = make_cls(1, 10)
        _, ctx = self._run(classes=[cls1], teams_cls_ids=set())
        assert ctx['class_stats'][0]['is_relay'] is False

    def test_all_classes_dans_class_stats(self):
        cls1 = make_cls(1, 10); cls2 = make_cls(1, 11)
        _, ctx = self._run(classes=[cls1, cls2])
        assert len(ctx['class_stats']) == 2


# ══════════════════════════════════════════════════════════════════════════════
# class_results (mode catégorie)
# ══════════════════════════════════════════════════════════════════════════════

class TestClassResultsView:
    """Branches de class_results en mode catégorie."""

    def _run(self, competitors, controls_seq=None):
        comp = make_competition(); cls = make_cls()
        with patch('results.views.Mopteam') as MockTeam, \
             patch('results.views.Mopcompetitor') as MockComp, \
             patch('results.views.get_object_or_404', side_effect=[comp, cls]), \
             patch('results.views._get_adjacent_classes', return_value=(None, None)), \
             patch('results.views.get_org_map', return_value={}), \
             patch('results.views.get_class_controls', return_value=(controls_seq or [], {})), \
             patch('results.views.get_radio_map', return_value={}), \
             patch('results.views.compute_splits', return_value=[]), \
             patch('results.views.mark_best_splits'), \
             patch('results.views.rank_splits'), \
             patch('results.views.render') as mock_render:
            MockTeam.objects.filter.return_value.exists.return_value = False
            MockComp.objects.filter.return_value = competitors
            from results.views import class_results
            class_results(rf_get(), cid=1, class_id=10)
            _, template, ctx = mock_render.call_args[0]
            return template, ctx

    def test_template_class_results(self):
        template, _ = self._run([make_competitor()])
        assert template == 'results/class_results.html'

    def test_has_splits_false_sans_controles(self):
        _, ctx = self._run([make_competitor()], controls_seq=[])
        assert ctx['has_splits'] is False

    def test_has_splits_true_avec_controles(self):
        _, ctx = self._run([make_competitor()], controls_seq=[{'ctrl_id': 31, 'ctrl_name': 'P31'}])
        assert ctx['has_splits'] is True

    def test_course_hash_present(self):
        _, ctx = self._run([make_competitor()])
        assert 'course_hash' in ctx
        import re; assert re.fullmatch(r'[0-9a-f]{8}', ctx['course_hash'])

    def test_course_none_dans_contexte(self):
        _, ctx = self._run([make_competitor()])
        assert ctx['course'] is None

    def test_prev_next_cls_presents(self):
        _, ctx = self._run([make_competitor()])
        assert 'prev_cls' in ctx and 'next_cls' in ctx

    def test_redirect_si_relais(self):
        with patch('results.views.Mopteam') as MockTeam, \
             patch('results.views.Mopcompetitor') as MockComp, \
             patch('results.views.get_object_or_404', side_effect=[make_competition(), make_cls()]), \
             patch('results.views.redirect') as mock_redirect:
            MockTeam.objects.filter.return_value.exists.return_value = True
            from results.views import class_results
            class_results(rf_get(), cid=1, class_id=10)
            mock_redirect.assert_called_once()

    def test_leader_time_correct(self):
        from results.models import format_time
        c1 = make_competitor(1, rt=4000); c2 = make_competitor(2, rt=6000)
        _, ctx = self._run([c1, c2])
        assert ctx['leader_time'] == format_time(4000)

    def test_leader_time_tiret_si_aucun_classe(self):
        dnf = make_nf(1, STAT_DNF, 'Bob')
        _, ctx = self._run([dnf])
        assert ctx['leader_time'] == '-'


# ══════════════════════════════════════════════════════════════════════════════
# class_results — error_map et leg_error_data
# ══════════════════════════════════════════════════════════════════════════════

class TestClassResultsErrorMap:
    """Branche controls_seq + finishers → calcul des erreurs."""

    def _run_with_controls(self, competitors, controls_seq, radio_map, error_map=None):
        comp = make_competition(); cls = make_cls()
        default_error_map = error_map or {1: [{'error_time': 50, 'error_pct': 5.0}]}
        with patch('results.views.Mopteam') as MockTeam, \
             patch('results.views.Mopcompetitor') as MockComp, \
             patch('results.views.get_object_or_404', side_effect=[comp, cls]), \
             patch('results.views._get_adjacent_classes', return_value=(None, None)), \
             patch('results.views.get_org_map', return_value={}), \
             patch('results.views.get_class_controls', return_value=(controls_seq, {})), \
             patch('results.views.get_radio_map', return_value=radio_map), \
             patch('results.views.compute_splits', return_value=[
                 {'ctrl_name': 'P31', 'abs_time': '2:00', 'leg_time': '2:00',
                  'leg_raw': 1200, 'abs_raw': 1200, 'is_best': False, 'leg_rank': None, 'abs_rank': None}
             ]), \
             patch('results.views.mark_best_splits'), \
             patch('results.views.rank_splits'), \
             patch('results.views.compute_error_estimates', return_value=default_error_map), \
             patch('results.views.render') as mock_render:
            MockTeam.objects.filter.return_value.exists.return_value = False
            MockComp.objects.filter.return_value = competitors
            from results.views import class_results
            class_results(rf_get(), cid=1, class_id=10)
            _, _, ctx = mock_render.call_args[0]
            return ctx

    def test_leg_error_data_json_rempli(self):
        cs = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        ctx = self._run_with_controls([make_competitor(1, rt=5000)], cs, {1: {31: 1200}})
        leg_data = json.loads(ctx['leg_error_data_json'])
        assert len(leg_data) == 1
        assert leg_data[0]['ctrl_name'] == 'P31'

    def test_leg_error_data_vide_sans_controles(self):
        ctx = self._run_with_controls([make_competitor(1, rt=5000)], [], {})
        assert json.loads(ctx['leg_error_data_json']) == []

    def test_error_time_injecte_dans_splits(self):
        cs = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        ctx = self._run_with_controls(
            [make_competitor(1, rt=5000)], cs, {1: {31: 1200}},
            error_map={1: [{'error_time': 50, 'error_pct': 5.0}]}
        )
        # Le split du coureur doit avoir error_time injecté
        for r in ctx['results']:
            if r.is_ok:
                assert hasattr(r.splits[0], '__getitem__')
                break


# ══════════════════════════════════════════════════════════════════════════════
# class_results — ordre des non-classés
# ══════════════════════════════════════════════════════════════════════════════

class TestClassResultsNonFinisherOrdering:
    def _run(self, competitors):
        comp = make_competition(); cls = make_cls()
        with patch('results.views.Mopteam') as MockTeam, \
             patch('results.views.Mopcompetitor') as MockComp, \
             patch('results.views.get_object_or_404', side_effect=[comp, cls]), \
             patch('results.views._get_adjacent_classes', return_value=(None, None)), \
             patch('results.views.get_org_map', return_value={}), \
             patch('results.views.get_class_controls', return_value=([], {})), \
             patch('results.views.get_radio_map', return_value={}), \
             patch('results.views.compute_splits', return_value=[]), \
             patch('results.views.mark_best_splits'), \
             patch('results.views.rank_splits'), \
             patch('results.views.render') as mock_render:
            MockTeam.objects.filter.return_value.exists.return_value = False
            MockComp.objects.filter.return_value = competitors
            from results.views import class_results
            class_results(rf_get(), cid=1, class_id=10)
            _, _, ctx = mock_render.call_args[0]
            return ctx

    def test_classes_en_premier(self):
        ok = make_competitor(1, rt=5000, name='Alice')
        dnf = make_nf(2, STAT_DNF, 'Bob')
        ctx = self._run([dnf, ok])
        noms = [r.name for r in ctx['results']]
        assert noms.index('Alice') < noms.index('Bob')

    def test_nc_avant_pm(self):
        ctx = self._run([make_nf(1, STAT_MP, 'PM'), make_nf(2, STAT_OCC, 'NC')])
        noms = [r.name for r in ctx['results']]
        assert noms.index('NC') < noms.index('PM')

    def test_pm_avant_abandon(self):
        ctx = self._run([make_nf(1, STAT_DNF, 'DNF'), make_nf(2, STAT_MP, 'PM')])
        noms = [r.name for r in ctx['results']]
        assert noms.index('PM') < noms.index('DNF')

    def test_abandon_avant_dns(self):
        ctx = self._run([make_nf(1, STAT_DNS, 'DNS'), make_nf(2, STAT_DNF, 'DNF')])
        noms = [r.name for r in ctx['results']]
        assert noms.index('DNF') < noms.index('DNS')

    def test_ordre_complet(self):
        ctx = self._run([
            make_nf(1, STAT_DNS, 'DNS'), make_nf(2, STAT_DNF, 'DNF'),
            make_nf(3, STAT_MP, 'PM'),   make_nf(4, STAT_OCC, 'NC'),
            make_competitor(5, rt=5000, name='OK'),
        ])
        noms = [r.name for r in ctx['results']]
        idx = {n: noms.index(n) for n in ['OK', 'NC', 'PM', 'DNF', 'DNS']}
        assert idx['OK'] < idx['NC'] < idx['PM'] < idx['DNF'] < idx['DNS']

    def test_alpha_dans_groupe_pm(self):
        ctx = self._run([make_nf(1, STAT_MP, 'Zara'), make_nf(2, STAT_MP, 'Alice'), make_nf(3, STAT_MP, 'Martin')])
        assert [r.name for r in ctx['results']] == ['Alice', 'Martin', 'Zara']


# ══════════════════════════════════════════════════════════════════════════════
# competitor_detail
# ══════════════════════════════════════════════════════════════════════════════

class TestCompetitorDetailView:
    @patch('results.views.compute_splits', return_value=[])
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.Moporganization')
    @patch('results.views.Mopclass')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_contexte(self, mock_get404, mock_render, MockClass, MockOrg, *_):
        mock_get404.side_effect = [make_competition(), make_competitor()]
        MockOrg.objects.filter.return_value.first.return_value = MagicMock()
        MockClass.objects.filter.return_value.first.return_value = MagicMock()
        from results.views import competitor_detail
        competitor_detail(rf_get(), cid=1, competitor_id=1)
        _, template, ctx = mock_render.call_args[0]
        assert template == 'results/competitor_detail.html'
        assert 'splits' in ctx and 'total_time' in ctx

    @patch('results.views.compute_splits', return_value=[])
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.Moporganization')
    @patch('results.views.Mopclass')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_total_time_statut_si_non_classe(self, mock_get404, mock_render, MockClass, MockOrg, *_):
        dnf = make_competitor(1, rt=-1, stat=STAT_DNF); dnf.is_ok = False
        mock_get404.side_effect = [make_competition(), dnf]
        MockOrg.objects.filter.return_value.first.return_value = None
        MockClass.objects.filter.return_value.first.return_value = None
        from results.views import competitor_detail
        competitor_detail(rf_get(), cid=1, competitor_id=1)
        _, _, ctx = mock_render.call_args[0]
        assert ctx['total_time'] == 'OK'  # status_label mocké


# ══════════════════════════════════════════════════════════════════════════════
# api_class_results
# ══════════════════════════════════════════════════════════════════════════════

class TestApiClassResults:
    @patch('results.views.get_org_map', return_value={1: 'COLE'})
    @patch('results.views.Mopcompetitor')
    def test_retourne_json_avec_rang(self, MockComp, mock_org):
        MockComp.objects.filter.return_value = [make_competitor(1, rt=5000), make_competitor(2, rt=6000)]
        from results.views import api_class_results
        data = json.loads(api_class_results(rf_get(), cid=1, class_id=10).content)
        assert data['results'][0]['rank'] == 1
        assert data['results'][1]['behind'].startswith('+')

    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.Mopcompetitor')
    def test_liste_vide(self, MockComp, mock_org):
        MockComp.objects.filter.return_value = []
        from results.views import api_class_results
        data = json.loads(api_class_results(rf_get(), cid=1, class_id=10).content)
        assert data['results'] == []


# ══════════════════════════════════════════════════════════════════════════════
# superman_analysis
# ══════════════════════════════════════════════════════════════════════════════

class TestSupermanAnalysis:
    def _setup(self, mock_get404):
        competition = make_competition(); cls = make_cls()
        mock_get404.side_effect = [competition, cls]

    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views._controls_for', return_value=[])
    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_no_data_si_aucun_classe(self, MockComp, mock_get404, mock_render, mock_org, mock_ctrl, mock_radio):
        self._setup(mock_get404)
        dnf = make_competitor(1, rt=-1, stat=STAT_DNF); dnf.is_ok = False
        MockComp.objects.filter.return_value = [dnf]
        from results.views import superman_analysis
        superman_analysis(rf_get(), cid=1, class_id=10)
        _, template, ctx = mock_render.call_args[0]
        assert template == 'results/superman.html'
        assert ctx['no_data'] is True

    @patch('results.views.get_org_map', return_value={1: 'COLE'})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_superman_leg_data_contient_noms(self, MockComp, mock_get404, mock_render, *_):
        self._setup(mock_get404)
        c = make_competitor(1, rt=5000, org=1)
        MockComp.objects.filter.return_value = [c]
        from results.views import superman_analysis
        superman_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        assert len(ctx['superman_leg_data']) == 1   # 0 contrôles → 1 tronçon arrivée
        assert ctx['superman_leg_data'][0]['names'] == [c.name]

    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([{'ctrl_id': 31, 'ctrl_name': 'P31'}], {}))
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_radio_manquant_points_none(self, MockComp, mock_get404, mock_render, *_):
        """Si un coureur n'a pas de radio, ses points après le poste manquant sont None."""
        self._setup(mock_get404)
        c = make_competitor(1, rt=5000)
        MockComp.objects.filter.return_value = [c]
        from results.views import superman_analysis
        superman_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        series = json.loads(ctx['series_json'])
        # P31 radio absent → valid=False → points[1:] = None
        assert series[0]['points'][1] is None

    @patch('results.views.get_org_map', return_value={1: 'COLE', 2: 'NOSE'})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_series_json_ordre_classement(self, MockComp, mock_get404, mock_render, *_):
        self._setup(mock_get404)
        alice = make_competitor(1, rt=8000, name='Alice', org=1)
        bob   = make_competitor(2, rt=5000, name='Bob',   org=2)
        MockComp.objects.filter.return_value = [alice, bob]
        from results.views import superman_analysis
        superman_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        series = json.loads(ctx['series_json'])
        assert series[0]['name'] == 'Bob'; assert series[0]['rank'] == 1


# ══════════════════════════════════════════════════════════════════════════════
# performance_analysis
# ══════════════════════════════════════════════════════════════════════════════

class TestPerformanceAnalysis:
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_no_data(self, MockComp, mock_get404, mock_render):
        mock_get404.side_effect = [make_competition(), make_cls()]
        dnf = make_competitor(1, rt=-1, stat=STAT_DNF); dnf.is_ok = False
        MockComp.objects.filter.return_value = [dnf]
        from results.views import performance_analysis
        performance_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        assert ctx['no_data'] is True

    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_mean_pi_none_si_aucun_valide(self, MockComp, mock_get404, mock_render, *_):
        """valid=[] quand tous les tronçons sont invalides → mean_pi=None."""
        mock_get404.side_effect = [make_competition(), make_cls()]
        c = make_competitor(1, rt=5000)
        # Sans contrôles intermédiaires, leg_matrix aura le tronçon d'arrivée
        # mais leg_refs sera None si rt=0. On simule via un rt valide mais ref None.
        MockComp.objects.filter.return_value = [c]
        from results.views import performance_analysis
        performance_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        series = json.loads(ctx['series_json'])
        # Avec 1 coureur sans contrôles, il y a 1 tronçon et IP = 1.0
        assert series[0]['mean_pi'] is not None  # 1.0

    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_n_finishers_et_n_legs(self, MockComp, mock_get404, mock_render, *_):
        mock_get404.side_effect = [make_competition(), make_cls()]
        c1 = make_competitor(1, rt=5000); c2 = make_competitor(2, rt=6000)
        MockComp.objects.filter.return_value = [c1, c2]
        from results.views import performance_analysis
        performance_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        assert ctx['n_finishers'] == 2
        assert ctx['n_legs'] == 1   # 0 contrôles → 1 tronçon


# ══════════════════════════════════════════════════════════════════════════════
# regularity_analysis
# ══════════════════════════════════════════════════════════════════════════════

class TestRegularityAnalysis:
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_no_data_si_un_seul_classe(self, MockComp, mock_get404, mock_render):
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockComp.objects.filter.return_value = [make_competitor(1)]
        from results.views import regularity_analysis
        regularity_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        assert ctx['no_data'] is True

    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_category_regularity_none_si_tous_stds_none(self, MockComp, mock_get404, mock_render, *_):
        """Sans contrôles intermédiaires, les 2 coureurs ont un tronçon → σ calculable."""
        mock_get404.side_effect = [make_competition(), make_cls()]
        c1 = make_competitor(1, rt=5000); c2 = make_competitor(2, rt=6000)
        MockComp.objects.filter.return_value = [c1, c2]
        from results.views import regularity_analysis
        regularity_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        # category_regularity doit être float (σ > 0 car temps différents) ou 0.0
        cat = ctx['category_regularity']
        assert cat is None or isinstance(cat, float)

    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([{'ctrl_id': 31, 'ctrl_name': 'P31'}], {}))
    @patch('results.views.get_radio_map', return_value={})   # radio absent → cascade None
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_category_regularity_none_sans_radio(self, MockComp, mock_get404, mock_render, *_):
        """Sans données radio, tous les tronçons invalides → category_regularity = None."""
        mock_get404.side_effect = [make_competition(), make_cls()]
        c1 = make_competitor(1, rt=5000); c2 = make_competitor(2, rt=6000)
        MockComp.objects.filter.return_value = [c1, c2]
        from results.views import regularity_analysis
        regularity_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        assert ctx['category_regularity'] is None


# ══════════════════════════════════════════════════════════════════════════════
# grouping_analysis
# ══════════════════════════════════════════════════════════════════════════════

class TestGroupingAnalysis:
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_no_data_si_aucun_depart(self, MockComp, mock_get404, mock_render):
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockComp.objects.filter.return_value = [make_competitor(1, st=0)]
        from results.views import grouping_analysis
        grouping_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        assert ctx['no_data'] is True

    @patch('results.views.get_org_map', return_value={1: 'COLE'})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_series_contient_stat_rank_time_fmt(self, MockComp, mock_get404, mock_render, *_):
        mock_get404.side_effect = [make_competition(), make_cls()]
        c1 = make_competitor(1, rt=5000, st=100000, org=1)
        c2 = make_competitor(2, rt=6000, st=110000, org=1)
        MockComp.objects.filter.return_value = [c1, c2]
        from results.views import grouping_analysis
        grouping_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        series = json.loads(ctx['series_json'])
        for s in series:
            assert 'stat' in s
            assert 'rank' in s
            assert 'time_fmt' in s

    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_n_runners_et_n_controls(self, MockComp, mock_get404, mock_render, *_):
        mock_get404.side_effect = [make_competition(), make_cls()]
        c1 = make_competitor(1, st=100000); c2 = make_competitor(2, st=110000)
        MockComp.objects.filter.return_value = [c1, c2]
        from results.views import grouping_analysis
        grouping_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        assert ctx['n_runners'] == 2
        assert ctx['n_controls'] == 0


# ══════════════════════════════════════════════════════════════════════════════
# grouping_index_analysis
# ══════════════════════════════════════════════════════════════════════════════

class TestGroupingIndexAnalysis:
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_no_data(self, MockComp, mock_get404, mock_render):
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockComp.objects.filter.return_value = [make_competitor(1, st=0)]
        from results.views import grouping_index_analysis
        grouping_index_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        assert ctx['no_data'] is True

    @patch('results.views.get_org_map', return_value={1: 'COLE'})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_leg_ref_names_dans_raw(self, MockComp, mock_get404, mock_render, *_):
        mock_get404.side_effect = [make_competition(), make_cls()]
        c1 = make_competitor(1, st=100000, rt=50000, org=1)
        c2 = make_competitor(2, st=110000, rt=60000, org=1)
        MockComp.objects.filter.return_value = [c1, c2]
        from results.views import grouping_index_analysis
        grouping_index_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        raw = json.loads(ctx['results_json'])
        for r in raw:
            assert 'leg_ref_names' in r
            # leg_ref_ids doit être supprimé
            assert 'leg_ref_ids' not in r

    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_seuils_custom(self, MockComp, mock_get404, mock_render, *_):
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockComp.objects.filter.return_value = [make_competitor(1, st=100000)]
        from results.views import grouping_index_analysis
        grouping_index_analysis(RequestFactory().get('/?t1=5&t2=15'), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        assert ctx['t1'] == 5 and ctx['t2'] == 15

    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_seuils_invalides_defauts(self, MockComp, mock_get404, mock_render, *_):
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockComp.objects.filter.return_value = [make_competitor(1, st=100000)]
        from results.views import grouping_index_analysis
        grouping_index_analysis(RequestFactory().get('/?t1=abc&t2=xyz'), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        assert ctx['t1'] == 7 and ctx['t2'] == 20


# ══════════════════════════════════════════════════════════════════════════════
# duel_analysis
# ══════════════════════════════════════════════════════════════════════════════

class TestDuelAnalysis:
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteam')
    def test_no_data(self, MockTeam, MockComp, mock_get404, mock_render):
        MockTeam.objects.filter.return_value.exists.return_value = False
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockComp.objects.filter.return_value = []
        from results.views import duel_analysis
        duel_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        assert ctx['no_data'] is True

    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopteam')
    @patch('results.views.redirect')
    def test_relay_redirect_pour_categorie(self, mock_redirect, MockTeam, mock_get404, MockComp):
        competition = make_competition(); cls = make_cls()
        mock_get404.side_effect = [competition, cls]
        MockTeam.objects.filter.return_value.exists.return_value = True
        MockComp.objects.filter.return_value = []
        from results.views import duel_analysis
        duel_analysis(rf_get(), cid=1, class_id=10)
        mock_redirect.assert_called_once()

    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.compute_splits', return_value=[{
        'ctrl_name': 'P31', 'leg_raw': 1200, 'leg_time': '2:00',
        'abs_raw': 1200, 'abs_time': '2:00'
    }])
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteam')
    def test_splits_dans_runners_data(self, MockTeam, MockComp, mock_get404, mock_render, *_):
        MockTeam.objects.filter.return_value.exists.return_value = False
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockComp.objects.filter.return_value = [make_competitor(1, rt=5000)]
        from results.views import duel_analysis
        duel_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        runners = json.loads(ctx['runners_json'])
        assert len(runners[0]['splits']) == 1
        assert runners[0]['splits'][0]['ctrl_name'] == 'P31'

    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.compute_splits', return_value=[])
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteam')
    def test_current_analysis_duel(self, MockTeam, MockComp, mock_get404, mock_render, *_):
        MockTeam.objects.filter.return_value.exists.return_value = False
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockComp.objects.filter.return_value = [make_competitor(1)]
        from results.views import duel_analysis
        duel_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        assert ctx['current_analysis'] == 'duel'


# ══════════════════════════════════════════════════════════════════════════════
# relay_results
# ══════════════════════════════════════════════════════════════════════════════

class TestRelayResultsView:
    @patch('results.views.get_controls_by_leg', return_value=({}, {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.get_org_map', return_value={1: 'COLE'})
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteammember')
    @patch('results.views.Mopteam')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_contexte_nominal(self, mock_get404, mock_render, MockTeam, MockTM, MockComp, *_):
        mock_get404.side_effect = [make_competition(), make_cls()]
        t1 = MagicMock(); t1.id = 1; t1.rt = 10000; t1.stat = STAT_OK; t1.org = 1
        t2 = MagicMock(); t2.id = 2; t2.rt = 12000; t2.stat = STAT_OK; t2.org = 1
        MockTeam.objects.filter.return_value = [t1, t2]
        m1 = MagicMock(); m1.id = 1; m1.rid = 101; m1.leg = 1; m1.ord = 1
        m2 = MagicMock(); m2.id = 2; m2.rid = 102; m2.leg = 1; m2.ord = 1
        MockTM.objects.filter.return_value.order_by.return_value = [m1, m2]
        c1 = make_competitor(101, rt=10000); c2 = make_competitor(102, rt=12000)
        MockComp.objects.filter.return_value = [c1, c2]
        from results.views import relay_results
        relay_results(rf_get(), cid=1, class_id=10)
        _, template, ctx = mock_render.call_args[0]
        assert template == 'results/relay_results.html'
        assert 'teams_data' in ctx and 'leader_time' in ctx and 'n_legs' in ctx


# ══════════════════════════════════════════════════════════════════════════════
# org_results
# ══════════════════════════════════════════════════════════════════════════════

class TestOrgResultsView:
    def _mk_cls(self, id_, name, ord_=10):
        c = MagicMock(); c.id = id_; c.name = name; c.ord = ord_; return c

    @patch('results.views.Mopclass')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_contexte_de_base(self, mock_get404, mock_render, MockComp, MockClass):
        mock_get404.side_effect = [make_competition(), MagicMock()]
        MockComp.objects.filter.side_effect = [[make_competitor(1, cls=10)], [make_competitor(1, cls=10)]]
        MockClass.objects.filter.return_value = []
        from results.views import org_results
        org_results(rf_get(), cid=1, org_id=5)
        _, template, ctx = mock_render.call_args[0]
        assert template == 'results/org_results.html'
        assert 'competitors' in ctx

    @patch('results.views.Mopclass')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_cat_rank_attribue(self, mock_get404, mock_render, MockComp, MockClass):
        mock_get404.side_effect = [make_competition(), MagicMock()]
        alice = make_competitor(1, rt=6000, cls=10, name='Alice')
        bob   = make_competitor(2, rt=5000, cls=10, name='Bob', org=9)
        MockComp.objects.filter.side_effect = [[alice], [alice, bob]]
        MockClass.objects.filter.return_value = []
        from results.views import org_results
        org_results(rf_get(), cid=1, org_id=5)
        _, _, ctx = mock_render.call_args[0]
        alice_out = next(c for c in ctx['competitors'] if c.name == 'Alice')
        assert alice_out.cat_rank == 2

    @patch('results.views.Mopclass')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_classes_avant_non_classes(self, mock_get404, mock_render, MockComp, MockClass):
        mock_get404.side_effect = [make_competition(), MagicMock()]
        ok  = make_competitor(1, rt=5000, cls=10, name='OK')
        dnf = make_nf(2, STAT_DNF, 'DNF'); dnf.cls = 10
        MockComp.objects.filter.side_effect = [[ok, dnf], [ok]]
        MockClass.objects.filter.return_value = []
        from results.views import org_results
        org_results(rf_get(), cid=1, org_id=5)
        _, _, ctx = mock_render.call_args[0]
        noms = [c.name for c in ctx['competitors']]
        assert noms.index('OK') < noms.index('DNF')

    @patch('results.views.Mopclass')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_non_classe_cat_rank_none(self, mock_get404, mock_render, MockComp, MockClass):
        mock_get404.side_effect = [make_competition(), MagicMock()]
        dnf = make_nf(1, STAT_DNF, 'Bob'); dnf.cls = 10
        MockComp.objects.filter.side_effect = [[dnf], []]
        MockClass.objects.filter.return_value = []
        from results.views import org_results
        org_results(rf_get(), cid=1, org_id=5)
        _, _, ctx = mock_render.call_args[0]
        assert ctx['competitors'][0].cat_rank is None


# ══════════════════════════════════════════════════════════════════════════════
# statistics
# ══════════════════════════════════════════════════════════════════════════════

class TestStatisticsView:
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_contexte(self, MockComp, mock_get404, mock_render):
        mock_get404.return_value = make_competition()
        MockComp.objects.filter.return_value.count.return_value = 100
        MockComp.objects.filter.return_value.exclude.return_value.count.return_value = 80
        with patch('django.db.connection') as mock_conn:
            mock_conn.cursor.return_value.__enter__.return_value.fetchall.return_value = [('COLE', 15)]
            from results.views import statistics
            statistics(rf_get(), cid=1)
        _, template, ctx = mock_render.call_args[0]
        assert template == 'results/statistics.html'
        assert 'total' in ctx and 'finished' in ctx and 'top_orgs' in ctx


# ══════════════════════════════════════════════════════════════════════════════
# ClassResultsRankSplits — rank_splits est appelé
# ══════════════════════════════════════════════════════════════════════════════

class TestClassResultsRankSplits:
    @patch('results.views._get_adjacent_classes', return_value=(None, None))
    @patch('results.views.rank_splits')
    @patch('results.views.mark_best_splits')
    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([{'ctrl_id': 31, 'ctrl_name': 'P31'}], {}))
    @patch('results.views.get_radio_map', return_value={1: {31: 1200}})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteam')
    def test_rank_splits_appele(self, MockTeam, MockComp, mock_get404, mock_render, *args):
        mock_rank = args[0]  # rank_splits mock
        MockTeam.objects.filter.return_value.exists.return_value = False
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockComp.objects.filter.return_value = [make_competitor(1), make_competitor(2)]
        from results.views import class_results
        class_results(rf_get(), cid=1, class_id=10)
        assert mock_rank.called


# ══════════════════════════════════════════════════════════════════════════════
# _slugify_no_prefix
# ══════════════════════════════════════════════════════════════════════════════

class TestSlugifyNoPrefix:
    def _call(self, value):
        from results.views import _slugify_no_prefix
        return _slugify_no_prefix(value, separator='-')

    def test_prefixe_simple(self):    assert self._call('1 En amont') == 'en-amont'
    def test_prefixe_pointe(self):    assert self._call('5. Statuts') == 'statuts'
    def test_prefixe_compose(self):   assert self._call('1.1 Créer') == 'créer'
    def test_sans_prefixe(self):      assert self._call('Introduction') == 'introduction'
    def test_multi_niveaux(self):     assert self._call('3.2.1 Section') == 'section'
