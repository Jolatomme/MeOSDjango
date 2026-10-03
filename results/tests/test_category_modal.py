"""
Modale « Choisir une catégorie » — sélecteur en bas de page.

Le partial _category_modal.html est inclus par class_results / live /
recapitulatif (mode catégorie). Chaque vignette pointe vers
results:class_results ; les catégories relais sont redirigées par la vue.
"""

import re
from types import SimpleNamespace

import pytest

from django.template.loader import render_to_string


def _cls(id_, name):
    return SimpleNamespace(id=id_, name=name)


CATS = [_cls(10, 'H21'), _cls(20, 'D21'), _cls(30, 'H35')]


def _render(all_classes=CATS, current=None, cid=1):
    ctx = {
        'all_classes':  all_classes,
        'cls':          current or CATS[1],
        'competition':  SimpleNamespace(cid=cid),
    }
    return render_to_string('results/_category_modal.html', ctx)


class TestCategoryModalPartial:

    def test_affiche_toutes_les_categories(self):
        html = _render()
        for name in ('H21', 'D21', 'H35'):
            assert name in html
        assert 'category-picker-grid' in html
        assert html.count('category-picker-btn') >= len(CATS)

    def test_liens_vers_class_results(self):
        html = _render()
        assert '/competition/1/class/H21/' in html
        assert '/competition/1/class/D21/' in html
        assert '/competition/1/class/H35/' in html

    def test_declencheur_modal_present_dans_le_partial(self):
        html = _render()
        assert 'categoryPickerModal' in html

    def test_courante_activee(self):
        html = _render(current=CATS[2])
        assert 'aria-current="page"' in html
        assert re.search(r'category-picker-btn active[^>]*>\s*H35', html)
        # La courante n'est pas activee ailleurs
        assert not re.search(r'category-picker-btn active[^>]*>\s*H21', html)

    def test_aucune_activee_si_courante_inconnue(self):
        html = _render(current=_cls(99, 'XX'))
        assert 'aria-current' not in html
        assert ' active' not in html

    def test_lien_vers_page_competition_dans_footer(self):
        html = _render()
        assert 'href="/competition/1/"' in html

    def test_liste_vide_ne_rend_rien(self):
        assert _render(all_classes=[]).strip() == ''


# ─── Les 3 pages embarquent le déclencheur + la modale ───────────────────────

PAGE_CTX = {
    'competition':       SimpleNamespace(cid=1, name='Test'),
    'cls':               SimpleNamespace(id=20, name='D21'),
    'course':            None,
    'results':           [],
    'live':              [],
    'leader_time':       '-',
    'controls_seq':      [],
    'has_splits':        False,
    'can_show_splits':   False,
    'prev_cls':          SimpleNamespace(id=10, name='H21'),
    'next_cls':          SimpleNamespace(id=30, name='H35'),
    'all_classes':       CATS,
    'course_hash':       'abc12345',
    'current_analysis':  'results',
    'neg_time_warning':  '',
    'groups':            {},
    'race_state':        'finished',
    'leg_error_data_json': '[]',
    'partial_analysis':  False,
    'n_ok': 0, 'n_total': 0,
}

PAGES = [
    pytest.param('results/class_results.html', id='results'),
    pytest.param('results/live_results.html', id='live'),
    pytest.param('results/recapitulatif.html', id='recapitulatif'),
]


class TestPagesOuvrentLaModale:

    @pytest.mark.parametrize('template', PAGES)
    def test_declencheur_et_modale_presents(self, template):
        html = render_to_string(template, PAGE_CTX)
        assert 'data-bs-target="#categoryPickerModal"' in html
        assert 'id="categoryPickerModal"' in html
        assert 'category-picker-grid' in html

    @pytest.mark.parametrize('template', PAGES)
    def test_garde_les_chevrons_prev_next(self, template):
        html = render_to_string(template, PAGE_CTX)
        # prev/next pointent vers la meme page avec la categorie adjacente
        assert 'class/H21/' in html
        assert 'class/H35/' in html

    @pytest.mark.parametrize('template', PAGES)
    def test_vignettes_categories_dans_la_modale(self, template):
        html = render_to_string(template, PAGE_CTX)
        assert 'category-picker-btn' in html
        # La courante (D21) est marquee activee
        assert re.search(r'category-picker-btn active[^>]*>\s*D21', html)

    def test_le_bouton_n_est_plus_un_lien_vers_competition(self):
        """Le déclencheur est un bouton modal, pas une balise <a>."""
        html = render_to_string('results/class_results.html', PAGE_CTX)
        trigger = re.search(
            r'<button[^>]*data-bs-target="#categoryPickerModal"[^>]*>.*?</button>',
            html, re.S)
        assert trigger, 'bouton déclencheur absent'
        assert 'Toutes les catégories' in trigger.group(0)


# ─── Barre flottante en bas d'écran (.cat-nav-bar, position: sticky) ──────────

COURSE_CTX = dict(PAGE_CTX, course={
    'hash':          'abc12345',
    'display_name':  'Circuit A',
    'n_controls':    10,
    'classes':       [],
    'controls_seq':  [],
})


class TestBarreFlottante:

    @pytest.mark.parametrize('template', PAGES)
    def test_mode_categorie_utilise_la_barre_flottante(self, template):
        html = render_to_string(template, PAGE_CTX)
        assert 'class="cat-nav-bar"' in html
        # L'ancien conteneur inline (mt-3 d-flex…) n'existe plus
        assert 'mt-3 d-flex gap-2' not in html

    @pytest.mark.parametrize('template', PAGES)
    def test_mode_circuit_utilise_la_barre_flottante(self, template):
        html = render_to_string(template, COURSE_CTX)
        assert 'class="cat-nav-bar"' in html
        # Le bouton retour « Toutes les catégories » flotte aussi
        assert re.search(
            r'class="cat-nav-bar">\s*<a href="/competition/1/"', html)

    @pytest.mark.parametrize('template', PAGES)
    def test_un_seul_bouton_haut_de_page(self, template):
        """Pas de doublon : une seule barre par page."""
        html = render_to_string(template, PAGE_CTX)
        assert html.count('cat-nav-bar') == 1
