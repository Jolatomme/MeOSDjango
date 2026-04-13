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