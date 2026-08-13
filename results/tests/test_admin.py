"""
Tests pour l'admin Django de results (DB entièrement mockée via connection).
"""

from unittest.mock import patch, MagicMock

import pytest
from django.test import RequestFactory


def _make_admin():
    """Instancie CompetitionConfigAdmin avec le vrai modèle (sans DB)."""
    from results.admin import CompetitionConfigAdmin
    from results.models import CompetitionConfig
    return CompetitionConfigAdmin(CompetitionConfig, None)


# ─── _competition_name ────────────────────────────────────────────────────────

class TestCompetitionName:

    def _call(self, cid, row):
        from results.admin import _competition_name
        cur = MagicMock()
        cur.fetchone.return_value = row
        with patch('results.admin.connection') as mock_conn:
            mock_conn.cursor.return_value.__enter__ = lambda s: cur
            mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)
            return _competition_name(cid)

    def test_nom_trouve(self):
        assert self._call(1, ('Championnat',)) == 'Championnat'

    def test_aucune_ligne_retourne_cid(self):
        assert self._call(7, None) == '7'


# ─── get_queryset / _name / _date / permissions ───────────────────────────────

class TestCompetitionConfigAdmin:

    def test_get_queryset_cree_configurations_manquantes(self):
        inst = _make_admin()
        cur = MagicMock()
        cur.fetchall.return_value = [(1,), (2,), (3,)]
        with patch('results.admin.CompetitionConfig') as MockConfig, \
             patch('results.admin.connection') as mock_conn:
            mock_conn.cursor.return_value.__enter__ = lambda s: cur
            mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)
            MockConfig.objects.all.side_effect = [[MagicMock(cid=1)], 'final']
            inst.get_queryset(None)
            created = [c.kwargs['cid']
                       for c in MockConfig.objects.create.call_args_list]
            assert created == [2, 3]

    def test_get_queryset_aucune_creation_si_tout_existe(self):
        inst = _make_admin()
        cur = MagicMock()
        cur.fetchall.return_value = [(1,)]
        with patch('results.admin.CompetitionConfig') as MockConfig, \
             patch('results.admin.connection') as mock_conn:
            mock_conn.cursor.return_value.__enter__ = lambda s: cur
            mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)
            MockConfig.objects.all.side_effect = [[MagicMock(cid=1)], MagicMock()]
            inst.get_queryset(None)
            MockConfig.objects.create.assert_not_called()

    def test_get_queryset_purge_configs_orphelines(self):
        inst = _make_admin()
        cur = MagicMock()
        cur.fetchall.return_value = [(1,), (2,)]
        with patch('results.admin.CompetitionConfig') as MockConfig, \
             patch('results.admin.connection') as mock_conn:
            mock_conn.cursor.return_value.__enter__ = lambda s: cur
            mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)
            MockConfig.objects.all.side_effect = [
                [MagicMock(cid=1), MagicMock(cid=2), MagicMock(cid=3)],
                MagicMock(),
            ]
            inst.get_queryset(None)
            MockConfig.objects.create.assert_not_called()
            MockConfig.objects.filter.assert_called_once_with(cid__in={3})
            MockConfig.objects.filter.return_value.delete.assert_called_once_with()

    def test_get_queryset_pas_de_purge_si_aucune_orpheline(self):
        inst = _make_admin()
        cur = MagicMock()
        cur.fetchall.return_value = [(1,), (2,)]
        with patch('results.admin.CompetitionConfig') as MockConfig, \
             patch('results.admin.connection') as mock_conn:
            mock_conn.cursor.return_value.__enter__ = lambda s: cur
            mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)
            MockConfig.objects.all.side_effect = [[MagicMock(cid=1), MagicMock(cid=2)], MagicMock()]
            inst.get_queryset(None)
            MockConfig.objects.filter.assert_not_called()

    def test_name_et_date(self):
        inst = _make_admin()
        cur = MagicMock()
        cur.fetchone.side_effect = [('Mon Comp',), ('2026-01-01',)]
        with patch('results.admin.connection') as mock_conn:
            mock_conn.cursor.return_value.__enter__ = lambda s: cur
            mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)
            obj = MagicMock(cid=3)
            assert inst._name(obj) == 'Mon Comp'
            assert inst._date(obj) == '2026-01-01'

    def test_date_inconnue_tiret(self):
        inst = _make_admin()
        cur = MagicMock()
        cur.fetchone.return_value = None
        with patch('results.admin.connection') as mock_conn:
            mock_conn.cursor.return_value.__enter__ = lambda s: cur
            mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)
            assert inst._date(MagicMock(cid=3)) == '—'

    def test_get_actions_vide(self):
        inst = _make_admin()
        assert inst.get_actions(None) == {}

    def test_has_delete_permission_false(self):
        inst = _make_admin()
        assert inst.has_delete_permission(None) is False


# ─── changeform_view ──────────────────────────────────────────────────────────

class TestChangeformView:

    @patch('results.admin.reverse')
    @patch('results.admin.messages')
    def test_delete_mop_data_post(self, mock_messages, mock_reverse):
        from results.admin import CompetitionConfigAdmin, MEOS_TABLES
        inst = CompetitionConfigAdmin.__new__(CompetitionConfigAdmin)
        inst.model = MagicMock()
        cur = MagicMock()
        request = RequestFactory().post('/change/1/', {'_delete_mop_data': '1'})
        obj = MagicMock(cid=5)
        mock_reverse.return_value = '/admin/results/competitionconfig/'
        with patch.object(CompetitionConfigAdmin, 'get_object', return_value=obj), \
             patch.object(CompetitionConfigAdmin, 'message_user') as mock_msg, \
             patch('results.admin.CompetitionConfig') as MockConfig, \
             patch('results.admin.connection') as mock_conn:
            mock_conn.cursor.return_value.__enter__ = lambda s: cur
            mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)
            response = inst.changeform_view(request, object_id='5')
        assert cur.execute.call_count == len(MEOS_TABLES) + 1  # +1: nom de compétition (message)
        deletes = [c[0][0] for c in cur.execute.call_args_list if 'DELETE' in c[0][0]]
        assert len(deletes) == len(MEOS_TABLES)
        assert any('mopCompetition' in sql for sql in deletes)
        MockConfig.objects.filter.assert_called_once_with(cid=5)
        MockConfig.objects.filter.return_value.delete.assert_called_once_with()
        mock_msg.assert_called_once()
        assert response.status_code == 302

    def test_post_sans_flag_delegue_super(self):
        from results.admin import CompetitionConfigAdmin
        inst = CompetitionConfigAdmin.__new__(CompetitionConfigAdmin)
        inst.model = MagicMock()
        request = RequestFactory().post('/change/5', {})
        with patch.object(CompetitionConfigAdmin, 'get_object', return_value=MagicMock(cid=1)), \
             patch('django.contrib.admin.options.ModelAdmin.changeform_view') as mock_super:
            mock_super.return_value = 'super-result'
            result = inst.changeform_view(request, object_id='5')
        assert result == 'super-result'

    def test_get_delegue_super(self):
        from results.admin import CompetitionConfigAdmin
        inst = CompetitionConfigAdmin.__new__(CompetitionConfigAdmin)
        inst.model = MagicMock()
        request = RequestFactory().get('/change/5/')
        with patch.object(CompetitionConfigAdmin, 'get_object', return_value=MagicMock(cid=1)), \
             patch('django.contrib.admin.options.ModelAdmin.changeform_view') as mock_super:
            mock_super.return_value = 'super-get'
            result = inst.changeform_view(request, object_id='5')
        assert result == 'super-get'