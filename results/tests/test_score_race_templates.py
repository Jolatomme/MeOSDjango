"""Rendu de la course au score dans les deux tableaux de résultats.

Vérifie la colonne « Points », le badge « Score max » et le fait qu'un
non-classé affiche « — » plutôt que de répéter son statut.
"""

import re
from types import SimpleNamespace

import pytest

from django.template.loader import render_to_string

from results.tests.test_analysis_tabs import HASH, _course, _page_ctx


FINISHER = SimpleNamespace(
    id=1, name='Alice', rt=5000, stat=1, cls=10, org=1, is_ok=True,
    score=15, time_behind=0, rank=1, cat_rank=1, splits=[], neg_time=False,
)
NON_FINISHER = SimpleNamespace(
    id=2, name='Bob', rt=-1, stat=3, cls=10, org=1, is_ok=False,
    score=0, time_behind=None, rank=None, cat_rank=None, splits=[],
    neg_time=False,
)


def _ctx(*, score_race, course_mode):
    ctx = _page_ctx(
        course=_course() if course_mode else None,
        cls_name=HASH if course_mode else 'H21',
    )
    ctx.update(
        no_data=False,
        n_finishers=1,
        n_runners=2,
        n_controls=2,
        n_legs=1,
        partial_analysis=False,
        n_ok=1,
        n_total=2,
        has_splits=False,
        can_show_splits=False,
        leader_time='8:20',
        leader_score=15 if score_race else None,
        score_race=score_race,
        results_colspan=(
            (7 if course_mode else 6) if score_race
            else (6 if course_mode else 5)
        ),
        controls_seq=[{'ctrl_id': 31, 'ctrl_name': '31'}],
        results=[FINISHER, NON_FINISHER],
        leg_error_data=[],
        neg_time_warning=None,
        prev_cls=None,
        next_cls=None,
        all_classes=[],
    )
    return ctx


CASES = [
    pytest.param('results/class_results.html', False, id='categorie'),
    pytest.param('results/course_results.html', True, id='circuit'),
]


@pytest.mark.parametrize('template,course_mode', CASES)
class TestScoreRaceRendering:

    def test_colonne_points_et_score_max(self, template, course_mode):
        html = render_to_string(
            template, _ctx(score_race=True, course_mode=course_mode),
        )
        assert '<th class="text-end">Points</th>' in html
        assert 'Score max : 15' in html
        assert 'score-col' in html

    def test_non_classe_tirets_sans_statut(self, template, course_mode):
        """La cellule Points d'un non-classé affiche « — », pas son statut."""
        html = render_to_string(
            template, _ctx(score_race=True, course_mode=course_mode),
        )
        cells = re.findall(
            r'<td class="text-end score-col">(.*?)</td>', html, re.S,
        )
        assert len(cells) == 2
        assert '15' in cells[0]
        assert '—' in cells[1]
        assert 'badge' not in cells[1]

    def test_sans_score_pas_de_colonne(self, template, course_mode):
        html = render_to_string(
            template, _ctx(score_race=False, course_mode=course_mode),
        )
        assert 'score-col' not in html
        assert 'Score max' not in html
        assert '<th class="text-end">Points</th>' not in html
