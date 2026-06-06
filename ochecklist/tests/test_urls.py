"""
Tests pour le routage de ochecklist/urls.py.

Couvre :
  - Résolution de chaque URL nommée vers la bonne vue
  - Présence de toutes les routes dans urlpatterns
"""

import pytest
from django.urls import resolve, reverse, NoReverseMatch

from ochecklist import views as ochecklist_views
from ochecklist.views import (
    ochecklist_update,
    report_list,
    clear_reports,
    report_detail,
    runner_detail,
)


# ─── Tests résolution d'URL ───────────────────────────────────────────────────

class TestURLResolution:
    """Vérifie que chaque URL résout vers la bonne fonction de vue."""

    def test_update_url_resout(self):
        match = resolve('/ochecklist/update/')
        assert match.func is ochecklist_update

    def test_update_url_nom(self):
        assert reverse('ochecklist_update') == '/ochecklist/update/'

    def test_report_list_url_resout(self):
        match = resolve('/ochecklist/')
        assert match.func is report_list

    def test_report_list_url_nom(self):
        assert reverse('ochecklist_report_list') == '/ochecklist/'

    def test_clear_url_resout(self):
        match = resolve('/ochecklist/clear/')
        assert match.func is clear_reports

    def test_clear_url_nom(self):
        assert reverse('ochecklist_clear_reports') == '/ochecklist/clear/'

    def test_report_detail_url_resout(self):
        match = resolve('/ochecklist/42/')
        assert match.func is report_detail
        assert match.kwargs == {'report_id': 42}

    def test_report_detail_url_nom(self):
        assert reverse('ochecklist_report_detail',
                       args=[99]) == '/ochecklist/99/'

    def test_runner_detail_url_resout(self):
        match = resolve('/ochecklist/runner/7/')
        assert match.func is runner_detail
        assert match.kwargs == {'runner_id': 7}

    def test_runner_detail_url_nom(self):
        assert reverse('ochecklist_runner_detail',
                       args=[3]) == '/ochecklist/runner/3/'


# ─── Tests reverse avec kwargs ────────────────────────────────────────────────

class TestURLReverse:

    def test_report_detail_kwargs(self):
        url = reverse('ochecklist_report_detail', kwargs={'report_id': 123})
        assert url == '/ochecklist/123/'

    def test_runner_detail_kwargs(self):
        url = reverse('ochecklist_runner_detail', kwargs={'runner_id': 456})
        assert url == '/ochecklist/runner/456/'

    def test_update_kwargs_vides(self):
        """L'URL update/ n'a pas de paramètres."""
        assert reverse('ochecklist_update', kwargs={}) == '/ochecklist/update/'


# ─── Tests urlpatterns ────────────────────────────────────────────────────────

class TestURLPatterns:
    """Vérifie l'intégrité de la liste urlpatterns."""

    def test_5_routes(self):
        from ochecklist.urls import urlpatterns
        assert len(urlpatterns) == 5

    def test_toutes_les_noms_distincts(self):
        from ochecklist.urls import urlpatterns
        names = [p.name for p in urlpatterns]
        assert len(set(names)) == len(names)

    def test_noms_attendus(self):
        from ochecklist.urls import urlpatterns
        names = sorted([p.name for p in urlpatterns])
        assert names == sorted([
            'ochecklist_update',
            'ochecklist_report_list',
            'ochecklist_clear_reports',
            'ochecklist_report_detail',
            'ochecklist_runner_detail',
        ])
