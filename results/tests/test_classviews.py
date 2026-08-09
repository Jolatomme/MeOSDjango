"""
Tests unitaires pour classViews.py.

Couvre :
  - TutoView (ListView de MeosTutorial)
  - has_individual_competitors (branches relais / individuel)
  - _months_ago et _days_in_month (rollover année, clamp fin de mois)
  - Branches 404 quand competition_visible retourne False
  - MarkdownDetailView (article inexistant)
"""

from unittest.mock import patch, MagicMock
import pytest
from django.test import RequestFactory
from django.http import Http404
from datetime import date


def rf_get(url='/'):
    return RequestFactory().get(url)


# ─── Tests TutoView ───────────────────────────────────────────────────────────

class TestTutoView:
    """Vérifie le comportement de TutoView (ListView)."""

    def test_template_name(self):
        """TutoView doit utiliser le bon template."""
        from results.classViews import TutoView
        assert TutoView.template_name == 'results/tuto.html'

    @patch('results.classViews.MeosTutorial')
    def test_get_queryset_retourne_tous_les_tutoriels(self, MockTutorial):
        """get_queryset doit retourner MeosTutorial.objects.all()."""
        tuto1 = MagicMock(); tuto1.title = 'Guide 1'
        tuto2 = MagicMock(); tuto2.title = 'Guide 2'
        MockTutorial.objects.all.return_value = [tuto1, tuto2]

        from results.classViews import TutoView
        view = TutoView()
        qs = view.get_queryset()

        MockTutorial.objects.all.assert_called_once()
        assert tuto1 in qs
        assert tuto2 in qs

    @patch('results.classViews.MeosTutorial')
    def test_get_queryset_vide_si_aucun_tutoriel(self, MockTutorial):
        """get_queryset doit retourner une liste vide s'il n'y a pas de tutoriels."""
        MockTutorial.objects.all.return_value = []

        from results.classViews import TutoView
        view = TutoView()
        qs = view.get_queryset()

        assert list(qs) == []

    @patch('results.classViews.MeosTutorial')
    def test_get_queryset_appele_all(self, MockTutorial):
        """get_queryset ne doit pas filtrer : il appelle .all()."""
        MockTutorial.objects.all.return_value = []

        from results.classViews import TutoView
        view = TutoView()
        view.get_queryset()

        # Vérifier qu'on appelle .all() et non .filter()
        MockTutorial.objects.all.assert_called_once()
        MockTutorial.objects.filter.assert_not_called()

    def test_tutoview_est_une_listview(self):
        """TutoView doit hériter de ListView."""
        from django.views.generic import ListView
        from results.classViews import TutoView
        assert issubclass(TutoView, ListView)


# ─── Tests CompetitionListView ────────────────────────────────────────────────

class TestCompetitionListView:
    """Vérifie le comportement de CompetitionListView (liste des compétitions)."""

    def test_template_name(self):
        """CompetitionListView doit utiliser le bon template."""
        from results.classViews import CompetitionListView
        assert CompetitionListView.template_name == 'results/competition_list.html'

    @patch('results.classViews.Mopcompetition')
    def test_get_queryset_retourne_toutes_les_competitions(self, MockComp):
        """get_queryset doit retourner Mopcompetition.objects.all()."""
        comps = [MagicMock(cid=1), MagicMock(cid=2)]
        MockComp.objects.all.return_value = comps

        from results.classViews import CompetitionListView
        view = CompetitionListView()
        qs = view.get_queryset()

        MockComp.objects.all.assert_called_once()
        assert list(qs) == comps

    @patch('results.classViews.Mopcompetition')
    def test_next_cid_max_plus_un(self, MockComp):
        """next_cid doit être le max(cid) + 1."""
        MockComp.objects.aggregate.return_value = {'max_cid': 42}

        from results.classViews import CompetitionListView
        view = CompetitionListView()
        view.object_list = []
        ctx = view.get_context_data()

        MockComp.objects.aggregate.assert_called_once()
        assert ctx['next_cid'] == 43

    @patch('results.classViews.Mopcompetition')
    def test_next_cid_si_table_vide(self, MockComp):
        """Si la table est vide, next_cid doit valoir 1."""
        MockComp.objects.aggregate.return_value = {'max_cid': None}

        from results.classViews import CompetitionListView
        view = CompetitionListView()
        view.object_list = []
        ctx = view.get_context_data()

        assert ctx['next_cid'] == 1

    @patch('results.classViews.Mopcompetition')
    @patch('results.classViews.render')
    def test_vue_entiere_rend_competitions_et_next_cid(self, mock_render, MockComp):
        """La vue rend le template avec les compétitions et le prochain CID."""
        comps = [MagicMock(cid=1), MagicMock(cid=2)]
        MockComp.objects.all.return_value = comps
        MockComp.objects.aggregate.return_value = {'max_cid': 2}

        from results.classViews import CompetitionListView
        CompetitionListView.as_view()(rf_get('/gec/competitions/'))

        _, template, ctx = mock_render.call_args[0]
        assert template == 'results/competition_list.html'
        assert list(ctx['competitions']) == comps
        assert ctx['next_cid'] == 3

    def test_competitionlistview_est_une_listview(self):
        """CompetitionListView doit hériter de ListView."""
        from django.views.generic import ListView
        from results.classViews import CompetitionListView
        assert issubclass(CompetitionListView, ListView)


# ─── Tests has_individual_competitors ─────────────────────────────────────────

class TestHasIndividualCompetitors:
    @patch('results.classViews.Mopcompetitor')
    @patch('results.classViews.Mopteam')
    def test_avec_relais_exclut_les_categories_relais(self, MockTeam, MockComp):
        """Des catégories relais existent → on exclut ces catégories."""
        MockTeam.objects.filter.return_value.values_list.return_value.distinct.return_value = [10, 11]
        MockComp.objects.filter.return_value.exclude.return_value.exists.return_value = True

        from results.classViews import has_individual_competitors
        assert has_individual_competitors(1) is True

        MockComp.objects.filter.assert_called_once_with(cid=1, st__gt=0)
        MockComp.objects.filter.return_value.exclude.assert_called_once_with(cls__in={10, 11})

    @patch('results.classViews.Mopcompetitor')
    @patch('results.classViews.Mopteam')
    def test_sans_relais_appelle_exists_directement(self, MockTeam, MockComp):
        """Aucune catégorie relais → exists() sans exclusion."""
        MockTeam.objects.filter.return_value.values_list.return_value.distinct.return_value = []
        MockComp.objects.filter.return_value.exists.return_value = False

        from results.classViews import has_individual_competitors
        assert has_individual_competitors(1) is False

        MockComp.objects.filter.return_value.exclude.assert_not_called()

    @patch('results.classViews.Mopcompetitor')
    @patch('results.classViews.Mopteam')
    def test_relay_class_ids_fournis_sans_requete_equipe(self, MockTeam, MockComp):
        """relay_class_ids fourni → pas de requête sur Mopteam."""
        MockComp.objects.filter.return_value.exclude.return_value.exists.return_value = True

        from results.classViews import has_individual_competitors
        assert has_individual_competitors(1, relay_class_ids={10}) is True

        MockTeam.objects.filter.assert_not_called()
        MockComp.objects.filter.return_value.exclude.assert_called_once_with(cls__in={10})


# ─── Tests _days_in_month / _months_ago ───────────────────────────────────────

class TestDaysInMonth:
    def test_decembre(self):
        from results.classViews import _days_in_month
        assert _days_in_month(2026, 12) == 31

    def test_fevrier_bissextile(self):
        from results.classViews import _days_in_month
        assert _days_in_month(2024, 2) == 29

    def test_fevrier_non_bissextile(self):
        from results.classViews import _days_in_month
        assert _days_in_month(2025, 2) == 28

    def test_avril(self):
        from results.classViews import _days_in_month
        assert _days_in_month(2026, 4) == 30


class TestMonthsAgo:
    def test_soustraction_simple(self):
        from results.classViews import _months_ago
        assert _months_ago(2, ref=date(2026, 8, 7)) == date(2026, 6, 7)

    def test_chevauchant_changement_d_annee(self):
        from results.classViews import _months_ago
        assert _months_ago(3, ref=date(2026, 2, 15)) == date(2025, 11, 15)

    def test_clamp_fin_de_mois_janvier(self):
        """31 janvier moins 1 mois → 31 décembre (clamp)."""
        from results.classViews import _months_ago
        assert _months_ago(1, ref=date(2026, 1, 31)) == date(2025, 12, 31)

    def test_clamp_fin_de_mois_fevrier(self):
        """31 mars moins 1 mois → 28 février (année non bissextile)."""
        from results.classViews import _months_ago
        assert _months_ago(1, ref=date(2026, 3, 31)) == date(2026, 2, 28)

    def test_zero_mois_retourne_la_reference(self):
        from results.classViews import _months_ago
        assert _months_ago(0, ref=date(2026, 7, 4)) == date(2026, 7, 4)

    def test_ref_par_defaut_aujourdhui(self):
        from results.classViews import _months_ago
        assert _months_ago(0) == date.today()


# ─── Tests branches 404 (competition_visible=False) ───────────────────────────

class TestCompetitionInvisible404:
    """Les vues doivent lever Http404 quand la compétition est invisible."""

    @patch('results.classViews.competition_visible', return_value=False)
    @patch('results.classViews.get_object_or_404')
    def test_competition_detail_leve_404(self, mock_get404, mock_visible):
        mock_get404.return_value = MagicMock(cid=1)
        from results.classViews import CompetitionDetailView
        view = CompetitionDetailView()
        view.kwargs = {'cid': 1}
        with pytest.raises(Http404):
            view.get_object()

    @patch('results.classViews.competition_visible', return_value=False)
    @patch('results.classViews.get_object_or_404')
    @patch('results.classViews.render')
    def test_start_list_leve_404(self, mock_render, mock_get404, mock_visible):
        mock_get404.return_value = MagicMock(cid=1)
        from results.classViews import StartListView
        with pytest.raises(Http404):
            StartListView.as_view()(rf_get(), cid=1)

    @patch('results.classViews.competition_visible', return_value=False)
    @patch('results.classViews.get_object_or_404')
    @patch('results.classViews.render')
    def test_statistics_leve_404(self, mock_render, mock_get404, mock_visible):
        mock_get404.return_value = MagicMock(cid=1)
        from results.classViews import StatisticsView
        with pytest.raises(Http404):
            StatisticsView.as_view()(rf_get(), cid=1)

    @patch('results.classViews.MeosTutorial')
    def test_markdown_article_inexistant_leve_404(self, MockTutorial):
        """MarkdownDetailView : article absent → Http404."""
        MockTutorial.DoesNotExist = KeyError
        MockTutorial.objects.get.side_effect = KeyError
        from results.classViews import MarkdownDetailView
        view = MarkdownDetailView()
        view.kwargs = {'article_id': 99}
        with pytest.raises(Http404):
            view.get_object()
