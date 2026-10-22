"""Régression P0-01 — transport des données JSON vers les pages.

Les données issues de MeOS (noms, clubs, libellés de postes…) ne doivent
jamais être interpolées directement dans un bloc ``<script>``. Elles passent
par le filtre Django ``json_script`` puis sont relues avec
``COUtils.readJSONScript``. Un nom contenant ``</script>`` ou une balise HTML
reste ainsi une simple chaîne JSON.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from django.template.loader import render_to_string

from results.tests.test_analysis_tabs import _course, _page_ctx

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / 'templates' / 'results'

PAYLOAD = '</script><script>alert("xss")</script><img src=x onerror=alert(1)>'
ESCAPED_CLOSE = '\\u003C/script\\u003E'


def _analysis_ctx(**extra):
    """Contexte minimal des onglets d'analyse, avec des données à afficher."""
    ctx = _page_ctx()
    ctx.update(
        no_data=False,
        n_finishers=1,
        n_runners=1,
        n_controls=1,
        n_legs=2,
        partial_analysis=False,
        n_ok=1,
        n_total=1,
        has_splits=True,
        can_show_splits=True,
        leader_time='1:00',
        controls_seq=[{'ctrl_id': 31, 'ctrl_name': 'P31'}],
        results=[],
        t1=7,
        t2=20,
        neg_time_warning=None,
        superman_total='1:00:00',
        controls_labels=['P31'],
        superman_leg_data=[],
        category_regularity=None,
        prev_cls=None,
        next_cls=None,
    )
    ctx.update(extra)
    return ctx


ANALYSIS_CASES = [
    (
        'results/performance.html',
        dict(
            series=[{'name': PAYLOAD, 'org': PAYLOAD}],
            leg_info=[{'label': PAYLOAD, 'ref': PAYLOAD}],
        ),
    ),
    (
        'results/superman.html',
        dict(
            series=[{'name': PAYLOAD, 'org': PAYLOAD}],
            x_labels=[PAYLOAD],
        ),
    ),
    (
        'results/grouping.html',
        dict(
            series=[{'name': PAYLOAD, 'org': PAYLOAD}],
            x_labels=[PAYLOAD],
        ),
    ),
    (
        'results/regularity.html',
        dict(
            series=[{'name': PAYLOAD, 'org': PAYLOAD}],
            leg_info=[{'label': PAYLOAD, 'ref': PAYLOAD}],
        ),
    ),
    (
        'results/grouping_index.html',
        dict(
            results_data=[{'name': PAYLOAD, 'org': PAYLOAD, 'rank': 1,
                           'leg_indices': [1.0], 'leg_ref_names': [PAYLOAD]}],
            leg_labels=[PAYLOAD],
        ),
    ),
    (
        'results/duel.html',
        dict(runners=[{'name': PAYLOAD, 'org': PAYLOAD}]),
    ),
    (
        'results/class_results.html',
        dict(
            leg_error_data=[{'ctrl_name': PAYLOAD}],
            prev_cls=None, next_cls=None,
        ),
    ),
    (
        'results/course_results.html',
        dict(
            course=_course(),
            leg_error_data=[{'ctrl_name': PAYLOAD}],
        ),
    ),
]


@pytest.mark.parametrize('template,extra', ANALYSIS_CASES,
                         ids=[c[0] for c in ANALYSIS_CASES])
def test_payload_echappe_dans_les_pages_d_analyse(template, extra):
    html = render_to_string(template, _analysis_ctx(**extra))

    assert PAYLOAD not in html
    assert ESCAPED_CLOSE in html


def test_payload_echappe_dans_la_liste_de_depart():
    data = {
        'meta': {'count': 1},
        'groups': {
            'category': [{'name': PAYLOAD}],
            'club': [],
            'start_time': [],
        },
    }
    ctx = {
        'competition': SimpleNamespace(
            cid=1, name='Test', date=None, organizer=None,
        ),
        'start_list_data': data,
    }

    html = render_to_string('results/start_list.html', ctx)

    assert PAYLOAD not in html
    assert ESCAPED_CLOSE in html
    # Le script de la page utilise COUtils : il doit être chargé après site.js.
    assert html.index('results/js/site.js') < html.index(
        "COUtils.readJSONScript('start-list-data')"
    )


def test_payload_echappe_dans_verifie_moi():
    result = SimpleNamespace(
        n_runners=1, n_with_card=0, n_skipped=0, rows=[],
    )
    ctx = {
        'result': result,
        'csv_content': PAYLOAD,
        'csv_filename': PAYLOAD,
    }

    html = render_to_string('results/verifie_moi.html', ctx)

    assert PAYLOAD not in html
    assert ESCAPED_CLOSE in html


@pytest.mark.parametrize('template', [
    'performance.html',
    'superman.html',
    'grouping.html',
    'regularity.html',
    'grouping_index.html',
    'duel.html',
    'start_list.html',
    'verifie_moi.html',
    'class_results.html',
    'course_results.html',
])
def test_aucune_donnee_json_interpolee_avec_safe(template):
    """Les anciens marqueurs ``*_json|safe`` ne doivent pas revenir."""
    source = (TEMPLATES_DIR / template).read_text()

    for marker in (
        'series_json|safe',
        'leg_info_json|safe',
        'x_labels_json|safe',
        'results_json|safe',
        'leg_labels_json|safe',
        'runners_json|safe',
        'start_list_data|safe',
        'csv_content_json|safe',
        'filename_json|safe',
        'leg_error_data_json|safe',
    ):
        assert marker not in source, f'{template} : {marker}'
