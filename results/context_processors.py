from pathlib import Path

from django.conf import settings

# Dossier imposé pour le logo du club : results/static/results/img/. Le réglage
# ORG_LOGO ne contient que le nom du fichier (voir MeOSDjango/settings.py).
ORG_LOGO_STATIC_DIR = 'results/img/'
DEFAULT_ORG_LOGO = 'logo-cocs.svg'


def _org_logo_static_path():
    """Chemin statique du logo du club, toujours dans results/img/."""
    name = getattr(settings, 'ORG_LOGO', DEFAULT_ORG_LOGO)
    if not name:
        return ''
    # Un éventuel chemin fourni est réduit au seul nom de fichier.
    return f'{ORG_LOGO_STATIC_DIR}{Path(str(name)).name}'


def site_settings(request):
    return {
        'SITE_NAME':          getattr(settings, 'SITE_NAME',          'Résultats CO'),
        'SITE_SUBTITLE':      getattr(settings, 'SITE_SUBTITLE',      'Course d\'Orientation'),
        'CLUB_NAME':          getattr(settings, 'CLUB_NAME',          'COCS'),
        'ORG_LOGO':           _org_logo_static_path(),
        'CLUB_COLOR_PRIMARY': getattr(settings, 'CLUB_COLOR_PRIMARY', '#1a6b3c'),
        'CLUB_COLOR_ACCENT':  getattr(settings, 'CLUB_COLOR_ACCENT',  '#f0a500'),
        'ENABLE_RACE_CREATION': getattr(settings, 'ENABLE_RACE_CREATION', True),
    }
