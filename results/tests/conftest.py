"""
Fixtures partagées de la suite de tests (aucune base de données requise).

Le helper get_negative_time_stats fait des requêtes DB réelles : il est
masqué par défaut dans tous les tests de vues (appels depuis results.views
et results.classViews). Les tests dédiés au diagnostic des temps négatifs
le démasquent (patch imbriqué ou appel direct du service).

competition_visible est masqué de la même manière (vrai par défaut) : les
tests de visibilité le démasquent avec un patch imbriqué.

Enfin, les réglages portés par le ``.env`` de production sont neutralisés :
les tests doivent donner exactement le même résultat en local et sur le
serveur (``DEBUG=0`` + ``PUBLIC_SITE_URL``).
"""

import pytest
from django.test import override_settings
from unittest.mock import patch


@pytest.fixture(autouse=True)
def _environnement_independant_de_la_machine():
    """Ignore le ``.env`` de prod : mêmes résultats partout.

    Sur le serveur (``DEBUG=0``), le bloc HTTPS de ``settings.py`` active
    ``SECURE_SSL_REDIRECT`` : SecurityMiddleware répond **301** vers
    ``https://testserver/…`` à chaque requête ``http://`` du client de test —
    corps vide, cookie jamais posé (``co_lang``), ``Location`` absolue au lieu
    de ``/`` : échec en cascade des tests de vue (set_language, négociation de
    langue, ``/org_logo/…``). ``PUBLIC_SITE_URL`` écrase de son côté les URL
    déduites de la requête : « URL d'envoi » MeOS et lien de gestion affichent
    l'URL de prod au lieu de ``http://testserver/…``.

    ``Client`` construit ses middlewares à la **première requête de chaque
    test** (``ClientHandler.__call__``) : ``SecurityMiddleware`` relisait donc
    la valeur au bon moment, l'override est effectif — aucune valeur n'est
    figée en mémoire d'une fixture à l'autre.
    """
    with override_settings(SECURE_SSL_REDIRECT=False, PUBLIC_SITE_URL=''):
        yield


@pytest.fixture(autouse=True)
def _no_neg_time_stats_db():
    """Ne jamais toucher la base via get_negative_time_stats dans les tests."""
    with patch('results.views.get_negative_time_stats', return_value=None), \
         patch('results.classViews.get_negative_time_stats', return_value=None), \
         patch('results.views.competition_visible', return_value=True), \
         patch('results.classViews.competition_visible', return_value=True):
        yield