"""
Tests unitaires pour classViews.py.

Couvre :
  - TutoView (ListView de MeosTutorial)
"""

from unittest.mock import patch, MagicMock
import pytest
from django.test import RequestFactory


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
