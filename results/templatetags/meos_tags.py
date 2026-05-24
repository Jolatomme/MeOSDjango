from django import template
from django.utils.safestring import mark_safe
from results.models import format_time, STATUS_LABELS

register = template.Library()


@register.filter
def meos_time(seconds):
    """Formate des secondes MeOS en MM:SS."""
    try:
        return format_time(int(seconds))
    except (TypeError, ValueError):
        return '-'


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
