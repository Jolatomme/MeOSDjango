from django.conf import settings


def site_settings(request):
    return {
        'SITE_NAME':          getattr(settings, 'SITE_NAME',          'Résultats CO'),
        'SITE_SUBTITLE':      getattr(settings, 'SITE_SUBTITLE',      'Course d\'Orientation'),
        'CLUB_NAME':          getattr(settings, 'CLUB_NAME',          'COCS'),
        'CLUB_COLOR_PRIMARY': getattr(settings, 'CLUB_COLOR_PRIMARY', '#1a6b3c'),
        'CLUB_COLOR_ACCENT':  getattr(settings, 'CLUB_COLOR_ACCENT',  '#f0a500'),
    }
