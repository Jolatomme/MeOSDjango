"""
Tests du health check — /health/.

La vue fait un ``SELECT 1`` : la connexion est mockée (la suite tourne sans
base de données). Deux cas : base joignable → 200, base en panne → 503.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from django.db.utils import OperationalError
from django.test import Client
from django.urls import reverse


def _mock_connection():
    """Connexion mockée : cursor() fonctionne (context manager inclus)."""
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (1,)
    return conn


def test_health_check_url_resolves():
    assert reverse('results:health_check') == '/health/'


@pytest.mark.parametrize('url', ['/health/', '/health'])
def test_health_check_accepts_both_spellings(url):
    """La sonde répond en direct sur /health/ **et** /health (pas de 301)."""
    with patch('results.views.connection', _mock_connection()):
        resp = Client().get(url)

    assert resp.status_code == 200
    assert json.loads(resp.content) == {'status': 'ok', 'db': 'ok'}


def test_health_check_returns_ok_json_when_db_up():
    with patch('results.views.connection', _mock_connection()):
        resp = Client().get('/health/')

    assert resp.status_code == 200
    assert resp['Content-Type'] == 'application/json'
    assert json.loads(resp.content) == {'status': 'ok', 'db': 'ok'}


def test_health_check_returns_503_when_db_down():
    conn = MagicMock()
    conn.cursor.side_effect = OperationalError('lost connection')

    with patch('results.views.connection', conn):
        resp = Client().get('/health/')

    assert resp.status_code == 503
    assert json.loads(resp.content) == {'status': 'error', 'db': 'error'}
