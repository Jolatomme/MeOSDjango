"""
Tests unitaires pour context_processors.py.

Couvre :
  - site_settings : injection des variables de configuration dans chaque requête
"""

import pytest
from unittest.mock import MagicMock, patch
from django.test import RequestFactory


def rf_get(url='/'):
    return RequestFactory().get(url)


# ─── Tests site_settings ─────────────────────────────────────────────────────

class TestSiteSettings:
    """Vérifie que site_settings retourne les bonnes clés depuis settings."""

    def _call(self, request=None, **overrides):
        """Appelle site_settings avec les settings patchés."""
        defaults = {
            'SITE_NAME':          'Résultats CO',
            'SITE_SUBTITLE':      "Course d'Orientation",
            'CLUB_NAME':          'COCS',
            'CLUB_COLOR_PRIMARY': '#1a6b3c',
            'CLUB_COLOR_ACCENT':  '#f0a500',
        }
        defaults.update(overrides)
        with patch('results.context_processors.settings') as mock_settings:
            for key, val in defaults.items():
                setattr(mock_settings, key, val)
            # getattr(settings, 'X', default) doit retourner la valeur
            mock_settings.configure_mock(**{key: val for key, val in defaults.items()})

            from results.context_processors import site_settings
            return site_settings(request or rf_get())

    def test_retourne_dict(self):
        """site_settings doit retourner un dictionnaire."""
        result = self._call()
        assert isinstance(result, dict)

    def test_contient_site_name(self):
        result = self._call()
        assert 'SITE_NAME' in result

    def test_contient_site_subtitle(self):
        result = self._call()
        assert 'SITE_SUBTITLE' in result

    def test_contient_club_name(self):
        result = self._call()
        assert 'CLUB_NAME' in result

    def test_contient_club_color_primary(self):
        result = self._call()
        assert 'CLUB_COLOR_PRIMARY' in result

    def test_contient_club_color_accent(self):
        result = self._call()
        assert 'CLUB_COLOR_ACCENT' in result

    def test_valeurs_par_defaut_si_settings_absent(self):
        """Si les settings ne définissent pas les clés, les défauts sont utilisés."""
        from django.conf import settings as real_settings
        from results.context_processors import site_settings

        # On supprime temporairement les attributs pour simuler leur absence
        attrs_to_remove = [
            'SITE_NAME', 'SITE_SUBTITLE', 'CLUB_NAME',
            'CLUB_COLOR_PRIMARY', 'CLUB_COLOR_ACCENT',
        ]
        saved = {}
        for attr in attrs_to_remove:
            if hasattr(real_settings, attr):
                saved[attr] = getattr(real_settings, attr)
                try:
                    delattr(real_settings, attr)
                except AttributeError:
                    pass  # Certains settings sont protégés

        try:
            result = site_settings(rf_get())
            # Les valeurs par défaut codées en dur dans le processor
            assert result['SITE_NAME']          == 'Résultats CO'
            assert result['SITE_SUBTITLE']      == "Course d'Orientation"
            assert result['CLUB_NAME']          == 'COCS'
            assert result['CLUB_COLOR_PRIMARY'] == '#1a6b3c'
            assert result['CLUB_COLOR_ACCENT']  == '#f0a500'
        finally:
            # Restaurer les settings
            for attr, val in saved.items():
                setattr(real_settings, attr, val)

    def test_cinq_cles_retournees(self):
        """Le dictionnaire doit contenir exactement 5 clés."""
        result = self._call()
        assert len(result) == 5

    def test_valeurs_sont_des_chaines(self):
        """Toutes les valeurs doivent être des chaînes de caractères."""
        result = self._call()
        for key, val in result.items():
            assert isinstance(val, str), f"La valeur de {key} doit être str, obtenu {type(val)}"

    def test_independant_de_la_requete(self):
        """Le résultat ne doit pas dépendre du contenu de la requête."""
        req1 = RequestFactory().get('/foo/')
        req2 = RequestFactory().post('/bar/')
        from results.context_processors import site_settings
        r1 = site_settings(req1)
        r2 = site_settings(req2)
        assert r1 == r2
