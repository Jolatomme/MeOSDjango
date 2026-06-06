"""
Tests unitaires pour ochecklist/models.py.

Aucune DB requise : on inspecte les définitions de champs via _meta.
"""

import pytest
from django.db import models

from ochecklist.models import OchecklistReport, OchecklistRunner, OchecklistChangeLog


# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_field(model, name):
    return model._meta.get_field(name)


# ─── Tests OchecklistReport ───────────────────────────────────────────────────

class TestOchecklistReportModel:
    """Vérifie la définition du modèle OchecklistReport."""

    def test_meta_ordering(self):
        assert OchecklistReport._meta.ordering == ['-created']

    def test_verbose_name(self):
        assert OchecklistReport._meta.verbose_name == "O'checklist Report"

    def test_verbose_name_plural(self):
        assert OchecklistReport._meta.verbose_name_plural == "O'checklist Reports"

    def test_app_label(self):
        assert OchecklistReport._meta.app_label == 'ochecklist'

    # ── Champs ────────────────────────────────────────────────────────────────

    def test_version_charfield(self):
        f = get_field(OchecklistReport, 'version')
        assert isinstance(f, models.CharField)
        assert f.max_length == 10

    def test_creator_charfield(self):
        f = get_field(OchecklistReport, 'creator')
        assert isinstance(f, models.CharField)
        assert f.max_length == 100

    def test_created_datetimefield(self):
        f = get_field(OchecklistReport, 'created')
        assert isinstance(f, models.DateTimeField)
        assert f.null is False
        assert f.blank is False
        assert f.auto_now_add is False

    def test_event_nullable(self):
        f = get_field(OchecklistReport, 'event')
        assert isinstance(f, models.CharField)
        assert f.max_length == 200
        assert f.null is True
        assert f.blank is True

    def test_received_at_auto_now_add(self):
        f = get_field(OchecklistReport, 'received_at')
        assert isinstance(f, models.DateTimeField)
        assert f.auto_now_add is True

    def test_primary_key_auto(self):
        f = get_field(OchecklistReport, 'id')
        assert f.primary_key is True


# ─── Tests OchecklistRunner ────────────────────────────────────────────────────

class TestOchecklistRunnerModel:
    """Vérifie la définition du modèle OchecklistRunner."""

    def test_meta_ordering(self):
        assert OchecklistRunner._meta.ordering == ['start_time']

    def test_verbose_name(self):
        assert OchecklistRunner._meta.verbose_name == "O'checklist Runner"

    def test_verbose_name_plural(self):
        assert OchecklistRunner._meta.verbose_name_plural == "O'checklist Runners"

    def test_status_choices(self):
        """STATUS_CHOICES contient exactement les 3 statuts attendus."""
        assert OchecklistRunner.STATUS_CHOICES == [
            ('Started OK', 'Started OK'),
            ('DNS', 'DNS'),
            ('Late start', 'Late start'),
        ]

    # ── Foreign key vers OchecklistReport ─────────────────────────────────────

    def test_report_fk_related_name(self):
        f = get_field(OchecklistRunner, 'report')
        assert isinstance(f, models.ForeignKey)
        assert f.related_model is OchecklistReport
        assert f.remote_field.related_name == 'runners'

    def test_report_fk_cascade_delete(self):
        f = get_field(OchecklistRunner, 'report')
        assert f.remote_field.on_delete is models.CASCADE

    # ── Champs optionnels (null=True) ─────────────────────────────────────────

    def test_runner_id_optional(self):
        f = get_field(OchecklistRunner, 'runner_id')
        assert isinstance(f, models.CharField)
        assert f.max_length == 50
        assert f.null is True
        assert f.blank is True

    def test_bib_optional(self):
        f = get_field(OchecklistRunner, 'bib')
        assert isinstance(f, models.CharField)
        assert f.max_length == 20
        assert f.null is True
        assert f.blank is True

    def test_card_number_optional(self):
        f = get_field(OchecklistRunner, 'card_number')
        assert isinstance(f, models.CharField)
        assert f.max_length == 20
        assert f.null is True
        assert f.blank is True

    def test_start_time_optional(self):
        f = get_field(OchecklistRunner, 'start_time')
        assert isinstance(f, models.DateTimeField)
        assert f.null is True
        assert f.blank is True

    def test_new_card_optional(self):
        f = get_field(OchecklistRunner, 'new_card')
        assert isinstance(f, models.CharField)
        assert f.max_length == 20
        assert f.null is True
        assert f.blank is True

    def test_comment_optional(self):
        f = get_field(OchecklistRunner, 'comment')
        assert isinstance(f, models.TextField)
        assert f.null is True
        assert f.blank is True

    # ── Champs obligatoires ───────────────────────────────────────────────────

    def test_name_obligatoire(self):
        f = get_field(OchecklistRunner, 'name')
        assert isinstance(f, models.CharField)
        assert f.max_length == 100
        assert f.null is False
        assert f.blank is False

    def test_org_obligatoire(self):
        f = get_field(OchecklistRunner, 'org')
        assert isinstance(f, models.CharField)
        assert f.max_length == 100
        assert f.null is False

    def test_class_name_obligatoire(self):
        f = get_field(OchecklistRunner, 'class_name')
        assert isinstance(f, models.CharField)
        assert f.max_length == 50
        assert f.null is False

    def test_start_status_obligatoire(self):
        f = get_field(OchecklistRunner, 'start_status')
        assert isinstance(f, models.CharField)
        assert f.max_length == 20
        assert f.null is False
        assert f.choices == OchecklistRunner.STATUS_CHOICES


# ─── Tests OchecklistChangeLog ─────────────────────────────────────────────────

class TestOchecklistChangeLogModel:
    """Vérifie la définition du modèle OchecklistChangeLog."""

    def test_verbose_name(self):
        assert OchecklistChangeLog._meta.verbose_name == "O'checklist Change Log"

    def test_verbose_name_plural(self):
        assert (
            OchecklistChangeLog._meta.verbose_name_plural
            == "O'checklist Change Logs"
        )

    def test_runner_one_to_one(self):
        f = get_field(OchecklistChangeLog, 'runner')
        assert isinstance(f, models.OneToOneField)
        assert f.related_model is OchecklistRunner
        assert f.remote_field.related_name == 'changelog'

    def test_runner_cascade_delete(self):
        f = get_field(OchecklistChangeLog, 'runner')
        assert f.remote_field.on_delete is models.CASCADE

    # ── Tous les timestamps sont nullables ────────────────────────────────────

    def _test_nullable_datetime(self, field_name):
        f = get_field(OchecklistChangeLog, field_name)
        assert isinstance(f, models.DateTimeField)
        assert f.null is True
        assert f.blank is True

    def test_dns_nullable(self):
        self._test_nullable_datetime('dns')

    def test_late_start_nullable(self):
        self._test_nullable_datetime('late_start')

    def test_new_card_nullable(self):
        self._test_nullable_datetime('new_card')

    def test_comment_nullable(self):
        self._test_nullable_datetime('comment')

    def test_new_runner_nullable(self):
        self._test_nullable_datetime('new_runner')
