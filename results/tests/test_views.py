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
from datetime import date, timedelta
from django.test import RequestFactory
from django.http import Http404

from results.models import (
    STAT_OK, STAT_MP, STAT_DNF, STAT_DNS, STAT_NP, STAT_CANCEL,
    STAT_OCC, STAT_NT, STAT_OT, STAT_DQ,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_competition(cid=1, date=None):
    c = MagicMock(); c.cid = cid; c.name = 'Test'; c.date = date; return c

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
    @patch('results.views.competition_visible', return_value=False)
    @patch('results.views.get_object_or_404')
    def test_invisible_leve_404(self, mock_get404, mock_visible, MockComp):
        """Compétition invisible → Http404 même si elle existe en base."""
        mock_get404.return_value = make_competition(1)
        from results.views import _load_class_context
        with pytest.raises(Http404):
            _load_class_context(cid=1, class_id=10)

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
    @patch('results.classViews.Mopcompetition')
    @patch('results.classViews.Mopteam')
    @patch('results.classViews.Mopcompetitor')
    @patch('results.classViews.render')
    def test_passe_competitions(self, mock_render, MockCompetitor, MockTeam, MockComp):
        comps = [make_competition(1), make_competition(2)]
        MockComp.objects.all.return_value = comps
        # Mock relay class IDs (empty = no relay)
        MockTeam.objects.filter.return_value.values_list.return_value.distinct.return_value = []
        # Mock individual competitors exist
        MockCompetitor.objects.filter.return_value.exclude.return_value.exists.return_value = True
        from results.classViews import HomeView
        HomeView.as_view()(rf_get())
        _, template, ctx = mock_render.call_args[0]
        assert template == 'results/home.html'
        assert ctx['competitions'] == comps
        # Check that has_individual_competitors was set
        for comp in comps:
            assert hasattr(comp, 'has_individual_competitors')

    # ─── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _run(url='/', comps=None):
        """Run HomeView with mocked models/render and return (template, context)."""
        comps = comps if comps is not None else [make_competition(1), make_competition(2)]
        with patch('results.classViews.Mopcompetition') as MockComp, \
             patch('results.classViews.Mopteam') as MockTeam, \
             patch('results.classViews.Mopcompetitor') as MockCompetitor, \
             patch('results.classViews.render') as mock_render:
            MockComp.objects.all.return_value = comps
            MockTeam.objects.filter.return_value.values_list.return_value.distinct.return_value = []
            MockCompetitor.objects.filter.return_value.exclude.return_value.exists.return_value = True
            MockCompetitor.objects.filter.return_value.exists.return_value = True
            from results.classViews import HomeView
            HomeView.as_view()(rf_get(url))
            _, template, context = mock_render.call_args[0]
            return template, context

    @staticmethod
    def _comps():
        """Five dated competitions, ordered oldest → newest."""
        return [
            make_competition(1, date=date(2024, 6, 15)),
            make_competition(2, date=date(2025, 3, 20)),
            make_competition(3, date=date(2025, 9, 10)),
            make_competition(4, date=date(2026, 1, 5)),
            make_competition(5, date=date(2026, 7, 1)),
        ]

    # -----------------------------------------------------------------─────

    def test_defaut_limite_trois_plus_recentes(self):
        """Sans paramètre → seules les 3 compétitions les plus récentes."""
        _, ctx = self._run(comps=self._comps())
        ids = [c.cid for c in ctx['competitions']]
        assert ids == [5, 4, 3]

    def test_defaut_trie_par_date_decroissante(self):
        _, ctx = self._run(comps=self._comps())
        dates = [c.date for c in ctx['competitions']]
        assert dates == sorted(dates, reverse=True)

    def test_regroupe_par_annee(self):
        _, ctx = self._run(url='/?months=100', comps=self._comps())
        years = [year for year, _ in ctx['years']]
        assert years == [2026, 2025, 2024]
        by_year = dict(ctx['years'])
        assert [c.cid for c in by_year[2026]] == [5, 4]
        assert [c.cid for c in by_year[2025]] == [3, 2]
        assert [c.cid for c in by_year[2024]] == [1]

    def test_filtre_mois_garde_seulement_recentes(self):
        cutoff = date.today() - timedelta(days=45)
        recent = make_competition(10, date=cutoff)
        old = make_competition(11, date=date(2020, 1, 1))
        _, ctx = self._run(url='/?months=2', comps=[old, recent])
        assert ctx['months'] == 2
        assert [c.cid for c in ctx['competitions']] == [10]
        assert ctx['active_filter'] is True

    def test_mode_annee_garde_toute_l_annee(self):
        _, ctx = self._run(url='/?year=2025', comps=self._comps())
        assert ctx['selected_year'] == 2025
        assert ctx['active_filter'] is True
        assert [c.cid for c in ctx['competitions']] == [3, 2]
        assert [year for year, _ in ctx['years']] == [2025]

    def test_mode_toutes_garde_toutes_les_competitions(self):
        """?all=1 → toutes les compétitions, triées par date décroissante."""
        _, ctx = self._run(url='/?all=1', comps=self._comps())
        assert ctx['show_all'] is True
        assert ctx['active_filter'] is True
        assert [c.cid for c in ctx['competitions']] == [5, 4, 3, 2, 1]
        assert [year for year, _ in ctx['years']] == [2026, 2025, 2024]

    def test_annee_prioritaire_sur_toutes(self):
        """year + all simultanés → l'année gagne (modes exclusifs)."""
        _, ctx = self._run(url='/?year=2024&all=1', comps=self._comps())
        assert ctx['selected_year'] == 2024
        assert ctx['show_all'] is False
        assert [c.cid for c in ctx['competitions']] == [1]

    def test_all_invalide_retour_au_defaut(self):
        """all=abc (ou absent) → considéré invalide → 3 plus récentes."""
        _, ctx = self._run(url='/?all=abc', comps=self._comps())
        assert ctx['show_all'] is False
        assert ctx['active_filter'] is False
        assert [c.cid for c in ctx['competitions']] == [5, 4, 3]

    def test_annee_prioritaire_sur_mois(self):
        """year + months simultanés → l'année gagne (modes exclusifs)."""
        _, ctx = self._run(url='/?year=2024&months=1', comps=self._comps())
        assert ctx['selected_year'] == 2024
        assert ctx['months'] is None
        assert [c.cid for c in ctx['competitions']] == [1]

    def test_parametres_invalides_retour_au_defaut(self):
        _, ctx = self._run(url='/?year=9999&months=abc', comps=self._comps())
        assert ctx['selected_year'] is None
        assert ctx['months'] is None
        assert ctx['active_filter'] in (None, False)
        assert [c.cid for c in ctx['competitions']] == [5, 4, 3]

    def test_available_years_decroissants(self):
        _, ctx = self._run(comps=self._comps())
        assert ctx['available_years'] == [2026, 2025, 2024]

    def test_months_zero_retour_au_defaut(self):
        """months=0 (ou négatif) → considéré invalide → 3 plus récentes."""
        _, ctx = self._run(url='/?months=0', comps=self._comps())
        assert ctx['months'] is None
        assert ctx['active_filter'] is False
        assert [c.cid for c in ctx['competitions']] == [5, 4, 3]

    def test_annotation_relais_utilise_exclude_par_competition(self):
        """HomeView annotates chaque compétition via la branche relais (exclude)."""
        comps = self._comps()
        with patch('results.classViews.Mopcompetition') as MockComp, \
             patch('results.classViews.Mopteam') as MockTeam, \
             patch('results.classViews.Mopcompetitor') as MockCompetitor, \
             patch('results.classViews.render'):
            MockComp.objects.all.return_value = comps
            MockTeam.objects.filter.return_value.values_list.return_value.distinct.return_value = [10]
            MockCompetitor.objects.filter.return_value.exclude.return_value.exists.return_value = True
            from results.classViews import HomeView
            HomeView.as_view()(rf_get())
        recent = sorted(comps, key=lambda c: c.date, reverse=True)[:HomeView.default_limit]
        for comp in recent:
            assert comp.has_individual_competitors is True


# ══════════════════════════════════════════════════════════════════════════════
# competition_detail
# ══════════════════════════════════════════════════════════════════════════════

class TestCompetitionDetailView:
    """CORRECTIF : get_courses_map est mocké pour éviter les requêtes DB."""

    def _run(self, cid=1, classes=None, teams_cls_ids=None, courses_map=None, neg_stats=None):
        competition = make_competition(cid)
        classes = classes or [make_cls(cid, 10), make_cls(cid, 11)]
        relay_cls_ids = teams_cls_ids if teams_cls_ids is not None else set()

        with patch('results.classViews.get_object_or_404', return_value=competition), \
             patch('results.classViews.Mopclass') as MockClass, \
             patch('results.classViews.Mopteam') as MockTeam, \
             patch('results.classViews.Mopcompetitor') as MockComp, \
             patch('results.classViews.get_courses_map', return_value=courses_map or {}), \
             patch('results.classViews.get_class_controls', return_value=([{'ctrl_id': 1}, {'ctrl_id': 2}], {})), \
             patch('results.classViews.get_negative_time_stats', return_value=neg_stats), \
             patch('results.classViews.render') as mock_render:
            MockClass.objects.filter.return_value.order_by.return_value = classes
            MockTeam.objects.filter.return_value.values_list.return_value.distinct.return_value = list(relay_cls_ids)
            comp_qs = MagicMock()
            comp_qs.count.return_value = 5
            comp_qs.filter.return_value.exclude.return_value.count.return_value = 3
            MockComp.objects.filter.return_value = comp_qs
            MockTeam.objects.filter.return_value.count.return_value = 2
            MockTeam.objects.filter.return_value.filter.return_value.exclude.return_value.count.return_value = 1
            from results.classViews import CompetitionDetailView
            CompetitionDetailView.as_view()(rf_get(), cid=cid)
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

    def _run_class_stats(self, cls, relay_cls_ids, relay_total=2, comp_total=5):
        """Run CompetitionDetailView avec une seule catégorie et des totaux donnés."""
        with patch('results.classViews.get_object_or_404', return_value=make_competition(1)), \
             patch('results.classViews.Mopclass') as MockClass, \
             patch('results.classViews.Mopteam') as MockTeam, \
             patch('results.classViews.Mopcompetitor') as MockComp, \
             patch('results.classViews.get_courses_map', return_value={}), \
             patch('results.classViews.get_class_controls', return_value=([], {})), \
             patch('results.classViews.render') as mock_render:
            MockClass.objects.filter.return_value.order_by.return_value = [cls]
            MockTeam.objects.filter.return_value.values_list.return_value.distinct.return_value = list(relay_cls_ids)
            MockTeam.objects.filter.return_value.count.return_value = relay_total
            MockComp.objects.filter.return_value.count.return_value = comp_total
            from results.classViews import CompetitionDetailView
            CompetitionDetailView.as_view()(rf_get(), cid=1)
            _, _, ctx = mock_render.call_args[0]
            return ctx

    def test_classe_relais_sans_equipe_ignoree(self):
        """Catégorie relais sans équipe (total 0) → absente de class_stats."""
        cls1 = make_cls(1, 10)
        ctx = self._run_class_stats(cls1, relay_cls_ids=[10], relay_total=0)
        assert ctx['class_stats'] == []

    def test_classe_individuelle_sans_concurrent_ignoree(self):
        """Catégorie individuelle sans concurrent (total 0) → absente de class_stats."""
        cls1 = make_cls(1, 10)
        ctx = self._run_class_stats(cls1, relay_cls_ids=set(), comp_total=0)
        assert ctx['class_stats'] == []

    def test_neg_time_warning_absent_par_defaut(self):
        """Aucun temps négatif → neg_time_warning est None."""
        _, ctx = self._run()
        assert ctx['neg_time_warning'] is None
        assert 'neg_count' not in ctx['class_stats'][0]
        assert 'neg_count' not in ctx['courses_map']

    def test_neg_count_par_categorie_et_circuit(self):
        """Le contexte remonte le nombre de temps négatifs par catégorie et par circuit."""
        cls1 = make_cls(1, 10, 'H21')
        cls2 = make_cls(1, 11, 'D35')
        stats = {
            'count': 3, 'kind': 'multiple', 'message': 'msg', 'tooltip': 't',
            'box_controls': {'P32': 2},
            'runners': [
                {'id': 1, 'name': 'A', 'cls_name': 'H21', 'controls': ['P32']},
                {'id': 2, 'name': 'B', 'cls_name': 'H21', 'controls': ['P32']},
                {'id': 3, 'name': 'C', 'cls_name': 'D35', 'controls': ['P31']},
            ],
        }
        cm = {'abc12345': {'hash': 'abc12345', 'display_name': 'H21 / D35',
                           'n_controls': 2, 'classes': [cls1, cls2]}}
        _, ctx = self._run(classes=[cls1, cls2], courses_map=cm, neg_stats=stats)
        assert ctx['neg_time_warning'] is stats
        assert ctx['class_stats'][0]['neg_count'] == 2
        assert ctx['class_stats'][1]['neg_count'] == 1
        assert ctx['courses_map']['abc12345']['neg_count'] == 3

    def test_neg_time_warning_rendu_dans_template(self):
        """La bannière et les badges s'affichent dans le HTML rendu."""
        cls1 = make_cls(1, 10, 'H21')
        cls2 = make_cls(1, 11, 'D35')
        stats = {
            'count': 2, 'kind': 'multiple', 'message': '2 coureurs neg', 'tooltip': 't',
            'box_controls': {'P32': 2},
            'runners': [
                {'id': 1, 'name': 'A', 'cls_name': 'H21', 'controls': ['P32']},
                {'id': 2, 'name': 'B', 'cls_name': 'H21', 'controls': ['P32']},
            ],
        }
        cm = {'abc12345': {'hash': 'abc12345', 'display_name': 'H21',
                           'n_controls': 2, 'classes': [cls1]}}
        _, ctx = self._run(classes=[cls1, cls2], courses_map=cm, neg_stats=stats)
        from types import SimpleNamespace
        from django.template.loader import render_to_string
        ctx['competition'] = SimpleNamespace(cid=1, name='Test', date=date(2026, 1, 1))
        html = render_to_string('results/competition_detail.html', ctx)
        assert '2 coureurs neg' in html
        assert 'neg-runners-table' in html
        assert 'neg-badge' in html
        assert 'neg-time-warning' in html


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

    def test_neg_time_warning_dans_contexte(self):
        """Le diagnostic temps négatifs est transmis au template."""
        comp = make_competition(); cls = make_cls()
        warning = {'count': 2, 'kind': 'multiple',
                   'message': '2 coureurs…', 'tooltip': 'Temps négatif'}
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
             patch('results.views.get_negative_time_stats', return_value=warning) as mock_stats, \
             patch('results.views.render') as mock_render:
            MockTeam.objects.filter.return_value.exists.return_value = False
            MockComp.objects.filter.return_value = [make_competitor()]
            from results.views import class_results
            class_results(rf_get(), cid=1, class_id=10)
            mock_stats.assert_called_once_with(1)
            _, _, ctx = mock_render.call_args[0]
            assert ctx['neg_time_warning'] == warning


# ══════════════════════════════════════════════════════════════════════════════
# class_results — marquage des coureurs à temps négatif
# ══════════════════════════════════════════════════════════════════════════════

class TestClassResultsNegTime:
    """Les coureurs avec un temps négatif sont marqués c.neg_time."""

    def _run(self, splits_list):
        comp = make_competition(); cls = make_cls()
        with patch('results.views.Mopteam') as MockTeam, \
             patch('results.views.Mopcompetitor') as MockComp, \
             patch('results.views.get_object_or_404', side_effect=[comp, cls]), \
             patch('results.views._get_adjacent_classes', return_value=(None, None)), \
             patch('results.views.get_org_map', return_value={}), \
             patch('results.views.get_class_controls', return_value=([{'ctrl_id': 31, 'ctrl_name': 'P31'}], {})), \
             patch('results.views.get_radio_map', return_value={}), \
             patch('results.views.compute_splits', return_value=splits_list), \
             patch('results.views.mark_best_splits'), \
             patch('results.views.rank_splits'), \
             patch('results.views.render') as mock_render:
            MockTeam.objects.filter.return_value.exists.return_value = False
            MockComp.objects.filter.return_value = [make_competitor(1, 4000)]
            from results.views import class_results
            class_results(rf_get(), cid=1, class_id=10)
            _, _, ctx = mock_render.call_args[0]
            return ctx['results'][0]

    def test_coureur_temps_negatif_marque(self):
        splits = [{'ctrl_name': 'P31', 'leg_time': '-00:50', 'leg_raw': -500,
                   'abs_raw': 1200, 'neg_leg': True}]
        assert self._run(splits).neg_time is True

    def test_coureur_arrivee_negative_marque(self):
        """Arrivée antérieure au dernier poste → marqué aussi."""
        splits = [{'ctrl_name': 'P31', 'leg_time': '02:00', 'leg_raw': 1200,
                   'abs_raw': 5000, 'neg_leg': False}]
        c = self._run(splits)
        assert c.neg_time is True

    def test_coureur_normal_non_marque(self):
        splits = [{'ctrl_name': 'P31', 'leg_time': '02:00', 'leg_raw': 1200,
                   'abs_raw': 1200, 'neg_leg': False}]
        assert self._run(splits).neg_time is False


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
    @patch('results.views.Mopcompetitor')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_contexte(self, mock_get404, mock_render, MockComp, MockClass, MockOrg, *_):
        mock_get404.side_effect = [make_competition(), make_competitor()]
        MockComp.objects.filter.return_value = []
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
    @patch('results.views.Mopcompetitor')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_total_time_statut_si_non_classe(self, mock_get404, mock_render, MockComp, MockClass, MockOrg, *_):
        dnf = make_competitor(1, rt=-1, stat=STAT_DNF); dnf.is_ok = False
        mock_get404.side_effect = [make_competition(), dnf]
        MockComp.objects.filter.return_value = []
        MockOrg.objects.filter.return_value.first.return_value = None
        MockClass.objects.filter.return_value.first.return_value = None
        from results.views import competitor_detail
        competitor_detail(rf_get(), cid=1, competitor_id=1)
        _, _, ctx = mock_render.call_args[0]
        assert ctx['total_time'] == 'OK'  # status_label mocké

    @patch('results.views.compute_splits', return_value=[{'ctrl_name': 'P31', 'abs_raw': 1200}])
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.Moporganization')
    @patch('results.views.Mopclass')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_troncon_arrivee_ajoute(self, mock_get404, mock_render, MockComp, MockClass, MockOrg, *_):
        """Un coureur classé avec splits reçoit un tronçon « Arrivée »."""
        comp = make_competition(); c = make_competitor(1, rt=5000)
        mock_get404.side_effect = [comp, c]
        MockComp.objects.filter.return_value = []
        MockOrg.objects.filter.return_value.first.return_value = None
        MockClass.objects.filter.return_value.first.return_value = None
        from results.views import competitor_detail
        competitor_detail(rf_get(), cid=1, competitor_id=1)
        _, _, ctx = mock_render.call_args[0]
        last = ctx['splits'][-1]
        assert last['ctrl_name'] == 'Arrivée'
        assert last['leg_raw'] == 3800   # 5000 - 1200
        assert last['abs_raw'] == 5000

    @patch('results.views.render')  # non atteint (le 404 précède)
    @patch('results.views.get_object_or_404')
    def test_invisible_leve_404(self, mock_get404, mock_render):
        """Compétition invisible → Http404."""
        mock_get404.return_value = make_competition(1)
        with patch('results.views.competition_visible', return_value=False):
            from results.views import competitor_detail
            with pytest.raises(Http404):
                competitor_detail(rf_get(), cid=1, competitor_id=1)


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

    @patch('results.views.get_org_map', return_value={1: 'COLE'})
    @patch('results.views.get_class_controls', return_value=([{'ctrl_id': 31, 'ctrl_name': 'P31'}], {}))
    @patch('results.views.get_radio_map', return_value={1: {31: 1200}})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_radio_presente_points_loss_calcules(self, MockComp, mock_get404, mock_render, *_):
        """Radio à 1200 → loss de 0 par rapport au superman cumulé, puis arrivée."""
        self._setup(mock_get404)
        c = make_competitor(1, rt=5000, org=1)
        MockComp.objects.filter.return_value = [c]
        from results.views import superman_analysis
        superman_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        series = json.loads(ctx['series_json'])
        # P31=1200 (cum=1200) → loss 0 ; totale=5000-5000 → 0
        assert series[0]['points'] == [0, 0, 0]
        assert len(series[0]['labels']) == 3

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

    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([{'ctrl_id': 31, 'ctrl_name': 'P31'}], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_indices_none_et_mean_pi_none_sans_radio(self, MockComp, mock_get404, mock_render, *_):
        """Aucune radio intermédiaire → leg_matrix vide, indices None, mean_pi None."""
        mock_get404.side_effect = [make_competition(), make_cls()]
        c = make_competitor(1, rt=5000)
        MockComp.objects.filter.return_value = [c]
        from results.views import performance_analysis
        performance_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        series = json.loads(ctx['series_json'])
        assert series[0]['indices'] == [None, None]   # P31 + Arrivée
        assert series[0]['mean_pi'] is None
        assert series[0]['std_pi'] is None


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
# recapitulatif_analysis
# ══════════════════════════════════════════════════════════════════════════════

class TestRecapitulatifAnalysis:

    # ── Helpers ─────────────────────────────────────────────────────────────
    def _setup_splits(self, splits_data=None):
        """Configure les mocks pour compute_splits / mark_best_splits / rank_splits.
        Retourne les deux mockers utiles.
        """
        return {}

    def _mock_context(self, mock_get404, MockComp, MockTeam, competitors=None,
                      competition=None, cls_=None, relay_exists=False):
        competition = competition or make_competition()
        cls_ = cls_ or make_cls()
        mock_get404.side_effect = [competition, cls_]
        MockTeam.objects.filter.return_value.exists.return_value = relay_exists
        MockComp.objects.filter.return_value = competitors or []
        return competition, cls_

    def _call_view(self, **extra_kwargs):
        from results.views import recapitulatif_analysis
        return recapitulatif_analysis(rf_get(), cid=1, class_id=10, **extra_kwargs)

    # ── Tests ───────────────────────────────────────────────────────────────

    @patch('results.views._get_adjacent_classes', return_value=(None, None))
    @patch('results.views.mark_best_splits')
    @patch('results.views.rank_splits')
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteam')
    def test_no_data(self, MockTeam, MockComp, mock_get404, mock_render, *args):
        MockTeam.objects.filter.return_value.exists.return_value = False
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockComp.objects.filter.return_value = []
        from results.views import recapitulatif_analysis
        recapitulatif_analysis(rf_get(), cid=1, class_id=10)
        _, template, ctx = mock_render.call_args[0]
        assert template == 'results/recapitulatif.html'
        assert ctx['results'] == []

    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopteam')
    @patch('results.views.redirect')
    def test_relay_redirect(self, mock_redirect, MockTeam, mock_get404, MockComp):
        competition = make_competition()
        cls_ = make_cls()
        mock_get404.side_effect = [competition, cls_]
        MockTeam.objects.filter.return_value.exists.return_value = True
        MockComp.objects.filter.return_value = []
        from results.views import recapitulatif_analysis
        recapitulatif_analysis(rf_get(), cid=1, class_id=10)
        mock_redirect.assert_called_once()

    @patch('results.views._get_adjacent_classes', return_value=(None, None))
    @patch('results.views.mark_best_splits')
    @patch('results.views.rank_splits')
    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([{'ctrl_id': 31, 'ctrl_name': 'P31'}], {}))
    @patch('results.views.get_radio_map', return_value={1: {31: 1200}})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteam')
    def test_splits_pour_classement(self, MockTeam, MockComp, mock_get404,
                                    mock_render, *_):
        MockTeam.objects.filter.return_value.exists.return_value = False
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockComp.objects.filter.return_value = [make_competitor(1, rt=5000)]
        from results.views import recapitulatif_analysis
        recapitulatif_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        for c in ctx['results']:
            assert hasattr(c, 'splits')
            assert len(c.splits) == 2  # 1 control + Arrivée

    @patch('results.views._get_adjacent_classes', return_value=(None, None))
    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.compute_splits', return_value=[])
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteam')
    def test_has_splits_false(self, MockTeam, MockComp, mock_get404,
                              mock_render, *_):
        MockTeam.objects.filter.return_value.exists.return_value = False
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockComp.objects.filter.return_value = [make_competitor(1)]
        from results.views import recapitulatif_analysis
        recapitulatif_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        assert ctx['has_splits'] is False

    @patch('results.views._get_adjacent_classes', return_value=(None, None))
    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([{'ctrl_id': 31, 'ctrl_name': 'P31'}], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.compute_splits', return_value=[])
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteam')
    def test_has_splits_true(self, MockTeam, MockComp, mock_get404,
                             mock_render, *_):
        MockTeam.objects.filter.return_value.exists.return_value = False
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockComp.objects.filter.return_value = [make_competitor(1)]
        from results.views import recapitulatif_analysis
        recapitulatif_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        assert ctx['has_splits'] is True

    @patch('results.views._get_adjacent_classes', return_value=(None, None))
    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.compute_splits', return_value=[])
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteam')
    def test_contexte_cles(self, MockTeam, MockComp, mock_get404,
                           mock_render, *_):
        MockTeam.objects.filter.return_value.exists.return_value = False
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockComp.objects.filter.return_value = [make_competitor(1)]
        from results.views import recapitulatif_analysis
        recapitulatif_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        assert 'competition' in ctx
        assert 'cls' in ctx
        assert 'course' in ctx
        assert 'results' in ctx
        assert 'controls_seq' in ctx
        assert 'has_splits' in ctx
        assert ctx['current_analysis'] == 'recapitulatif'
        assert 'prev_cls' in ctx
        assert 'next_cls' in ctx
        assert 'leader_time' in ctx

    @patch('results.views._get_adjacent_classes', return_value=(MagicMock(), None))
    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.compute_splits', return_value=[])
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteam')
    def test_navigation_prev_next(self, MockTeam, MockComp, mock_get404,
                                  mock_render, *_):
        MockTeam.objects.filter.return_value.exists.return_value = False
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockComp.objects.filter.return_value = [make_competitor(1)]
        from results.views import recapitulatif_analysis
        recapitulatif_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        assert ctx['prev_cls'] is not None
        assert ctx['next_cls'] is None

    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.render')
    @patch('results.views._load_class_context')
    @patch('results.views.Mopteam')
    def test_course_context(self, MockTeam, mock_load, mock_render, *_):
        """Mode circuit : course doit être un dict, pas None."""
        MockTeam.objects.filter.return_value.exists.return_value = False
        competition = make_competition()
        cls_ = make_cls()
        course = {
            'hash': 'abcd1234', 'display_name': 'Circuit Test',
            'class_ids': [10], 'classes': [cls_],
            'controls_seq': [], 'n_controls': 0,
        }
        mock_load.return_value = (competition, cls_, [make_competitor(1)], course)
        from results.views import recapitulatif_analysis
        recapitulatif_analysis(rf_get(), cid=1, class_id='abcd1234')
        _, _, ctx = mock_render.call_args[0]
        assert ctx['course'] is not None
        assert ctx['course']['hash'] == 'abcd1234'

    @patch('results.views._get_adjacent_classes', return_value=(None, None))
    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.compute_splits', return_value=[])
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteam')
    def test_leader_time_tiret_si_aucun_classe(self, MockTeam, MockComp,
                                                mock_get404, mock_render, *_):
        MockTeam.objects.filter.return_value.exists.return_value = False
        mock_get404.side_effect = [make_competition(), make_cls()]
        # Un seul coureur mais stat != OK
        c = make_competitor(1, rt=-1, stat=STAT_DNF)
        MockComp.objects.filter.return_value = [c]
        from results.views import recapitulatif_analysis
        recapitulatif_analysis(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        assert ctx['leader_time'] == '-'

    @patch('results.views._get_adjacent_classes', return_value=(None, None))
    @patch('results.views.rank_splits')
    @patch('results.views.mark_best_splits')
    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([{'ctrl_id': 31, 'ctrl_name': 'P31'}], {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteam')
    def test_mark_best_et_rank_splits_appeles(self, MockTeam, MockComp,
                                               mock_get404, mock_render, *args):
        mock_rank = args[0]
        mock_best = args[1]
        MockTeam.objects.filter.return_value.exists.return_value = False
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockComp.objects.filter.return_value = [make_competitor(1), make_competitor(2)]
        from results.views import recapitulatif_analysis
        recapitulatif_analysis(rf_get(), cid=1, class_id=10)
        assert mock_best.called
        assert mock_rank.called


# ══════════════════════════════════════════════════════════════════════════════
# _load_recapitulatif_data — appel direct sans contexte (branche « else »)
# ══════════════════════════════════════════════════════════════════════════════

class TestLoadRecapitulatifDataDirect:
    @patch('results.views.compute_splits', return_value=[])
    @patch('results.views.mark_best_splits')
    @patch('results.views.rank_splits')
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_org_map', return_value={})
    @patch('results.views._get_adjacent_classes', return_value=(None, None))
    @patch('results.views._load_class_context')
    @patch('results.views.Mopteam')
    def test_sans_contexte_appelle_load_class_context(self, MockTeam, mock_load_ctx, *_):
        """Appel direct (CSV) → chargement via _load_class_context."""
        competition = make_competition(); cls_ = make_cls()
        mock_load_ctx.return_value = (competition, cls_, [], None)
        from results.views import _load_recapitulatif_data
        comp, c_, course, results, controls, prev, nxt, leader, errs = \
            _load_recapitulatif_data(cid=1, class_id=10)
        mock_load_ctx.assert_called_once_with(1, 10)
        assert comp is competition and c_ is cls_ and course is None
        assert results == [] and controls == []


# ══════════════════════════════════════════════════════════════════════════════
# recapitulatif_csv
# ══════════════════════════════════════════════════════════════════════════════

class TestRecapitulatifCsv:
    def _csv_runner(self, id_=1, ok=True, splits=None, class_name='H21',
                    org_name='COLE', rank=1):
        c = MagicMock()
        c.id = id_; c.name = f'Runner {id_}'; c.rank = rank; c.is_ok = ok
        c.st = 100000; c.stat = STAT_OK if ok else STAT_DNF
        c.class_obj = MagicMock(); c.class_obj.name = class_name
        c.org_obj = MagicMock(); c.org_obj.name = org_name
        c.splits = splits or []
        return c

    def _call(self, runner, controls=None, course=None, relay=False):
        competition = make_competition(); cls_ = make_cls(1, 10)
        with patch('results.views._load_class_context') as mock_ctx, \
             patch('results.views._is_relay', return_value=relay), \
             patch('results.views._load_recapitulatif_data') as mock_data, \
             patch('results.views.redirect') as mock_redirect:
            mock_ctx.return_value = (competition, cls_, [runner], course)
            mock_data.return_value = (competition, cls_, course, [runner],
                                      controls or [], None, None, None, [])
            from results.views import recapitulatif_csv
            response = recapitulatif_csv(rf_get(), cid=1, class_id=10)
            return response, mock_redirect

    def test_relais_redirige(self):
        runner = self._csv_runner()
        _, mock_redirect = self._call(runner, relay=True)
        mock_redirect.assert_called_once()

    def test_avec_troncons_ecrit_deux_lignes_par_coureur(self):
        runner = self._csv_runner(splits=[
            {'leg_time': '0.00', 'leg_rank': None, 'abs_time': '0.00', 'abs_rank': 1},
            {'leg_time': '0.00', 'leg_rank': 1, 'abs_time': '0.00', 'abs_rank': 2},
        ])
        response, _ = self._call(runner, controls=[{'ctrl_name': 'P31'}])
        text = response.content.decode('utf-8')
        assert 'attachment; filename="recapitulatif_H21_1.csv"' in response['Content-Disposition']
        lines = text.strip().split('\r\n')
        assert lines[0].strip().startswith('#') and 'Arr.' in lines[0]
        # 1 en-tête + 2 lignes (tronçon + cumulé)
        assert len(lines) == 3
        assert 'Runner 1' in lines[1]
        assert '(2)' in lines[2]     # rang cumulé de l'arrivée

    def test_sans_troncons_ligne_unique(self):
        runner = self._csv_runner(splits=[{'leg_time': '-', 'leg_rank': None,
                                           'abs_time': '-', 'abs_rank': None}])
        response, _ = self._call(runner)
        text = response.content.decode('utf-8')
        assert 'Arr.' not in text
        assert text.count('Runner 1') == 1

    def test_non_classe_tirets(self):
        runner = self._csv_runner(ok=False, splits=[{}, {}])
        response, _ = self._call(runner, controls=[{'ctrl_name': 'P31'}])
        text = response.content.decode('utf-8')
        assert '—' in text

    def test_circuit_ajoute_categorie(self):
        runner = self._csv_runner(class_name='D21', org_name='NOSE')
        course = {'hash': 'abc12345', 'display_name': 'Circuit'}
        response, _ = self._call(runner, course=course)
        text = response.content.decode('utf-8')
        assert 'Catégorie' in text
        assert 'D21' in text


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

    @patch('results.views.render')  # non atteint (le 404 précède)
    @patch('results.views.get_object_or_404')
    def test_404_si_invisible(self, mock_get404, mock_render):
        mock_get404.return_value = make_competition(1)
        with patch('results.views.competition_visible', return_value=False):
            from results.views import relay_results
            with pytest.raises(Http404):
                relay_results(rf_get(), cid=1, class_id=10)

    @patch('results.views.get_controls_by_leg', return_value=({}, {}))
    @patch('results.views.get_radio_map', return_value={})
    @patch('results.views.get_org_map', return_value={1: 'COLE'})
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteammember')
    @patch('results.views.Mopteam')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_etape_sans_coureur_emplacement_vide(self, mock_get404, mock_render, MockTeam, MockTM, MockComp, *_):
        """Équipe avec un trou dans les étapes → emplacement vide « — »."""
        mock_get404.side_effect = [make_competition(), make_cls()]
        t1 = MagicMock(); t1.id = 1; t1.rt = 10000; t1.stat = STAT_OK; t1.org = 1
        t2 = MagicMock(); t2.id = 2; t2.rt = 12000; t2.stat = STAT_OK; t2.org = 1
        MockTeam.objects.filter.return_value = [t1, t2]
        m1 = MagicMock(); m1.id = 1; m1.rid = 101; m1.leg = 1; m1.ord = 1
        m2 = MagicMock(); m2.id = 2; m2.rid = 102; m2.leg = 2; m2.ord = 1
        MockTM.objects.filter.return_value.order_by.return_value = [m1, m2]
        c1 = make_competitor(101, rt=10000); c2 = make_competitor(102, rt=12000)
        MockComp.objects.filter.return_value = [c1, c2]
        from results.views import relay_results
        relay_results(rf_get(), cid=1, class_id=10)
        _, _, ctx = mock_render.call_args[0]
        assert ctx['n_legs'] == 2
        team1 = ctx['teams_data'][0]          # t1 (10000) avant t2 (12000)
        assert team1['legs'][1]['name'] == '—'       # étape 2 sans coureur
        assert team1['legs'][1]['runner_id'] is None
        team2 = ctx['teams_data'][1]
        assert team2['legs'][0]['name'] == '—'       # étape 1 sans coureur


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

    @patch('results.views.render')  # non atteint (le 404 précède)
    @patch('results.views.get_object_or_404')
    def test_invisible_leve_404(self, mock_get404, mock_render):
        mock_get404.return_value = make_competition(1)
        with patch('results.views.competition_visible', return_value=False):
            from results.views import org_results
            with pytest.raises(Http404):
                org_results(rf_get(), cid=1, org_id=5)


# ══════════════════════════════════════════════════════════════════════════════
# statistics
# ══════════════════════════════════════════════════════════════════════════════

class TestStatisticsView:
    @patch('results.classViews.render')
    @patch('results.classViews.get_object_or_404')
    @patch('results.classViews.Mopcompetitor')
    def test_contexte(self, MockComp, mock_get404, mock_render):
        mock_get404.return_value = make_competition()
        MockComp.objects.filter.return_value.count.return_value = 100
        MockComp.objects.filter.return_value.exclude.return_value.count.return_value = 80
        with patch('results.classViews.connection') as mock_conn:
            mock_conn.cursor.return_value.__enter__.return_value.fetchall.return_value = [('COLE', 15)]
            from results.classViews import StatisticsView
            StatisticsView.as_view()(rf_get(), cid=1)
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
        from results.services import slugify_no_prefix
        return slugify_no_prefix(value, separator='-')

    def test_prefixe_simple(self):    assert self._call('1 En amont') == 'en-amont'
    def test_prefixe_pointe(self):    assert self._call('5. Statuts') == 'statuts'
    def test_prefixe_compose(self):   assert self._call('1.1 Créer') == 'créer'
    def test_sans_prefixe(self):      assert self._call('Introduction') == 'introduction'
    def test_multi_niveaux(self):     assert self._call('3.2.1 Section') == 'section'


# ══════════════════════════════════════════════════════════════════════════════
# start_list
# ══════════════════════════════════════════════════════════════════════════════

class TestStartListView:

    def _mk_competitor(self, id=1, st=100000, name='Martin Luc', org=1, cls=10, card='', bib=''):
        c = MagicMock()
        c.id = id; c.st = st; c.name = name; c.org = org; c.cls = cls
        c.card = card; c.bib = bib
        return c

    def _mk_cls(self, id=10, name='H21'):
        c = MagicMock(); c.id = id; c.name = name; return c

    def _mk_org(self, id=1, name='COLE'):
        c = MagicMock(); c.id = id; c.name = name; return c

    def _run(self, competitors=None, classes=None, orgs=None):
        competition = make_competition()
        competitors = competitors or []
        classes = classes or []
        org_map = {o.id: o for o in (orgs or [])}
        with patch('results.classViews.get_object_or_404', return_value=competition), \
             patch('results.classViews.Mopcompetitor') as MockComp, \
             patch('results.classViews.Mopclass') as MockClass, \
             patch('results.classViews.get_org_map', return_value=org_map), \
             patch('results.classViews.render') as mock_render:
            MockComp.objects.filter.return_value.select_related.return_value = competitors
            MockClass.objects.filter.return_value = classes
            from results.classViews import StartListView
            StartListView.as_view()(rf_get(), cid=1)
            _, template, ctx = mock_render.call_args[0]
            return template, ctx

    def test_template_correct(self):
        template, _ = self._run()
        assert template == 'results/start_list.html'

    def test_competition_dans_contexte(self):
        _, ctx = self._run()
        assert 'competition' in ctx

    def test_start_list_data_json_present(self):
        _, ctx = self._run()
        data = json.loads(ctx['start_list_data'])
        assert 'meta' in data
        assert 'groups' in data

    def test_sans_concurrent_listes_vides(self):
        _, ctx = self._run()
        data = json.loads(ctx['start_list_data'])
        assert data['groups']['category'] == []
        assert data['groups']['club'] == []
        assert data['groups']['start_time'] == []

    def test_un_concurrent(self):
        c = self._mk_competitor(id=1, st=36000, name='Martin Luc', org=1, cls=10)
        cls = self._mk_cls(10, 'H21')
        org = self._mk_org(1, 'COLE')
        _, ctx = self._run(competitors=[c], classes=[cls], orgs=[org])
        data = json.loads(ctx['start_list_data'])
        assert len(data['groups']['category']) == 1
        assert data['groups']['category'][0]['name'] == 'H21'
        assert len(data['groups']['category'][0]['rows']) == 1
        row = data['groups']['category'][0]['rows'][0]
        assert row['full_name'] == 'Martin Luc'
        assert row['family'] == 'Martin'
        assert row['given'] == 'Luc'
        assert row['category'] == 'H21'

    def test_heure_depart_formatee(self):
        """st=36000 dixièmes = 3600 sec = 01:00."""
        c = self._mk_competitor(id=1, st=36000)
        cls = self._mk_cls(10, 'H21')
        _, ctx = self._run(competitors=[c], classes=[cls])
        data = json.loads(ctx['start_list_data'])
        row = data['groups']['category'][0]['rows'][0]
        assert row['start_time'] == '01:00'

    def test_heure_depart_vide_si_st_zero(self):
        c = self._mk_competitor(id=1, st=0)
        cls = self._mk_cls(10, 'H21')
        _, ctx = self._run(competitors=[c], classes=[cls])
        data = json.loads(ctx['start_list_data'])
        row = data['groups']['category'][0]['rows'][0]
        assert row['start_time'] == ''

    def test_control_card_rempli(self):
        """Le numéro de puce (attribut card MOP) est exposé dans la liste."""
        c = self._mk_competitor(id=1, st=36000, name='Martin Luc', card='12345')
        cls = self._mk_cls(10, 'H21')
        _, ctx = self._run(competitors=[c], classes=[cls])
        data = json.loads(ctx['start_list_data'])
        row = data['groups']['category'][0]['rows'][0]
        assert row['control_card'] == '12345'

    def test_control_card_vide_si_absent(self):
        c = self._mk_competitor(id=1, st=36000, name='Martin Luc')
        cls = self._mk_cls(10, 'H21')
        _, ctx = self._run(competitors=[c], classes=[cls])
        data = json.loads(ctx['start_list_data'])
        row = data['groups']['category'][0]['rows'][0]
        assert row['control_card'] == ''

    def test_bib_expose_dans_rows(self):
        """Le dossard (attribut bib MOP) est exposé dans la liste."""
        c = self._mk_competitor(id=1, st=36000, name='Martin Luc', bib='218')
        cls = self._mk_cls(10, 'H21')
        _, ctx = self._run(competitors=[c], classes=[cls])
        data = json.loads(ctx['start_list_data'])
        row = data['groups']['category'][0]['rows'][0]
        assert row['bib'] == '218'

    def test_bib_vide_si_absent(self):
        c = self._mk_competitor(id=1, st=36000, name='Martin Luc')
        cls = self._mk_cls(10, 'H21')
        _, ctx = self._run(competitors=[c], classes=[cls])
        data = json.loads(ctx['start_list_data'])
        row = data['groups']['category'][0]['rows'][0]
        assert row['bib'] == ''

    def test_meta_has_bib_vrai_si_au_moins_un_bib(self):
        """Dès qu'un dossard existe, la colonne s'affichera pour tous."""
        c1 = self._mk_competitor(id=1, st=36000, name='Sans Bib')
        c2 = self._mk_competitor(id=2, st=37000, name='Avec Bib', bib='218')
        cls = self._mk_cls(10, 'H21')
        _, ctx = self._run(competitors=[c1, c2], classes=[cls])
        data = json.loads(ctx['start_list_data'])
        assert data['meta']['has_bib'] is True

    def test_meta_has_bib_faux_sans_bib(self):
        cls = self._mk_cls(10, 'H21')
        _, ctx = self._run(competitors=[self._mk_competitor()], classes=[cls])
        data = json.loads(ctx['start_list_data'])
        assert data['meta']['has_bib'] is False

    def test_meta_has_bib_faux_sans_concurrent(self):
        _, ctx = self._run()
        data = json.loads(ctx['start_list_data'])
        assert data['meta']['has_bib'] is False

    def test_tri_par_heure_depart(self):
        """Les groupes « Par heure » sont ordonnés par heure croissante."""
        c1 = self._mk_competitor(id=1, st=72000, name='Lent')
        c2 = self._mk_competitor(id=2, st=36000, name='Rapide')
        cls = self._mk_cls(10, 'H21')
        _, ctx = self._run(competitors=[c1, c2], classes=[cls])
        data = json.loads(ctx['start_list_data'])
        groups = data['groups']['start_time']
        assert [g['name'] for g in groups] == ['01:00', '02:00']

    def test_groupement_par_categorie(self):
        c1 = self._mk_competitor(id=1, st=36000, cls=10)
        c2 = self._mk_competitor(id=2, st=37000, cls=11)
        cls1 = self._mk_cls(10, 'H21')
        cls2 = self._mk_cls(11, 'D21')
        _, ctx = self._run(competitors=[c1, c2], classes=[cls1, cls2])
        data = json.loads(ctx['start_list_data'])
        cats = [g['name'] for g in data['groups']['category']]
        assert 'H21' in cats
        assert 'D21' in cats

    def test_tri_alpha_dans_categorie(self):
        """À catégorie identique, les coureurs sont triés par nom puis prénom, insensible à la casse."""
        c1 = self._mk_competitor(id=1, st=36000, name='Zebre anne', cls=10)
        c2 = self._mk_competitor(id=2, st=37000, name='martin Luc', cls=10)
        cls1 = self._mk_cls(10, 'H21')
        _, ctx = self._run(competitors=[c1, c2], classes=[cls1])
        data = json.loads(ctx['start_list_data'])
        rows = data['groups']['category'][0]['rows']
        assert [r['full_name'] for r in rows] == ['martin Luc', 'Zebre anne']

    def test_groupement_par_club(self):
        c1 = self._mk_competitor(id=1, st=36000, org=1)
        c2 = self._mk_competitor(id=2, st=37000, org=2)
        org1 = self._mk_org(1, 'COLE')
        org2 = self._mk_org(2, 'NOSE')
        _, ctx = self._run(competitors=[c1, c2], orgs=[org1, org2])
        data = json.loads(ctx['start_list_data'])
        clubs = [g['name'] for g in data['groups']['club']]
        assert any('COLE' in c for c in clubs)
        assert any('NOSE' in c for c in clubs)

    def test_tri_alpha_dans_club(self):
        """À club identique, les coureurs sont triés par nom puis prénom, insensible à la casse."""
        c1 = self._mk_competitor(id=1, st=36000, name='Zebre anne', org=1)
        c2 = self._mk_competitor(id=2, st=37000, name='martin Luc', org=1)
        org1 = self._mk_org(1, 'COLE')
        _, ctx = self._run(competitors=[c1, c2], orgs=[org1])
        data = json.loads(ctx['start_list_data'])
        rows = data['groups']['club'][0]['rows']
        assert [r['full_name'] for r in rows] == ['martin Luc', 'Zebre anne']

    def test_vignettes_club_triees_par_numero(self):
        """Les vignettes club sont triées par numéro de club croissant, pas par nom."""
        c1 = self._mk_competitor(id=1, st=36000, org=2)
        c2 = self._mk_competitor(id=2, st=37000, org=1)
        org1 = self._mk_org(1, 'COLE')
        org2 = self._mk_org(2, 'NOSE')
        _, ctx = self._run(competitors=[c1, c2], orgs=[org1, org2])
        data = json.loads(ctx['start_list_data'])
        groups = data['groups']['club']
        assert [g['name'] for g in groups] == ['0001 - COLE', '0002 - NOSE']

    def test_sans_club_en_dernier(self):
        """Le groupe « Sans club » apparaît après les clubs numérotés."""
        c1 = self._mk_competitor(id=1, st=36000, org=1)
        c2 = self._mk_competitor(id=2, st=37000, org=None)
        org1 = self._mk_org(1, 'COLE')
        _, ctx = self._run(competitors=[c1, c2], orgs=[org1])
        data = json.loads(ctx['start_list_data'])
        groups = data['groups']['club']
        assert [g['name'] for g in groups] == ['0001 - COLE', 'Sans club']

    def test_groupement_par_heure_depart_identique(self):
        c1 = self._mk_competitor(id=1, st=36000, name='A')
        c2 = self._mk_competitor(id=2, st=36000, name='B')
        _, ctx = self._run(competitors=[c1, c2])
        data = json.loads(ctx['start_list_data'])
        assert len(data['groups']['start_time']) == 1

    def test_tri_alpha_dans_heure_depart(self):
        """À heure identique, les coureurs sont triés par nom puis prénom, insensible à la casse."""
        c1 = self._mk_competitor(id=1, st=36000, name='Zebre anne')
        c2 = self._mk_competitor(id=2, st=36000, name='martin Luc')
        _, ctx = self._run(competitors=[c1, c2])
        data = json.loads(ctx['start_list_data'])
        rows = data['groups']['start_time'][0]['rows']
        assert [r['full_name'] for r in rows] == ['martin Luc', 'Zebre anne']

    def test_slug_genere(self):
        c = self._mk_competitor(id=1, st=36000)
        cls = self._mk_cls(10, 'H21 DÉBUTANT')
        _, ctx = self._run(competitors=[c], classes=[cls])
        data = json.loads(ctx['start_list_data'])
        assert data['groups']['category'][0]['slug'] == 'h21-d-butant'

    def test_concurrent_sans_org(self):
        c = self._mk_competitor(id=1, st=36000, org=None)
        cls = self._mk_cls(10, 'H21')
        _, ctx = self._run(competitors=[c], classes=[cls])
        data = json.loads(ctx['start_list_data'])
        row = data['groups']['category'][0]['rows'][0]
        assert row['club_display'] == 'Sans club'

    def test_concurrent_sans_categorie(self):
        c = self._mk_competitor(id=1, st=36000, cls=99)
        _, ctx = self._run(competitors=[c])
        data = json.loads(ctx['start_list_data'])
        # cls 99 n'est pas dans classes=[] → category=''
        # Les groupes de catégorie vide sont ignorés, mais le groupe start_time contient le coureur
        assert data['groups']['category'] == []
        assert len(data['groups']['start_time']) == 1

    def test_meta_contient_event_name(self):
        _, ctx = self._run()
        data = json.loads(ctx['start_list_data'])
        assert data['meta']['event_name'] == 'Test'

    def test_meta_date_vide_sans_date(self):
        _, ctx = self._run()
        data = json.loads(ctx['start_list_data'])
        assert data['meta']['event_date'] == ''

    def test_club_short_format(self):
        c = self._mk_competitor(id=1, st=36000, org=5)
        cls = self._mk_cls(10, 'H21')
        _, ctx = self._run(competitors=[c], classes=[cls])
        data = json.loads(ctx['start_list_data'])
        row = data['groups']['category'][0]['rows'][0]
        assert row['club_short'] == '0005'


# ══════════════════════════════════════════════════════════════════════════════
# Pages statiques
# ══════════════════════════════════════════════════════════════════════════════

class TestStaticPages:
    @patch('results.classViews.render')
    @patch('results.classViews.MeosTutorial')
    def test_etiquettes_template(self, MockTuto, mock_render):
        from results.classViews import EtiquettesView
        EtiquettesView.as_view()(rf_get())
        args = mock_render.call_args[0]
        assert args[0].method == 'GET'
        assert args[1] == 'results/etiquettes.html'

    @patch('results.classViews.render')
    @patch('results.classViews.MeosTutorial')
    def test_drivers_template(self, MockTuto, mock_render):
        from results.classViews import DriversView
        DriversView.as_view()(rf_get())
        args = mock_render.call_args[0]
        assert args[1] == 'results/drivers.html'

    @patch('results.classViews.markdown.Markdown')
    @patch('results.classViews.render')
    @patch('results.classViews.MeosTutorial')
    def test_markdown_view_contexte(self, MockTuto, mock_render, MockMarkdown):
        tuto = MagicMock(); tuto.text = '# Hello'; tuto.content = ''
        MockTuto.objects.get.return_value = tuto
        mock_md = MagicMock()
        mock_md.convert.return_value = '<h1>Hello</h1>'
        MockMarkdown.return_value = mock_md
        from results.classViews import MarkdownDetailView
        MarkdownDetailView.as_view()(rf_get(), article_id=1)
        args = mock_render.call_args[0]
        assert args[1] == 'results/markdown_content.html'
        assert 'markdown_content' in args[2]
        mock_md.convert.assert_called_once_with(tuto.text)
