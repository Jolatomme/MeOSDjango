"""
Fixtures partagées de la suite de tests (aucune base de données requise).

Le helper get_negative_time_stats fait des requêtes DB réelles : il est
masqué par défaut dans tous les tests de vues (appels depuis results.views
et results.classViews). Les tests dédiés au diagnostic des temps négatifs
le démasquent (patch imbriqué ou appel direct du service).

competition_visible est masqué de la même manière (vrai par défaut) : les
tests de visibilité le démasquent avec un patch imbriqué.
"""

import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def _no_neg_time_stats_db():
    """Ne jamais toucher la base via get_negative_time_stats dans les tests."""
    with patch('results.views.get_negative_time_stats', return_value=None), \
         patch('results.classViews.get_negative_time_stats', return_value=None), \
         patch('results.views.competition_visible', return_value=True), \
         patch('results.classViews.competition_visible', return_value=True):
        yield