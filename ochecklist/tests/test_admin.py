"""
Tests pour ochecklist/admin.py.

Couvre :
  - Enregistrement des 3 modèles auprès de l'admin Django
  - Méthodes d'affichage : runner_count, has_changelog, report_link,
    runner_name
"""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib import admin

from ochecklist.admin import (
    OchecklistReportAdmin,
    OchecklistRunnerAdmin,
    OchecklistChangeLogAdmin,
)
from ochecklist.models import (
    OchecklistReport,
    OchecklistRunner,
    OchecklistChangeLog,
)


# ─── Tests enregistrement ─────────────────────────────────────────────────────

class TestAdminRegistration:
    """Vérifie que les 3 modèles sont enregistrés avec la bonne classe."""

    def test_report_model_enregistre(self):
        assert OchecklistReport in admin.site._registry

    def test_report_admin_class(self):
        assert isinstance(
            admin.site._registry[OchecklistReport],
            OchecklistReportAdmin,
        )

    def test_runner_model_enregistre(self):
        assert OchecklistRunner in admin.site._registry

    def test_runner_admin_class(self):
        assert isinstance(
            admin.site._registry[OchecklistRunner],
            OchecklistRunnerAdmin,
        )

    def test_changelog_model_enregistre(self):
        assert OchecklistChangeLog in admin.site._registry

    def test_changelog_admin_class(self):
        assert isinstance(
            admin.site._registry[OchecklistChangeLog],
            OchecklistChangeLogAdmin,
        )


# ─── Tests OchecklistReportAdmin ──────────────────────────────────────────────

class TestOchecklistReportAdmin:

    def test_list_display(self):
        assert OchecklistReportAdmin.list_display == [
            'event', 'creator', 'created', 'received_at', 'runner_count',
        ]

    def test_list_filter(self):
        assert OchecklistReportAdmin.list_filter == ['created', 'received_at']

    def test_search_fields(self):
        assert OchecklistReportAdmin.search_fields == ['event', 'creator']

    def test_readonly_fields(self):
        assert OchecklistReportAdmin.readonly_fields == ['received_at']

    def test_runner_count(self):
        obj = MagicMock()
        obj.runners.count.return_value = 5
        admin_inst = OchecklistReportAdmin(OchecklistReport, admin.site)
        assert admin_inst.runner_count(obj) == 5
        obj.runners.count.assert_called_once()

    def test_runner_count_zero(self):
        obj = MagicMock()
        obj.runners.count.return_value = 0
        admin_inst = OchecklistReportAdmin(OchecklistReport, admin.site)
        assert admin_inst.runner_count(obj) == 0

    def test_runner_count_short_description(self):
        assert OchecklistReportAdmin.runner_count.short_description == 'Runners'


# ─── Tests OchecklistRunnerAdmin ──────────────────────────────────────────────

class TestOchecklistRunnerAdmin:

    def test_list_display(self):
        assert OchecklistRunnerAdmin.list_display == [
            'name', 'org', 'class_name', 'start_status',
            'report_link', 'has_changelog',
        ]

    def test_list_filter(self):
        assert OchecklistRunnerAdmin.list_filter == [
            'start_status', 'class_name', 'org', 'report__created',
        ]

    def test_search_fields(self):
        assert OchecklistRunnerAdmin.search_fields == [
            'name', 'org', 'bib', 'runner_id',
        ]

    def test_readonly_fields(self):
        assert OchecklistRunnerAdmin.readonly_fields == ['report_link']

    def test_has_changelog_true(self):
        class FakeRunner:
            pass
        runner = FakeRunner()
        runner.changelog = MagicMock()
        admin_inst = OchecklistRunnerAdmin(OchecklistRunner, admin.site)
        assert admin_inst.has_changelog(runner) is True

    def test_has_changelog_false(self):
        class FakeRunner:
            pass
        runner = FakeRunner()
        admin_inst = OchecklistRunnerAdmin(OchecklistRunner, admin.site)
        assert admin_inst.has_changelog(runner) is False

    def test_has_changelog_short_description(self):
        assert OchecklistRunnerAdmin.has_changelog.short_description == 'Has Changelog'

    def test_has_changelog_is_boolean(self):
        """La méthode est marquée comme bool pour l'admin (icône ✓/✗)."""
        assert OchecklistRunnerAdmin.has_changelog.boolean is True

    def test_report_link(self):
        obj = MagicMock()
        obj.report.id = 7
        obj.report.event = 'Mon Event'
        with patch('django.urls.reverse',
                   return_value='/admin/ochecklist/ochecklistreport/7/change/') as mock_reverse:
            admin_inst = OchecklistRunnerAdmin(OchecklistRunner, admin.site)
            html = admin_inst.report_link(obj)
        mock_reverse.assert_called_once_with(
            'admin:ochecklist_ochecklistreport_change', args=[7],
        )
        assert '/admin/ochecklist/ochecklistreport/7/change/' in html
        assert 'Mon Event' in html

    def test_report_link_short_description(self):
        assert OchecklistRunnerAdmin.report_link.short_description == 'Report'


# ─── Tests OchecklistChangeLogAdmin ───────────────────────────────────────────

class TestOchecklistChangeLogAdmin:

    def test_list_display(self):
        assert OchecklistChangeLogAdmin.list_display == [
            'runner_name', 'dns', 'late_start', 'new_card',
            'comment', 'new_runner',
        ]

    def test_list_filter(self):
        assert OchecklistChangeLogAdmin.list_filter == [
            'dns', 'late_start', 'new_card', 'comment', 'new_runner',
        ]

    def test_search_fields(self):
        assert OchecklistChangeLogAdmin.search_fields == [
            'runner__name', 'runner__org',
        ]

    def test_runner_name(self):
        obj = MagicMock()
        obj.runner.name = 'Jean Dupont'
        admin_inst = OchecklistChangeLogAdmin(OchecklistChangeLog, admin.site)
        assert admin_inst.runner_name(obj) == 'Jean Dupont'

    def test_runner_name_short_description(self):
        assert (
            OchecklistChangeLogAdmin.runner_name.short_description == 'Runner'
        )
