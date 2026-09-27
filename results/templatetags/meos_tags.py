import re
import unicodedata

from django import template
from django.contrib.staticfiles import finders
from django.utils.safestring import mark_safe
from results.models import format_time, STATUS_LABELS

register = template.Library()

# ─── Logos d'organisation ────────────────────────────────────────────────────
# 1) Alias : sous-chaîne du nom slugifié → fichier statique connu.
# 2) Convention : tout fichier results/img/org/<slug>.(svg|png|webp) est utilisé
#    tel quel — il suffit de déposer le fichier pour qu'il apparaisse.
ORG_LOGO_ALIASES = {
    'cocs': 'results/img/logo-cocs.svg',
}
ORG_LOGO_DIR = 'results/img/org/'
ORG_LOGO_EXTS = ('.svg', '.png', '.webp')


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


def _slugify(value):
    """Slug ASCII : 'COCS 7309AURA' → 'cocs-7309aura'."""
    text = unicodedata.normalize('NFD', str(value))
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


@register.filter
def org_logo(organizer):
    """Chemin statique du logo de l'organisation, ou '' si inconnu.

    Accepte le nom libre de l'organisation (mopCompetition.organizer).
    """
    if not organizer:
        return ''
    slug = _slugify(organizer)
    if not slug:
        return ''
    parts = slug.split('-')
    for needle, path in ORG_LOGO_ALIASES.items():
        if needle in parts or slug.startswith(f'{needle}-'):
            return path
    for ext in ORG_LOGO_EXTS:
        candidate = f'{ORG_LOGO_DIR}{slug}{ext}'
        if finders.find(candidate):
            return candidate
    return ''
