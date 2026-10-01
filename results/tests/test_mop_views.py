"""
Tests pour les vues MOP (réception des mises à jour MeOS).

Ces tests vérifient le endpoint POST /mop/update/ et ses cas d'erreur.
"""

from unittest.mock import patch, MagicMock
import pytest
from django.test import RequestFactory
from django.conf import settings

from results.mop_views import mop_update


@pytest.fixture
def factory():
    return RequestFactory()


@pytest.fixture
def mock_settings():
    with patch.object(settings, 'MOP_PASSWORD', 'testpassword'):
        yield


@pytest.fixture(autouse=True)
def _no_race_key_lookup():
    """Par défaut, aucune recherche de clé API (la DB n'est pas touchée).

    Les tests dédiés aux clés API re-patchent ``find_race_by_key`` (le patch
    imbriqué du test l'emporte sur ce patch autouse).
    """
    with patch('results.mop_views.find_race_by_key', return_value=None):
        yield


class TestMopUpdateInvalidCid:
    """Tests pour les CID invalides."""

    def test_cid_zero(self, factory, mock_settings):
        """CID = 0 retourne 400."""
        request = factory.post(
            '/mop/update/',
            data=b'<MeOS><Competition>0</Competition></MeOS>',
            content_type='application/xml',
            HTTP_COMPETITION='0',
            HTTP_PWD='testpassword',
        )
        response = mop_update(request)
        assert response.status_code == 400

    def test_cid_negatif(self, factory, mock_settings):
        """CID négatif retourne 400."""
        request = factory.post(
            '/mop/update/',
            data=b'<MeOS><Competition>-1</Competition></MeOS>',
            content_type='application/xml',
            HTTP_COMPETITION='-1',
            HTTP_PWD='testpassword',
        )
        response = mop_update(request)
        assert response.status_code == 400

    def test_cid_non_numerique(self, factory, mock_settings):
        """CID non numérique retourne 400."""
        request = factory.post(
            '/mop/update/',
            data=b'<MeOS><Competition>abc</Competition></MeOS>',
            content_type='application/xml',
            HTTP_COMPETITION='abc',
            HTTP_PWD='testpassword',
        )
        response = mop_update(request)
        assert response.status_code == 400

    def test_cid_vide(self, factory, mock_settings):
        """CID vide retourne 400."""
        request = factory.post(
            '/mop/update/',
            data=b'<MeOS><Competition></Competition></MeOS>',
            content_type='application/xml',
            HTTP_COMPETITION='',
            HTTP_PWD='testpassword',
        )
        response = mop_update(request)
        assert response.status_code == 400


class TestMopUpdateAuth:
    """Tests pour l'authentification."""

    def test_password_manquant(self, factory, mock_settings):
        """Mot de passe manquant retourne 403."""
        request = factory.post(
            '/mop/update/',
            data=b'<MeOS><Competition>1</Competition></MeOS>',
            content_type='application/xml',
            HTTP_COMPETITION='1',
            HTTP_PWD='',
        )
        response = mop_update(request)
        assert response.status_code == 403

    def test_password_incorrect(self, factory, mock_settings):
        """Mot de passe incorrect retourne 403."""
        request = factory.post(
            '/mop/update/',
            data=b'<MeOS><Competition>1</Competition></MeOS>',
            content_type='application/xml',
            HTTP_COMPETITION='1',
            HTTP_PWD='wrongpassword',
        )
        response = mop_update(request)
        assert response.status_code == 403

    def test_header_pwd_absent(self, factory, mock_settings):
        """Header PWD absent retourne 403."""
        request = factory.post(
            '/mop/update/',
            data=b'<MeOS><Competition>1</Competition></MeOS>',
            content_type='application/xml',
            HTTP_COMPETITION='1',
        )
        response = mop_update(request)
        assert response.status_code == 403

    def test_password_non_configure(self, factory):
        """MOP_PASSWORD absent des settings → 403 BADPWD."""
        with patch.object(settings, 'MOP_PASSWORD', ''):
            request = factory.post(
                '/mop/update/',
                data=b'<MeOS><Competition>1</Competition></MeOS>',
                content_type='application/xml',
                HTTP_COMPETITION='1',
                HTTP_PWD='nimporte',
            )
            response = mop_update(request)
            assert response.status_code == 403
            assert b'BADPWD' in response.content


class TestMopUpdateBody:
    """Tests pour le corps de la requête."""

    def test_body_vide(self, factory, mock_settings):
        """Corps vide retourne 400."""
        request = factory.post(
            '/mop/update/',
            data=b'',
            content_type='application/xml',
            HTTP_COMPETITION='1',
            HTTP_PWD='testpassword',
        )
        response = mop_update(request)
        assert response.status_code == 400

    def test_body_zip(self, factory, mock_settings):
        """Corps commençant par PK (ZIP) retourne 415."""
        request = factory.post(
            '/mop/update/',
            data=b'PK\x03\x04',  # ZIP header
            content_type='application/xml',
            HTTP_COMPETITION='1',
            HTTP_PWD='testpassword',
        )
        response = mop_update(request)
        assert response.status_code == 415

    def test_body_zip_autre(self, factory, mock_settings):
        """Autre signature ZIP retourne 415."""
        request = factory.post(
            '/mop/update/',
            data=b'PK\x05\x06\x00\x00\x00\x00',
            content_type='application/xml',
            HTTP_COMPETITION='1',
            HTTP_PWD='testpassword',
        )
        response = mop_update(request)
        assert response.status_code == 415


class TestMopUpdateSuccess:
    """Tests pour le succès."""

    @patch('results.mop_views.process_mop_xml')
    def test_process_ok(self, mock_process, factory, mock_settings):
        """process_mop_xml retourne OK."""
        mock_process.return_value = 'OK'
        request = factory.post(
            '/mop/update/',
            data=b'<MeOS><Competition>1</Competition></MeOS>',
            content_type='application/xml',
            HTTP_COMPETITION='1',
            HTTP_PWD='testpassword',
        )
        response = mop_update(request)
        assert response.status_code == 200
        mock_process.assert_called_once_with(1, b'<MeOS><Competition>1</Competition></MeOS>')

    @patch('results.mop_views.process_mop_xml')
    def test_process_autre_status(self, mock_process, factory, mock_settings):
        """Status non-OK retourne 422."""
        mock_process.return_value = 'ERROR'
        request = factory.post(
            '/mop/update/',
            data=b'<MeOS><Competition>1</Competition></MeOS>',
            content_type='application/xml',
            HTTP_COMPETITION='1',
            HTTP_PWD='testpassword',
        )
        response = mop_update(request)
        assert response.status_code == 422


# ─── Clé API par course ────────────────────────────────────────────────────────

def _race_config(cid=7):
    config = MagicMock()
    config.cid = cid
    config.api_key = 'k' * 43
    return config


class TestMopApiKeyAuth:
    """Authentification par clé API unique (course créée depuis le site).

    La clé identifie seule la compétition : le numéro de compétition peut
    rester vide dans MeOS (cf. page /creer-course/).
    """

    @patch('results.mop_views.process_mop_xml', return_value='OK')
    @patch('results.mop_views.find_race_by_key')
    def test_cle_seule_header_competition_vide(self, mock_find, mock_process, factory):
        """Compétition vide → cid dérivé de la clé."""
        mock_find.return_value = _race_config(7)
        request = factory.post(
            '/mop/update/',
            data=b'<MeOS/>',
            content_type='application/xml',
            HTTP_COMPETITION='',
            HTTP_PWD='k' * 43,
        )
        response = mop_update(request)
        assert response.status_code == 200
        mock_process.assert_called_once_with(7, b'<MeOS/>')

    @patch('results.mop_views.process_mop_xml', return_value='OK')
    @patch('results.mop_views.find_race_by_key')
    def test_cle_seule_header_competition_absent(self, mock_find, mock_process, factory):
        """Header Competition absent → cid dérivé de la clé."""
        mock_find.return_value = _race_config(12)
        request = factory.post(
            '/mop/update/',
            data=b'<MeOS/>',
            content_type='application/xml',
            HTTP_PWD='k' * 43,
        )
        response = mop_update(request)
        assert response.status_code == 200
        mock_process.assert_called_once_with(12, b'<MeOS/>')

    @patch('results.mop_views.process_mop_xml', return_value='OK')
    @patch('results.mop_views.find_race_by_key')
    def test_cle_seule_cid_zero(self, mock_find, mock_process, factory):
        """Compétition = 0 → traitée comme vide, cid dérivé de la clé."""
        mock_find.return_value = _race_config(7)
        request = factory.post(
            '/mop/update/',
            data=b'<MeOS/>',
            content_type='application/xml',
            HTTP_COMPETITION='0',
            HTTP_PWD='k' * 43,
        )
        response = mop_update(request)
        assert response.status_code == 200
        mock_process.assert_called_once_with(7, b'<MeOS/>')

    @patch('results.mop_views.process_mop_xml', return_value='OK')
    @patch('results.mop_views.find_race_by_key')
    def test_cle_avec_cid_correspondant(self, mock_find, mock_process, factory):
        """Compétition explicite identique à celle de la clé → accepté."""
        mock_find.return_value = _race_config(7)
        request = factory.post(
            '/mop/update/',
            data=b'<MeOS/>',
            content_type='application/xml',
            HTTP_COMPETITION='7',
            HTTP_PWD='k' * 43,
        )
        response = mop_update(request)
        assert response.status_code == 200
        mock_process.assert_called_once_with(7, b'<MeOS/>')

    @patch('results.mop_views.find_race_by_key')
    def test_cle_avec_cid_divergent(self, mock_find, factory):
        """Compétition explicite différente de celle de la clé → BADCMP."""
        mock_find.return_value = _race_config(7)
        request = factory.post(
            '/mop/update/',
            data=b'<MeOS/>',
            content_type='application/xml',
            HTTP_COMPETITION='8',
            HTTP_PWD='k' * 43,
        )
        response = mop_update(request)
        assert response.status_code == 400
        assert b'BADCMP' in response.content

    @patch('results.mop_views.process_mop_xml', return_value='OK')
    @patch('results.mop_views.find_race_by_key')
    @patch.object(settings, 'MOP_PASSWORD', '')
    def test_cle_fonctionne_sans_mot_de_passe_global(
        self, mock_find, mock_process, factory,
    ):
        """La clé API fonctionne même si MOP_PASSWORD n'est pas configuré."""
        mock_find.return_value = _race_config(3)
        request = factory.post(
            '/mop/update/',
            data=b'<MeOS/>',
            content_type='application/xml',
            HTTP_COMPETITION='',
            HTTP_PWD='k' * 43,
        )
        response = mop_update(request)
        assert response.status_code == 200
        mock_process.assert_called_once_with(3, b'<MeOS/>')


class TestMopFallbackGlobalPassword:
    """Repli sur le mot de passe global MOP_PASSWORD."""

    @patch('results.mop_views.process_mop_xml', return_value='OK')
    def test_cle_inconnue_mot_de_passe_global_valide(self, mock_process, factory, mock_settings):
        """Clé inconnue + mot de passe global valide → accepté (comportement historique)."""
        request = factory.post(
            '/mop/update/',
            data=b'<MeOS/>',
            content_type='application/xml',
            HTTP_COMPETITION='1',
            HTTP_PWD='testpassword',
        )
        response = mop_update(request)
        assert response.status_code == 200
        mock_process.assert_called_once_with(1, b'<MeOS/>')

    def test_cle_inconnue_mot_de_passe_global_invalide(self, factory, mock_settings):
        """Clé inconnue + mauvais mot de passe → 403 BADPWD."""
        request = factory.post(
            '/mop/update/',
            data=b'<MeOS/>',
            content_type='application/xml',
            HTTP_COMPETITION='1',
            HTTP_PWD='mauvaise-cle',
        )
        response = mop_update(request)
        assert response.status_code == 403
        assert b'BADPWD' in response.content

    def test_cle_inconnue_cid_invalide(self, factory, mock_settings):
        """Clé inconnue + CID invalide → 400 BADCMP (avant toute comparaison)."""
        request = factory.post(
            '/mop/update/',
            data=b'<MeOS/>',
            content_type='application/xml',
            HTTP_COMPETITION='',
            HTTP_PWD='testpassword',
        )
        response = mop_update(request)
        assert response.status_code == 400
        assert b'BADCMP' in response.content

    def test_secret_non_journalise_en_clair(self, factory, mock_settings, caplog):
        """L'identifiant refusé n'apparaît jamais en clair dans les logs."""
        import logging as _logging
        with caplog.at_level(_logging.WARNING, logger='results.mop_views'):
            request = factory.post(
                '/mop/update/',
                data=b'<MeOS/>',
                content_type='application/xml',
                HTTP_COMPETITION='1',
                HTTP_PWD='super-secret-password',
            )
            response = mop_update(request)
        assert response.status_code == 403
        assert 'super-secret-password' not in caplog.text
        assert 'super-secret-password' not in str(caplog.records)