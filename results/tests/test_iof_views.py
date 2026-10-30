"""
Tests de la page privée d'import IOF (DB mockée).

Couvre le rendu du formulaire, l'analyse sans écriture, la confirmation
obligatoire avant remplacement, l'import réussi, le gel et les erreurs.
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.messages.storage.cookie import CookieStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.test import RequestFactory
from django.urls import reverse

from results.iof_importer import IofImportError, IofImportReport

TOKEN = 'jeton-prive-abc'
URL = f'/gestion-course/{TOKEN}/importer-iof/'


def rf():
    return RequestFactory()


def _config(cid=9, token=TOKEN):
    return SimpleNamespace(cid=cid, manage_token=token, api_key='k' * 43)


def _competition():
    return SimpleNamespace(
        name='Trail de Test',
        date=date(2026, 5, 17),
        organizer='COCS 73',
        homepage='https://example.org',
        livelox='',
    )


def _upload(content=b'<ResultList xmlns="http://www.orienteering.org/datastandard/3.0"/>',
            name='resultats.xml'):
    return SimpleUploadedFile(name, content, content_type='application/xml')


def _report(status='DRY-RUN'):
    return IofImportReport(
        status=status,
        race_number=None,
        competition_name='Championnat test',
        classes=2,
        competitors=3,
        teams=0,
        controls=4,
        splits=5,
        warnings=['Un avertissement'],
        class_ids=[10, 20],
        course_hashes=['abcd1234'],
    )


def _post(data=None, **extra):
    payload = {
        'action': 'inspect',
        'ioffile': _upload(),
        'race_number': '',
        'use_event_metadata': '',
        'confirm': '',
    }
    payload.update(data or {})
    payload.update(extra)
    return rf().post(URL, payload)


# ─── GET ──────────────────────────────────────────────────────────────────────

class TestGet:

    @patch('results.race_views.Mopcompetition')
    @patch('results.race_views.CompetitionConfig')
    def test_affiche_le_formulaire(self, MockConfig, MockComp):
        MockConfig.objects.filter.return_value.first.return_value = _config()
        MockComp.objects.filter.return_value.first.return_value = _competition()

        from results.race_views import RaceImportIofView
        response = RaceImportIofView.as_view()(rf().get(URL), token=TOKEN)

        assert response.status_code == 200
        content = response.content.decode()
        assert 'Importer des résultats IOF' in content
        assert 'name="ioffile"' in content
        assert 'name="race_number"' in content
        assert 'name="use_event_metadata"' in content
        assert 'name="confirm"' in content
        assert 'value="inspect"' in content
        assert 'value="import"' in content
        assert f'/gestion-course/{TOKEN}/' in content
        assert 'Trail de Test' in content

    @patch('results.race_views.CompetitionConfig')
    def test_jeton_invalide_404(self, MockConfig):
        MockConfig.objects.filter.return_value.first.return_value = None

        from results.race_views import RaceImportIofView
        with pytest.raises(Http404):
            RaceImportIofView.as_view()(rf().get(URL), token=TOKEN)

    def test_sans_jeton_404(self):
        from results.race_views import RaceImportIofView
        with pytest.raises(Http404):
            RaceImportIofView.as_view()(rf().get(URL), token='')

    def test_url_reverse(self):
        assert reverse('results:race_import_iof', kwargs={'token': TOKEN}) == URL


# ─── POST : analyse ──────────────────────────────────────────────────────────

class TestInspect:

    @patch('results.race_views.import_iof_result_list')
    @patch('results.race_views.inspect_iof_result_list', return_value=_report())
    @patch('results.race_views.Mopcompetition')
    @patch('results.race_views.CompetitionConfig')
    def test_analyse_sans_ecriture(
            self, MockConfig, MockComp, mock_inspect, mock_import):
        MockConfig.objects.filter.return_value.first.return_value = _config()
        MockComp.objects.filter.return_value.first.return_value = _competition()

        from results.race_views import RaceImportIofView
        request = _post({'race_number': '2', 'use_event_metadata': 'on'})
        response = RaceImportIofView.as_view()(request, token=TOKEN)

        assert response.status_code == 200
        mock_inspect.assert_called_once()
        args, kwargs = mock_inspect.call_args
        assert args[0].startswith(b'<ResultList')
        assert kwargs == {
            'cid': 9,
            'race_number': 2,
            'use_event_metadata': True,
        }
        mock_import.assert_not_called()

        content = response.content.decode()
        assert 'Analyse — aucune écriture' in content
        assert 'Championnat test' in content
        assert 'Un avertissement' in content
        assert '>2<' in content       # classes
        assert '>3<' in content       # concurrents

    @patch('results.race_views.inspect_iof_result_list',
            side_effect=IofImportError('Fichier invalide'))
    @patch('results.race_views.Mopcompetition')
    @patch('results.race_views.CompetitionConfig')
    def test_erreur_de_parsing_affichee(
            self, MockConfig, MockComp, mock_inspect):
        MockConfig.objects.filter.return_value.first.return_value = _config()
        MockComp.objects.filter.return_value.first.return_value = _competition()

        from results.race_views import RaceImportIofView
        response = RaceImportIofView.as_view()(_post(), token=TOKEN)

        assert response.status_code == 200
        assert 'Fichier invalide' in response.content.decode()


# ─── POST : import ───────────────────────────────────────────────────────────

class TestImport:

    @patch('results.race_views.import_iof_result_list', return_value=_report('OK'))
    @patch('results.race_views.Mopcompetition')
    @patch('results.race_views.CompetitionConfig')
    def test_import_sans_confirmation_refuse(
            self, MockConfig, MockComp, mock_import):
        MockConfig.objects.filter.return_value.first.return_value = _config()
        MockComp.objects.filter.return_value.first.return_value = _competition()

        from results.race_views import RaceImportIofView
        response = RaceImportIofView.as_view()(
            _post({'action': 'import'}), token=TOKEN,
        )

        assert response.status_code == 200
        mock_import.assert_not_called()
        assert 'Cochez la case de confirmation' in response.content.decode()

    @patch('results.race_views.import_iof_result_list', return_value=_report('OK'))
    @patch('results.race_views.Mopcompetition')
    @patch('results.race_views.CompetitionConfig')
    def test_import_confirme_redirige_et_message(
            self, MockConfig, MockComp, mock_import):
        MockConfig.objects.filter.return_value.first.return_value = _config()
        MockComp.objects.filter.return_value.first.return_value = _competition()

        from results.race_views import RaceImportIofView
        request = _post({
            'action': 'import',
            'confirm': 'on',
            'race_number': '1',
            'use_event_metadata': 'on',
        })
        request._messages = CookieStorage(request)
        response = RaceImportIofView.as_view()(request, token=TOKEN)

        assert response.status_code == 302
        assert response['Location'] == f'/gestion-course/{TOKEN}/?ok=iof'
        mock_import.assert_called_once()
        args, kwargs = mock_import.call_args
        assert args[0] == 9
        assert args[1].startswith(b'<ResultList')
        assert kwargs == {'race_number': 1, 'use_event_metadata': True}

        flash = ' '.join(str(message) for message in request._messages)
        assert 'Résultats IOF importés' in flash
        assert '2 classe(s)' in flash
        assert '3 concurrent(s)' in flash

    @patch('results.race_views.import_iof_result_list', return_value=_report('FROZEN'))
    @patch('results.race_views.Mopcompetition')
    @patch('results.race_views.CompetitionConfig')
    def test_course_gelee_affiche_une_erreur(
            self, MockConfig, MockComp, mock_import):
        MockConfig.objects.filter.return_value.first.return_value = _config()
        MockComp.objects.filter.return_value.first.return_value = _competition()

        from results.race_views import RaceImportIofView
        response = RaceImportIofView.as_view()(
            _post({'action': 'import', 'confirm': 'on'}), token=TOKEN,
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert 'course est gelée' in content
        assert 'Course gelée' in content

    @patch('results.race_views.import_iof_result_list',
            side_effect=IofImportError("L'import a échoué (statut MOP : ERROR)."))
    @patch('results.race_views.Mopcompetition')
    @patch('results.race_views.CompetitionConfig')
    def test_erreur_mop_affichee(self, MockConfig, MockComp, mock_import):
        MockConfig.objects.filter.return_value.first.return_value = _config()
        MockComp.objects.filter.return_value.first.return_value = _competition()

        from results.race_views import RaceImportIofView
        response = RaceImportIofView.as_view()(
            _post({'action': 'import', 'confirm': 'on'}), token=TOKEN,
        )

        assert response.status_code == 200
        assert 'import a échoué' in response.content.decode()


# ─── Formulaire ──────────────────────────────────────────────────────────────

class TestForm:

    def test_fichier_trop_volumineux(self):
        from results.forms import IofImportForm
        with patch('results.iof_importer.MAX_UPLOAD_BYTES', 10):
            form = IofImportForm(
                files={'ioffile': _upload(b'x' * 11)},
                data={},
            )
            assert not form.is_valid()
        assert 'trop volumineux' in form.errors['ioffile'][0]

    def test_numero_de_course_positif(self):
        from results.forms import IofImportForm
        form = IofImportForm(
            files={'ioffile': _upload()},
            data={'race_number': '0'},
        )
        assert not form.is_valid()
        assert 'race_number' in form.errors

    def test_formulaire_valide(self):
        from results.forms import IofImportForm
        form = IofImportForm(
            files={'ioffile': _upload()},
            data={'race_number': '2', 'use_event_metadata': 'on'},
        )
        assert form.is_valid(), form.errors
        assert form.cleaned_data['race_number'] == 2
        assert form.cleaned_data['use_event_metadata'] is True


# ─── Lien depuis la page de gestion ──────────────────────────────────────────

class TestLienGestion:

    @patch('results.race_views.Mopcompetition')
    @patch('results.race_views.CompetitionConfig')
    def test_lien_import_present(self, MockConfig, MockComp):
        MockConfig.objects.filter.return_value.first.return_value = _config()
        MockComp.objects.filter.return_value.first.return_value = _competition()

        from results.race_views import RaceManageView
        response = RaceManageView.as_view()(
            rf().get(f'/gestion-course/{TOKEN}/'), token=TOKEN,
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert URL in content
        assert 'Importer un fichier IOF' in content
