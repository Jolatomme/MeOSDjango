"""
Tests des vues publiques de création / gestion de courses (DB mockée).

Couvre :
  - RaceCreateView : rendu, création, anti-spam (honeypot + jeton horodaté)
  - RaceManageView : rendu du lien privé, régénération de clé, édition
  - jetons horodatés (new_creation_token / _token_too_fast)
  - ENABLE_RACE_CREATION : création activée (défaut) ou désactivée (404)
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.http import Http404
from django.test import RequestFactory, override_settings

PNG_MAGIC = b'\x89PNG\r\n\x1a\n'


def _png_file(name='logo-club.png', content=None):
    """SimpleUploadedFile PNG valide (signature + données factices)."""
    return SimpleUploadedFile(
        name, PNG_MAGIC + (content or b'\x00' * 64), content_type='image/png',
    )


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
        'livelox': 'https://livelox.example/42',
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
        livelox='https://livelox.example/42',
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
        assert 'name="livelox"' in content
        assert 'Livelox' in content
        assert 'name="logo"' in content
        assert 'Logo de l\'organisateur' in content
        assert 'enctype="multipart/form-data"' in content

    @patch('results.race_views.save_org_logo')
    @patch('results.race_views.create_race')
    def test_post_valide_redirige_vers_gestion(self, mock_create, mock_save):
        mock_create.return_value = _config(token='tok-secret')
        from results.race_views import RaceCreateView
        response = RaceCreateView.as_view()(rf().post('/creer-course/', _valid_post()))
        assert response.status_code == 302
        assert response['Location'].endswith('/gestion-course/tok-secret/')
        mock_save.assert_not_called()               # aucun fichier → aucun écrit disque
        mock_create.assert_called_once_with(
            name='Trail de Test',
            date=date(2026, 5, 17),
            organizer='COCS 73',
            homepage='https://example.org',
            livelox='https://livelox.example/42',
            logo='',
        )

    @patch('results.race_views.save_org_logo', return_value='logo-deadbeef0001.png')
    @patch('results.race_views.create_race')
    def test_post_avec_logo_le_transmet_a_create_race(self, mock_create, mock_save):
        mock_create.return_value = _config(token='tok-secret')
        from results.race_views import RaceCreateView
        data = _valid_post()
        response = RaceCreateView.as_view()(
            rf().post('/creer-course/', {**data, 'logo': _png_file()}),
        )
        assert response.status_code == 302
        mock_save.assert_called_once()
        assert mock_save.call_args.args[0].name == 'logo-club.png'
        assert mock_create.call_args.kwargs['logo'] == 'logo-deadbeef0001.png'

    @patch('results.race_views.save_org_logo')
    @patch('results.race_views.create_race')
    def test_post_logo_format_invalide_rejette(self, mock_create, mock_save):
        from results.race_views import RaceCreateView
        data = _valid_post()
        bad = SimpleUploadedFile('evil.exe', b'MZ\x90\x00', content_type='application/x-msdownload')
        response = RaceCreateView.as_view()(
            rf().post('/creer-course/', {**data, 'logo': bad}),
        )
        assert response.status_code == 200
        assert 'Format accepté : SVG, PNG ou JPEG.' in response.content.decode()
        mock_create.assert_not_called()
        mock_save.assert_not_called()

    @patch('results.race_views.save_org_logo')
    @patch('results.race_views.create_race')
    def test_post_logo_contenu_invalide_rejette(self, mock_create, mock_save):
        """Extension .png mais contenu sans signature PNG."""
        from results.race_views import RaceCreateView
        data = _valid_post()
        fake = SimpleUploadedFile('fake.png', b'ce n est pas un png', content_type='image/png')
        response = RaceCreateView.as_view()(
            rf().post('/creer-course/', {**data, 'logo': fake}),
        )
        assert response.status_code == 200
        assert 'Fichier illisible' in response.content.decode()
        mock_create.assert_not_called()
        mock_save.assert_not_called()

    @patch('results.race_views.save_org_logo')
    @patch('results.race_views.create_race')
    def test_post_logo_trop_gros_rejette(self, mock_create, mock_save):
        from results.race_views import RaceCreateView
        data = _valid_post()
        huge = SimpleUploadedFile(
            'huge.png', PNG_MAGIC + b'\x00' * (2 * 1024 * 1024),
            content_type='image/png',
        )
        response = RaceCreateView.as_view()(
            rf().post('/creer-course/', {**data, 'logo': huge}),
        )
        assert response.status_code == 200
        assert '2 Mo maximum' in response.content.decode()
        mock_create.assert_not_called()
        mock_save.assert_not_called()

    @patch('results.race_views.delete_org_logo')
    @patch('results.race_views.save_org_logo', return_value='logo-deadbeef0001.png')
    @patch('results.race_views.create_race')
    def test_post_conflit_cid_supprime_le_logo_ecrit(self, mock_create, mock_save, mock_del):
        mock_create.side_effect = IntegrityError('duplicate')
        from results.race_views import RaceCreateView
        data = _valid_post()
        response = RaceCreateView.as_view()(
            rf().post('/creer-course/', {**data, 'logo': _png_file()}),
        )
        assert response.status_code == 200
        assert b'Conflit' in response.content
        mock_del.assert_called_once_with('logo-deadbeef0001.png')

    @patch('results.race_views.create_race')
    def test_post_sans_livelox_passe_chaine_vide(self, mock_create):
        """Champ livelox absent du POST → chaîne vide transmise à create_race."""
        mock_create.return_value = _config(token='tok-secret')
        from results.race_views import RaceCreateView
        data = _valid_post()
        del data['livelox']
        response = RaceCreateView.as_view()(rf().post('/creer-course/', data))
        assert response.status_code == 302
        assert mock_create.call_args.kwargs['livelox'] == ''

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
    def test_post_invalide_conserve_date_saisie(self, mock_create):
        """Formulaire lié : la date saisie reste dans le champ (iso_date)."""
        from results.race_views import RaceCreateView
        data = _valid_post(organizer='')
        response = RaceCreateView.as_view()(rf().post('/creer-course/', data))
        assert response.status_code == 200
        assert 'value="2026-05-17"' in response.content.decode()
        mock_create.assert_not_called()

    @patch('results.race_views.create_race')
    def test_post_conflit_cid_rend_erreur(self, mock_create):
        mock_create.side_effect = IntegrityError('duplicate')
        from results.race_views import RaceCreateView
        response = RaceCreateView.as_view()(rf().post('/creer-course/', _valid_post()))
        assert response.status_code == 200
        assert b'Conflit' in response.content


# ─── ENABLE_RACE_CREATION (activation / désactivation de la création) ──────────

class TestEnableRaceCreationFlag:
    """ENABLE_RACE_CREATION=False : /creer-course/ renvoie 404, sinon 200."""

    @override_settings(ENABLE_RACE_CREATION=False)
    def test_get_desactive_rend_404(self):
        from results.race_views import RaceCreateView
        with pytest.raises(Http404):
            RaceCreateView.as_view()(rf().get('/creer-course/'))

    @patch('results.race_views.create_race')
    @override_settings(ENABLE_RACE_CREATION=False)
    def test_post_desactive_rend_404_sans_creation(self, mock_create):
        from results.race_views import RaceCreateView
        with pytest.raises(Http404):
            RaceCreateView.as_view()(rf().post('/creer-course/', _valid_post()))
        mock_create.assert_not_called()

    @override_settings(ENABLE_RACE_CREATION=True)
    def test_get_active_rend_200(self):
        from results.race_views import RaceCreateView
        response = RaceCreateView.as_view()(rf().get('/creer-course/'))
        assert response.status_code == 200


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
        assert 'name="livelox"' in content
        assert 'https://livelox.example/42' in content   # valeur enregistrée
        # Date ISO dans <input type="date"> (et non localisée : « 17 mai 2026 »,
        # que le navigateur rejetterait → champ affiché vide)
        assert 'value="2026-05-17"' in content
        assert '17 mai 2026' not in content
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
            'livelox': 'https://livelox.example/99',
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
            livelox='https://livelox.example/99',
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


# ─── validate_org_logo ────────────────────────────────────────────────────────

class TestValidateOrgLogo:
    """Extension, taille et signature du contenu (anti « exécutable déguisé »)."""

    @staticmethod
    def _validate(uploaded):
        from results.forms import validate_org_logo
        validate_org_logo(uploaded)        # ne lève pas si valide

    @pytest.mark.parametrize('name', ['a.svg', 'a.png', 'a.jpg', 'a.jpeg',
                                      'A.JPG', 'logo.PNG'])
    def test_extensions_acceptees(self, name):
        from results.forms import validate_org_logo
        from django.core.exceptions import ValidationError
        content = (
            b'\xff\xd8\xff\xe0rest' if name.lower().endswith(('.jpg', '.jpeg'))
            else PNG_MAGIC + b'\x00' * 8 if name.lower().endswith('.png')
            else b'<svg xmlns="http://www.w3.org/2000/svg"/>'
        )
        try:
            validate_org_logo(SimpleUploadedFile(name, content))
        except ValidationError:
            pytest.fail(f'extension {name} rejetée à tort')

    def test_svg_avec_bom_et_espaces_accepte(self):
        bom = b'\xef\xbb\xbf'          # UTF-8 BOM
        self._validate(SimpleUploadedFile(
            'a.svg', bom + b' \n\r<svg xmlns="x"/>',
        ))

    def test_jpeg_valide(self):
        self._validate(SimpleUploadedFile('a.jpg', b'\xff\xd8\xff\xe0data'))

    @pytest.mark.parametrize('name,content', [
        ('a.svg', b'ce n est pas du svg'),
        ('a.png', b'\xff\xd8\xff\xe0'),      # JPEG déguisé en PNG
        ('a.jpg', b'<svg/>'),                # SVG déguisé en JPEG
    ])
    def test_contenu_invalide(self, name, content):
        from results.forms import validate_org_logo
        from django.core.exceptions import ValidationError
        with pytest.raises(ValidationError) as exc:
            validate_org_logo(SimpleUploadedFile(name, content))
        assert 'Fichier illisible' in str(exc.value)

    def test_extension_refusee(self):
        from results.forms import validate_org_logo
        from django.core.exceptions import ValidationError
        with pytest.raises(ValidationError):
            validate_org_logo(SimpleUploadedFile('a.gif', b'GIF89a'))

    def test_taille_max(self):
        from results.forms import validate_org_logo, LOGO_MAX_BYTES
        from django.core.exceptions import ValidationError
        huge = SimpleUploadedFile(
            'a.png', PNG_MAGIC + b'\x00' * LOGO_MAX_BYTES,
        )
        with pytest.raises(ValidationError) as exc:
            validate_org_logo(huge)
        assert '2 Mo' in str(exc.value)


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
