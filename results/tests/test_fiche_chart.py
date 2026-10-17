"""
Fiche coureur — attributes data-* du graphique d'évolution du rang.

Le template `results/competitor_detail.html` expose sur chaque ligne de split
(data-ctrl) les rangs lus par `fiche.js` pour construire ses deux courbes :
`data-rank` (rang au cumulé, courbe verte) et `data-leg-rank` (rang sur le
tronçon, courbe bleue). La boîte `#ficheRankChart` porte les libellés
traduits des deux courbes. Rendu pur (render_to_string) — aucune DB.
"""

from types import SimpleNamespace

import pytest

from django.template.loader import render_to_string

from results.models import STAT_OK


def _split(ctrl, abs_time, leg_time, abs_rank=None, leg_rank=None, **extra):
    sp = {
        'ctrl_name': ctrl, 'abs_time': abs_time, 'leg_time': leg_time,
        'abs_rank': abs_rank, 'leg_rank': leg_rank,
        'is_best': False, 'neg_leg': False,
    }
    sp.update(extra)
    return sp


SPLITS = [
    _split('1-101', '0:30', '0:30', abs_rank=3, leg_rank=1),
    _split('2-102', '1:02', '0:32', abs_rank=2, leg_rank=3),
    _split('Arrivée', '1:25', '0:23', abs_rank=2, leg_rank=2),
]


def _ctx(**overrides):
    ctx = {
        'competition': SimpleNamespace(cid=1, name='Test'),
        'competitor': SimpleNamespace(
            id=7, name='Coureur 7', nat='', neg_time=False, org=1,
            st=100000, it=105100, is_ok=True, status_label='OK',
            stat=STAT_OK,
        ),
        'org': SimpleNamespace(name='Club', nat=''),
        'cls': SimpleNamespace(name='H21'),
        'splits': SPLITS,
        'can_show_splits': True,
        'competitor_rank': 2,
        'gap_to_first': 500,
        'class_rank_total': 3,
        'rank_chart': True,
        'nat_code': '',
        'neg_time_warning': None,
        'total_time': '1:25',
    }
    ctx.update(overrides)
    return ctx


def _render(**overrides):
    return render_to_string('results/competitor_detail.html', _ctx(**overrides))


class TestRangsExposeesAuxCourbes:
    """Les lignes de splits portent data-rank et data-leg-rank (fiche.js)."""

    def test_ligne_de_poste_porte_les_deux_rangs(self):
        html = _render()
        assert ('data-ctrl="1-101" data-abs="0:30" data-leg="0:30" '
                'data-rank="3" data-leg-rank="1"') in html

    def test_ligne_arrivee_porte_les_deux_rangs(self):
        html = _render()
        assert 'data-ctrl="Arrivée"' in html
        assert 'data-rank="2" data-leg-rank="2"' in html

    def test_rang_absent_sans_attribut(self):
        splits = [_split('1-101', '0:30', '0:30', abs_rank=None, leg_rank=None)]
        html = _render(splits=splits)
        assert 'data-ctrl="1-101"' in html
        assert 'data-rank' not in html
        assert 'data-leg-rank' not in html


class TestBoiteGraphe:
    """La boîte #ficheRankChart porte les libellés des deux courbes."""

    def test_libelles_des_deux_courbes(self):
        html = _render()
        assert 'data-lbl-abs-rank="Rang cumulé"' in html
        assert 'data-lbl-leg-rank="Rang tronçon"' in html
        assert 'data-lbl-rank="Rang"' in html
        assert 'data-lbl-abs="Cumulé"' in html
        assert 'data-lbl-leg="Tronçon"' in html

    def test_boite_sans_au_moins_2_rangs_masquee_cote_js(self):
        # La vue pose rank_chart=False → ni carte, ni Chart.js chargé
        html = _render(rank_chart=False)
        assert 'ficheRankChart' not in html
        assert 'chart.umd.min.js' not in html

    def test_boite_presente_avec_au_moins_2_rangs(self):
        html = _render()
        assert 'id="ficheRankChart"' in html
        assert 'chart.umd.min.js' in html
        assert 'fiche.js' in html


@pytest.mark.parametrize('ctrl,rank,leg_rank', [
    ('1-101', '3', '1'),
    ('2-102', '2', '3'),
    ('Arrivée', '2', '2'),
])
def test_chaque_poste_expose_ses_rangs(ctrl, rank, leg_rank):
    """Chaque ligne (postes + arrivée) rend les deux data-attributes attendus."""
    html = _render()
    import re
    m = re.search(
        r'data-ctrl="%s"[^>]*' % re.escape(ctrl), html)
    assert m, ctrl
    assert 'data-rank="%s"' % rank in m.group(0)
    assert 'data-leg-rank="%s"' % leg_rank in m.group(0)
