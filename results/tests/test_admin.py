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
            # La purge ne touche que les configs sans clé API
            # (une course créée depuis le site garde son secret)
            MockConfig.objects.filter.assert_called_once_with(
                cid__in={3}, api_key__isnull=True,
            )
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

    def test_get_actions_uniquement_revoquer_liens(self):
        """L'action custom est proposée ; delete_selected est masqué."""
        from django.contrib.admin import site as admin_site
        from results.admin import CompetitionConfigAdmin
        from results.models import CompetitionConfig
        inst = CompetitionConfigAdmin(CompetitionConfig, admin_site)
        request = RequestFactory().get('/admin/results/competitionconfig/')
        actions = inst.get_actions(request)
        assert 'revoke_manage_links' in actions
        # has_delete_permission → False : l'action de suppression est retirée
        assert 'delete_selected' not in actions

    def test_revoke_manage_links_action(self):
        """L'action révoque le jeton (manage_token → NULL), clé API intacte."""
        from results.admin import CompetitionConfigAdmin
        from results.models import CompetitionConfig
        inst = CompetitionConfigAdmin(CompetitionConfig, None)
        request = RequestFactory().post(
            '/admin/results/competitionconfig/',
            {'action': 'revoke_manage_links', '_selected_action': ['1']},
        )
        queryset = MagicMock()
        with patch.object(CompetitionConfigAdmin, 'message_user') as mock_msg:
            inst.revoke_manage_links(request, queryset)
        queryset.filter.assert_called_once_with(manage_token__isnull=False)
        queryset.filter.return_value.update.assert_called_once_with(
            manage_token=None,
        )
        mock_msg.assert_called_once()

    def test_has_delete_permission_false(self):
        inst = _make_admin()
        assert inst.has_delete_permission(None) is False

    def test_form_admin_accepte_les_fieldsets(self):
        """created_at (auto_now_add) doit être readonly, sinon FieldError."""
        from results.admin import CompetitionConfigAdmin
        from results.models import CompetitionConfig
        inst = CompetitionConfigAdmin(CompetitionConfig, None)
        request = RequestFactory().get(
            '/admin/results/competitionconfig/5/change/'
        )
        form_class = inst.get_form(
            request, obj=CompetitionConfig(cid=5), change=True,
        )
        assert 'created_at' not in form_class.base_fields
        assert 'livelox' in form_class.base_fields
        assert 'logo' in form_class.base_fields
        assert 'remove_logo' not in form_class.base_fields
        assert inst.fieldsets[1][1]['classes'] == ('co-race-info',)


# ─── Formulaire admin : livelox / logo (champs de mopCompetition) ─────────────

class TestCompetitionConfigAdminForm:

    def _form(self, competition, data=None, files=None):
        from results.admin import CompetitionConfigAdminForm
        from results.models import CompetitionConfig
        with patch('results.admin.Mopcompetition') as MockCompetition:
            MockCompetition.objects.filter.return_value.first.return_value = (
                competition
            )
            form = CompetitionConfigAdminForm(
                data=data, files=files,
                instance=CompetitionConfig(cid=5),
            )
        return form, MockCompetition

    def test_initial_livelox_et_lien_logo_actuel(self):
        competition = MagicMock(
            livelox='https://livelox.example/42',
            logo='logo-abc123.png',
        )
        form, MockCompetition = self._form(competition)

        MockCompetition.objects.filter.assert_called_once_with(cid=5, id=1)
        assert form.initial['livelox'] == 'https://livelox.example/42'
        assert 'logo-abc123.png' in str(form.fields['logo'].help_text)
        assert '/org_logo/logo-abc123.png' in str(
            form.fields['logo'].help_text
        )

    def test_sans_ligne_mopcompetition(self):
        form, _ = self._form(None)
        assert form._competition is None
        assert form.initial.get('livelox', '') == ''

    @patch('results.admin.delete_org_logo')
    def test_save_livelox_seul(self, mock_delete):
        competition = MagicMock(livelox='', logo='')
        form, MockCompetition = self._form(competition)
        form.cleaned_data = {
            'livelox': 'https://livelox.example/99',
            'logo': None,
        }

        with patch('results.admin.Mopcompetition', MockCompetition):
            form.save_competition_fields()

        MockCompetition.objects.filter.return_value.update.assert_called_once_with(
            livelox='https://livelox.example/99',
        )
        mock_delete.assert_not_called()

    @patch('results.admin.delete_org_logo')
    @patch('results.admin.save_org_logo', return_value='logo-new.png')
    def test_save_nouveau_logo_remplace_l_ancien(self, mock_save, mock_delete):
        from django.core.files.uploadedfile import SimpleUploadedFile
        competition = MagicMock(livelox='', logo='logo-old.png')
        form, MockCompetition = self._form(competition)
        upload = SimpleUploadedFile('club.png', b'\x89PNG\r\n\x1a\nx')
        form.cleaned_data = {
            'livelox': '',
            'logo': upload,
        }

        with patch('results.admin.Mopcompetition', MockCompetition):
            form.save_competition_fields()

        mock_save.assert_called_once_with(upload)
        MockCompetition.objects.filter.return_value.update.assert_called_once_with(
            logo='logo-new.png',
        )
        mock_delete.assert_called_once_with('logo-old.png')

    def test_save_sans_changement_ne_touche_pas_a_la_base(self):
        competition = MagicMock(
            livelox='https://livelox.example/42', logo='logo-old.png',
        )
        form, MockCompetition = self._form(competition)
        form.cleaned_data = {
            'livelox': 'https://livelox.example/42',
            'logo': None,
        }

        form.save_competition_fields()

        MockCompetition.objects.filter.return_value.update.assert_not_called()

    def test_save_sans_competition_ne_touche_pas_a_la_base(self):
        form, MockCompetition = self._form(None)
        form.cleaned_data = {'livelox': 'https://x.example', 'logo': None}

        form.save_competition_fields()

        MockCompetition.objects.filter.assert_called_once()
        MockCompetition.objects.filter.return_value.update.assert_not_called()

    def test_fieldset_course_contient_le_bouton_supprimer_logo(self):
        from django.contrib.admin.helpers import Fieldset
        from django.template.loader import render_to_string
        from results.admin import CompetitionConfigAdminForm
        from results.models import CompetitionConfig

        form = CompetitionConfigAdminForm(instance=CompetitionConfig())
        fieldset = Fieldset(
            form, name="Informations de la course",
            fields=['livelox', 'logo'], classes=('co-race-info',),
        )
        context = {
            'fieldset': fieldset,
            'heading_level': 2,
            'prefix': 'fieldset',
            'id_prefix': 0,
            'id_suffix': 1,
        }

        html = render_to_string(
            'admin/results/competitionconfig/fieldset.html',
            {**context, 'competition_logo': 'logo-abc.png'},
        )
        assert 'name="_delete_logo"' in html
        assert 'Supprimer le logo local' in html

        html = render_to_string(
            'admin/results/competitionconfig/fieldset.html',
            {**context, 'competition_logo': ''},
        )
        assert 'name="_delete_logo"' not in html

    def test_save_model_appelle_le_report_des_champs_course(self):
        from results.admin import CompetitionConfigAdmin
        from results.models import CompetitionConfig
        inst = CompetitionConfigAdmin(CompetitionConfig, None)
        form = MagicMock()
        request = RequestFactory().post('/change/5/')
        obj = MagicMock(cid=5)
        with patch('django.contrib.admin.options.ModelAdmin.save_model') as mock_super:
            inst.save_model(request, obj, form, change=True)
        mock_super.assert_called_once_with(request, obj, form, True)
        form.save_competition_fields.assert_called_once_with()


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

    @patch('results.admin.delete_org_logo')
    @patch('results.admin.reverse')
    @patch('results.admin.messages')
    def test_delete_logo_post(self, mock_messages, mock_reverse, mock_delete):
        from results.admin import CompetitionConfigAdmin
        inst = CompetitionConfigAdmin.__new__(CompetitionConfigAdmin)
        inst.model = MagicMock()
        request = RequestFactory().post('/change/5/', {'_delete_logo': '1'})
        obj = MagicMock(cid=5, pk=5)
        mock_reverse.return_value = '/admin/results/competitionconfig/5/change/'
        competition = MagicMock(logo='logo-old.png')
        with patch.object(CompetitionConfigAdmin, 'get_object', return_value=obj), \
             patch.object(CompetitionConfigAdmin, 'message_user') as mock_msg, \
             patch('results.admin.Mopcompetition') as MockCompetition:
            MockCompetition.objects.filter.return_value.first.return_value = (
                competition
            )
            response = inst.changeform_view(request, object_id='5')
        MockCompetition.objects.filter.return_value.update.assert_called_once_with(
            logo='',
        )
        mock_delete.assert_called_once_with('logo-old.png')
        mock_msg.assert_called_once()
        assert response.status_code == 302

    @patch('results.admin.delete_org_logo')
    @patch('results.admin.reverse')
    @patch('results.admin.messages')
    def test_delete_logo_sans_logo(self, mock_messages, mock_reverse, mock_delete):
        from results.admin import CompetitionConfigAdmin
        inst = CompetitionConfigAdmin.__new__(CompetitionConfigAdmin)
        inst.model = MagicMock()
        request = RequestFactory().post('/change/5/', {'_delete_logo': '1'})
        obj = MagicMock(cid=5, pk=5)
        mock_reverse.return_value = '/admin/results/competitionconfig/5/change/'
        competition = MagicMock(logo='')
        with patch.object(CompetitionConfigAdmin, 'get_object', return_value=obj), \
             patch.object(CompetitionConfigAdmin, 'message_user') as mock_msg, \
             patch('results.admin.Mopcompetition') as MockCompetition:
            MockCompetition.objects.filter.return_value.first.return_value = (
                competition
            )
            response = inst.changeform_view(request, object_id='5')
        MockCompetition.objects.filter.return_value.update.assert_not_called()
        mock_delete.assert_not_called()
        mock_msg.assert_called_once()
        assert response.status_code == 302

    def test_get_ajoute_le_logo_au_contexte(self):
        from results.admin import CompetitionConfigAdmin
        inst = CompetitionConfigAdmin.__new__(CompetitionConfigAdmin)
        inst.model = MagicMock()
        request = RequestFactory().get('/change/5/')
        obj = MagicMock(cid=5)
        competition = MagicMock(logo='logo-old.png')
        with patch.object(CompetitionConfigAdmin, 'get_object', return_value=obj), \
             patch('results.admin.Mopcompetition') as MockCompetition, \
             patch('django.contrib.admin.options.ModelAdmin.changeform_view') as mock_super:
            MockCompetition.objects.filter.return_value.first.return_value = (
                competition
            )
            mock_super.return_value = 'super-get'
            inst.changeform_view(request, object_id='5')
        assert mock_super.call_args.args[3] == {
            'competition_logo': 'logo-old.png',
        }

    def test_post_sans_flag_delegue_super(self):
        from results.admin import CompetitionConfigAdmin
        inst = CompetitionConfigAdmin.__new__(CompetitionConfigAdmin)
        inst.model = MagicMock()
        request = RequestFactory().post('/change/5', {})
        with patch.object(CompetitionConfigAdmin, 'get_object', return_value=MagicMock(cid=1)), \
             patch('results.admin.Mopcompetition') as MockCompetition, \
             patch('django.contrib.admin.options.ModelAdmin.changeform_view') as mock_super:
            MockCompetition.objects.filter.return_value.first.return_value = None
            mock_super.return_value = 'super-result'
            result = inst.changeform_view(request, object_id='5')
        assert result == 'super-result'

    def test_get_delegue_super(self):
        from results.admin import CompetitionConfigAdmin
        inst = CompetitionConfigAdmin.__new__(CompetitionConfigAdmin)
        inst.model = MagicMock()
        request = RequestFactory().get('/change/5/')
        with patch.object(CompetitionConfigAdmin, 'get_object', return_value=MagicMock(cid=1)), \
             patch('results.admin.Mopcompetition') as MockCompetition, \
             patch('django.contrib.admin.options.ModelAdmin.changeform_view') as mock_super:
            MockCompetition.objects.filter.return_value.first.return_value = None
            mock_super.return_value = 'super-get'
            result = inst.changeform_view(request, object_id='5')
        assert result == 'super-get'