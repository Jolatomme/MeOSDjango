"""
Tests des vues publiques de création / gestion de courses (DB mockée).

Couvre :
  - RaceCreateView : rendu, création, anti-spam (honeypot + jeton horodaté)
  - RaceManageView : rendu du lien privé, régénération de clé, édition
  - jetons horodatés (new_creation_token / _token_too_fast)
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest
from django.db import IntegrityError
from django.http import Http404
from django.test import RequestFactory


def rf():
    return RequestFactory()


def _valid_post(age=10.0, **extra):
    """Données POST valides, avec un jeton d'âge ``age`` secondes."""
    from results.race_views import new_creation_token
    data = {
        'name': 'Trail de Test',
        'date': '2026-05-17',
        'organizer': 'COCS 73',
        'homepage': 'https://example.org',
        'token': new_creation_token(age=age),
        'website': '',
    }
    data.update(extra)
    return data


def _config(cid=9, token='jeton-prive-abc', api_key='k' * 43):
    # SimpleNamespace (et non MagicMock) : les templates Django tentent un
    # accès dictionnaire d'abord, que MagicMock satisferait à tort.
    return SimpleNamespace(cid=cid, manage_token=token, api_key=api_key)


def _competition():
    return SimpleNamespace(
        name='Trail de Test',
        date=date(2026, 5, 17),
        organizer='COCS 73',
        homepage='https://example.org',
    )


# ─── RaceCreateView ────────────────────────────────────────────────────────────

class TestRaceCreateView:

    def test_get_rend_formulaire(self):
        from results.race_views import RaceCreateView
        response = RaceCreateView.as_view()(rf().get('/creer-course/'))
        assert response.status_code == 200
        content = response.content.decode()
        assert 'Créer une course' in content
        assert 'name="token"' in content          # jeton horodaté
        assert 'name="website"' in content        # honeypot
        assert 'name="name"' in content
        assert 'name="date"' in content
        assert 'name="organizer"' in content
        assert "Site web de l'organisateur" in content

    @patch('results.race_views.create_race')
    def test_post_valide_redirige_vers_gestion(self, mock_create):
        mock_create.return_value = _config(token='tok-secret')
        from results.race_views import RaceCreateView
        response = RaceCreateView.as_view()(rf().post('/creer-course/', _valid_post()))
        assert response.status_code == 302
        assert response['Location'].endswith('/gestion-course/tok-secret/')
        mock_create.assert_called_once_with(
            name='Trail de Test',
            date=date(2026, 5, 17),
            organizer='COCS 73',
            homepage='https://example.org',
        )

    @patch('results.race_views.create_race')
    def test_post_honeypot_rempli_rejette(self, mock_create):
        from results.race_views import RaceCreateView
        data = _valid_post(website='https://spam.example')
        response = RaceCreateView.as_view()(rf().post('/creer-course/', data))
        assert response.status_code == 200
        assert b'Formulaire invalide' in response.content
        mock_create.assert_not_called()

    @patch('results.race_views.create_race')
    def test_post_sans_jeton_rejette(self, mock_create):
        from results.race_views import RaceCreateView
        data = _valid_post()
        data['token'] = ''
        response = RaceCreateView.as_view()(rf().post('/creer-course/', data))
        assert response.status_code == 200
        mock_create.assert_not_called()

    @patch('results.race_views.create_race')
    def test_post_jeton_trop_recent_rejette(self, mock_create):
        """Un remplissage en moins de 2 secondes est rejeté (anti-spam)."""
        from results.race_views import RaceCreateView
        data = _valid_post(age=0.5)
        response = RaceCreateView.as_view()(rf().post('/creer-course/', data))
        assert response.status_code == 200
        assert b'Formulaire invalide' in response.content
        mock_create.assert_not_called()

    @patch('results.race_views.create_race')
    def test_post_jeton_falsifie_rejette(self, mock_create):
        from results.race_views import RaceCreateView
        data = _valid_post()
        data['token'] = 'jeton-contrefait'
        response = RaceCreateView.as_view()(rf().post('/creer-course/', data))
        assert response.status_code == 200
        mock_create.assert_not_called()

    @patch('results.race_views.create_race')
    def test_post_champs_invalides_rend_erreurs(self, mock_create):
        from results.race_views import RaceCreateView
        data = _valid_post(name='', date='pas-une-date')
        response = RaceCreateView.as_view()(rf().post('/creer-course/', data))
        assert response.status_code == 200
        assert b'Ce champ est obligatoire' in response.content
        mock_create.assert_not_called()

    @patch('results.race_views.create_race')
    def test_post_conflit_cid_rend_erreur(self, mock_create):
        mock_create.side_effect = IntegrityError('duplicate')
        from results.race_views import RaceCreateView
        response = RaceCreateView.as_view()(rf().post('/creer-course/', _valid_post()))
        assert response.status_code == 200
        assert b'Conflit' in response.content


# ─── RaceManageView ────────────────────────────────────────────────────────────

class TestRaceManageView:

    @patch('results.race_views.Mopcompetition')
    @patch('results.race_views.CompetitionConfig')
    def test_get_affiche_parametres_meos(self, MockConfig, MockComp):
        config = _config()
        MockConfig.objects.filter.return_value.first.return_value = config
        MockComp.objects.filter.return_value.first.return_value = _competition()

        from results.race_views import RaceManageView
        request = rf().get('/gestion-course/jeton-prive-abc/')
        response = RaceManageView.as_view()(request, token='jeton-prive-abc')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'k' * 43 in content                 # clé API affichée
        assert 'http://testserver/mop/update/' in content
        assert 'laisser vide' in content           # CID à laisser vide
        assert 'MeOS Online Protocol XML 2.0' in content
        assert 'http://testserver/gestion-course/jeton-prive-abc/' in content
        # Bouton de révocation/regénération du lien privé
        assert 'name="action" value="regenerate_link"' in content
        assert "Site web de l'organisateur" in content
        MockConfig.objects.filter.assert_called_once_with(
            manage_token='jeton-prive-abc'
        )

    @patch('results.race_views.CompetitionConfig')
    def test_get_jeton_invalide_404(self, MockConfig):
        MockConfig.objects.filter.return_value.first.return_value = None
        from results.race_views import RaceManageView
        request = rf().get('/gestion-course/inconnu/')
        with pytest.raises(Http404):
            RaceManageView.as_view()(request, token='inconnu')

    def test_get_sans_jeton_404(self):
        from results.race_views import RaceManageView
        request = rf().get('/gestion-course/')
        with pytest.raises(Http404):
            RaceManageView.as_view()(request, token='')

    @patch('results.race_views.regenerate_api_key')
    @patch('results.race_views.Mopcompetition')
    @patch('results.race_views.CompetitionConfig')
    def test_post_regenere_cle(self, MockConfig, MockComp, mock_regen):
        config = _config()
        MockConfig.objects.filter.return_value.first.return_value = config

        from results.race_views import RaceManageView
        request = rf().post(
            '/gestion-course/jeton-prive-abc/',
            {'action': 'regenerate_key'},
        )
        response = RaceManageView.as_view()(request, token='jeton-prive-abc')

        assert response.status_code == 302
        assert response['Location'].endswith('?ok=key')
        mock_regen.assert_called_once_with(config)

    @patch('results.race_views.regenerate_manage_token', return_value='nouveau-jeton')
    @patch('results.race_views.CompetitionConfig')
    def test_post_regenere_lien(self, MockConfig, mock_regen):
        """Regénérer le lien → l'ancien meurt, redirection vers le nouveau."""
        config = _config()
        MockConfig.objects.filter.return_value.first.return_value = config

        from results.race_views import RaceManageView
        request = rf().post(
            '/gestion-course/jeton-prive-abc/',
            {'action': 'regenerate_link'},
        )
        response = RaceManageView.as_view()(request, token='jeton-prive-abc')

        assert response.status_code == 302
        assert response['Location'] == '/gestion-course/nouveau-jeton/?ok=link'
        mock_regen.assert_called_once_with(config)

    @patch('results.race_views.Mopcompetition')
    @patch('results.race_views.CompetitionConfig')
    def test_post_modifie_infos(self, MockConfig, MockComp):
        config = _config()
        MockConfig.objects.filter.return_value.first.return_value = config

        from results.race_views import RaceManageView
        data = {
            'action': 'edit',
            'name': 'Nouveau nom',
            'date': '2026-06-01',
            'organizer': 'OK Autre',
            'homepage': 'https://autre.example',
        }
        request = rf().post('/gestion-course/jeton-prive-abc/', data)
        response = RaceManageView.as_view()(request, token='jeton-prive-abc')

        assert response.status_code == 302
        assert response['Location'].endswith('?ok=info')
        MockComp.objects.filter.assert_called_once_with(cid=9, id=1)
        MockComp.objects.filter.return_value.update.assert_called_once_with(
            name='Nouveau nom',
            date=date(2026, 6, 1),
            organizer='OK Autre',
            homepage='https://autre.example',
        )

    @patch('results.race_views.Mopcompetition')
    @patch('results.race_views.CompetitionConfig')
    def test_post_modifie_champs_invalides_rend_erreurs(self, MockConfig, MockComp):
        config = _config()
        MockConfig.objects.filter.return_value.first.return_value = config
        MockComp.objects.filter.return_value.first.return_value = _competition()

        from results.race_views import RaceManageView
        request = rf().post(
            '/gestion-course/jeton-prive-abc/',
            {'action': 'edit', 'name': '', 'date': '', 'organizer': ''},
        )
        response = RaceManageView.as_view()(request, token='jeton-prive-abc')

        assert response.status_code == 200
        assert b'Ce champ est obligatoire' in response.content
        MockComp.objects.filter.return_value.update.assert_not_called()

    @patch('results.race_views.CompetitionConfig')
    def test_post_action_inconnue_redirige(self, MockConfig):
        MockConfig.objects.filter.return_value.first.return_value = _config()
        from results.race_views import RaceManageView
        request = rf().post('/gestion-course/jeton-prive-abc/', {'action': 'zzz'})
        response = RaceManageView.as_view()(request, token='jeton-prive-abc')
        assert response.status_code == 302
        assert response['Location'] == '/gestion-course/jeton-prive-abc/'


# ─── PUBLIC_SITE_URL (URL de production canonique) ─────────────────────────────

class TestPublicSiteUrl:
    """PUBLIC_SITE_URL force l'URL affichée (MeOS + lien de gestion)."""

    @patch('results.race_views.Mopcompetition')
    @patch('results.race_views.CompetitionConfig')
    def test_urls_utilisent_public_site_url(self, MockConfig, MockComp):
        from django.test import override_settings
        config = _config(token='jeton-prive-abc')
        MockConfig.objects.filter.return_value.first.return_value = config
        MockComp.objects.filter.return_value.first.return_value = _competition()

        from results.race_views import RaceManageView
        request = rf().get('/gestion-course/jeton-prive-abc/')
        with override_settings(PUBLIC_SITE_URL='https://jolatomme.alwaysdata.net/'):
            response = RaceManageView.as_view()(request, token='jeton-prive-abc')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'https://jolatomme.alwaysdata.net/mop/update/' in content
        assert 'https://jolatomme.alwaysdata.net/gestion-course/jeton-prive-abc/' in content
        assert 'http://testserver/' not in content

    @patch('results.race_views.Mopcompetition')
    @patch('results.race_views.CompetitionConfig')
    def test_sans_public_site_url_url_de_la_requetete(self, MockConfig, MockComp):
        """Non défini → comportement historique (host de la requête)."""
        config = _config(token='jeton-prive-abc')
        MockConfig.objects.filter.return_value.first.return_value = config
        MockComp.objects.filter.return_value.first.return_value = _competition()

        from results.race_views import RaceManageView
        request = rf().get('/gestion-course/jeton-prive-abc/')
        response = RaceManageView.as_view()(request, token='jeton-prive-abc')

        content = response.content.decode()
        assert 'http://testserver/mop/update/' in content
        assert 'http://testserver/gestion-course/jeton-prive-abc/' in content


# ─── Jetons horodatés ──────────────────────────────────────────────────────────

class TestCreationTokens:

    def test_jeton_frais_trop_rapide(self):
        from results.race_views import new_creation_token, _token_too_fast
        assert _token_too_fast(new_creation_token()) is True

    def test_jeton_ancien_accepte(self):
        from results.race_views import new_creation_token, _token_too_fast
        assert _token_too_fast(new_creation_token(age=10)) is False

    def test_jeton_vide_rejette(self):
        from results.race_views import _token_too_fast
        assert _token_too_fast('') is True
        assert _token_too_fast(None) is True

    def test_jeton_contrefait_rejette(self):
        from results.race_views import _token_too_fast
        assert _token_too_fast('signatures-absentes') is True
