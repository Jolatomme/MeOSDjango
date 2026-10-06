from datetime import date, datetime
from pathlib import Path

from django import template
from django.conf import settings
from django.urls import reverse
from django.utils.safestring import mark_safe
from results.models import format_time, STATUS_LABELS

register = template.Library()

# ─── Logo du site (fichier org_logo/site.* à la racine du projet) ─────────────
# Convention zéro configuration : déposer le logo du club sous
# org_logo/site.svg (ou .png / .jpg / .jpeg) — il apparaît dans la barre de
# navigation et le bandeau d'accueil ; absent → aucune image.
SITE_LOGO_EXTENSIONS = ('.svg', '.png', '.jpg', '.jpeg')


@register.filter
def meos_time(seconds):
    """Formate des secondes MeOS en MM:SS."""
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return '-'
    if seconds < 0:
        # MeOS utilise rt=-1 pour les non classés : on ne formate pas les négatifs ici
        return '-'
    return format_time(seconds)


@register.filter
def status_badge(stat_code):
    """Classe Bootstrap pour un code statut."""
    try:
        return STATUS_LABELS.get(int(stat_code), ('?', 'secondary'))[1]
    except (TypeError, ValueError):
        return 'secondary'


@register.filter
def status_label(stat_code):
    """Libellé lisible pour un code statut."""
    try:
        return STATUS_LABELS.get(int(stat_code), ('?', 'secondary'))[0]
    except (TypeError, ValueError):
        return '?'


@register.filter(is_safe=True)
def display_name(name):
    """Format 'Firstname Lastname' as 'Lastname,<br>Firstname'."""
    parts = name.strip().split(None, 1)
    if len(parts) == 2:
        return mark_safe(f"{parts[1]},<br>{parts[0]}")
    return name


@register.filter(is_safe=True)
def iso_date(value):
    """Date au format ISO ``YYYY-MM-DD`` attendu par ``<input type="date">``.

    Un objet ``date`` rendu brut dans un template est localisé (« 17 mai 2026 »
    en français) : le navigateur ignore alors la valeur et affiche le champ
    vide. Les chaînes (valeur déjà saisie, formulaire lié) passent telles
    quelles ; ``None``/vide → ``''``.
    """
    if isinstance(value, datetime):        # datetime est une sous-classe de date
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value or ''


@register.simple_tag
def time_behind(runner_time, leader_time):
    """Affiche l'écart '+MM:SS' ou '' pour le leader."""
    try:
        diff = int(runner_time) - int(leader_time)
    except (TypeError, ValueError):
        return '-'
    if diff <= 0:
        return ''
    return f'+{format_time(diff)}'


@register.simple_tag
def site_logo():
    """URL du logo du club (``org_logo/site.*``) ou '' si le fichier est absent.

    Le premier format trouvé est utilisé, dans l'ordre SVG, PNG, JPG, JPEG.
    """
    root = Path(settings.ORG_LOGO_DIR)
    for ext in SITE_LOGO_EXTENSIONS:
        name = f'site{ext}'
        if (root / name).is_file():
            return reverse('results:org_logo', args=[name])
    return ''
