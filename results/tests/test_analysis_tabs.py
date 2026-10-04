"""
Tests — barre d'onglets d'analyse unifiée (catégorie ET circuit).

``analysis_tabs.html`` est le partial UNIQUE inclus par toutes les pages
d'analyse (live, résultats, superman, indice perf., régularité,
regroupement, lièvre/suiveur, récapitulatif, duel). Il s'adapte seul au
contexte :

  - ``course=None`` → URLs ``/competition/<cid>/class/<nom>/…``   (ns ``results:*``)
  - ``course`` dict → URLs ``/competition/<cid>/course/<hash>/…`` (ns ``results:course_*``)

Le libellé du bouton duel est « Duel coureurs » dans les deux cas, et le
titre du dossier duel aussi. L'ancien partial ``course_analysis_tabs.html``
a été fusionné puis supprimé.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from django.template.loader import render_to_string
from django.urls import reverse

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / 'templates'

HASH = 'abc12345'

# (current_analysis, nom d'URL catégorie, nom d'URL circuit)
# Ordre visuel de la barre : Récapitulatif en DERNIER position (le plus à droite).
TABS = [
    ('live',            'live',           'course_live'),
    ('results',         'class_results',  'course_results'),
    ('superman',        'superman',       'course_superman'),
    ('performance',     'performance',    'course_performance'),
    ('regularity',      'regularity',     'course_regularity'),
    ('grouping',        'grouping',       'course_grouping'),
    ('grouping_index',  'grouping_index', 'course_grouping_index'),
    ('duel',            'duel',           'course_duel'),
    ('recapitulatif',   'recapitulatif',  'course_recapitulatif'),
]

# Libellés attendus de la barre d'onglets (identiques catégorie ET circuit)
TABS_LABELS = {
    'live':           'Live',
    'results':        'Résultats',
    'superman':       'Superman',
    'performance':    'Indice perf.',
    'regularity':     'Régularité',
    'grouping':       'Regroupement',
    'grouping_index': 'Lièvre / Suiveur',
    'duel':           'Duel coureurs',
    'recapitulatif':  'Récapitulatif',
}

ANALYSIS_TEMPLATES = [
    'results/superman.html',
    'results/performance.html',
    'results/regularity.html',
    'results/grouping.html',
    'results/grouping_index.html',
    'results/duel.html',
    'results/recapitulatif.html',
]

# Pages qui incluent (directement ou via analysis_base) le partial unifié
PAGES_WITH_RIBBON = [
    'results/analysis_base.html',
    'results/live_results.html',
    'results/class_results.html',
    'results/course_results.html',
    'results/duel.html',
    'results/regularity.html',
    'results/grouping_index.html',
    'results/recapitulatif.html',
]


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _ribbon_ctx(course=None, cls_name='H21'):
    return {
        'competition': SimpleNamespace(cid=1, name='Test', date=None),
        'cls':         SimpleNamespace(id=cls_name, name=cls_name, cid=1),
        'course':      course,
        'current_analysis': 'x',
    }


def _course():
    return {
        'hash':         HASH,
        'display_name': 'H21 + H35',
        'classes':      [SimpleNamespace(name='H21'),
                         SimpleNamespace(name='H35')],
    }


def _page_ctx(course=None, cls_name='H21'):
    """Contexte minimal pour rendre une des 7 pages d'analyse (no_data)."""
    ctx = _ribbon_ctx(course=course, cls_name=cls_name)
    ctx.update({
        'current_analysis': 'duel',
        'partial_analysis': True,
        'n_ok': 1,
        'n_total': 5,
        'no_data': True,
        'has_splits': True,
    })
    return ctx


def _duel_url(is_course, cls_name):
    name = 'course_duel' if is_course else 'duel'
    return reverse('results:' + name, kwargs={'cid': 1, 'class_id': cls_name})


# ─── Partial unifié : URLs par mode ─────────────────────────────────────────

class TestRibbonCategoryMode:

    def test_urls_categorie(self):
        html = render_to_string('results/analysis_tabs.html',
                                _ribbon_ctx(course=None))
        for _, cat_name, _ in TABS:
            url = reverse('results:' + cat_name, kwargs={'cid': 1, 'class_id': 'H21'})
            assert f'href="{url}"' in html, cat_name

    def test_libelles(self):
        html = render_to_string('results/analysis_tabs.html',
                                _ribbon_ctx(course=None))
        for label in TABS_LABELS.values():
            assert label in html, label

    def test_pas_d_url_circuit(self):
        html = render_to_string('results/analysis_tabs.html',
                                _ribbon_ctx(course=None))
        for _, _, course_name in TABS:
            url = reverse('results:' + course_name, kwargs={'cid': 1, 'class_id': 'H21'})
            assert url not in html, course_name


class TestRibbonCourseMode:

    def test_urls_circuit(self):
        html = render_to_string('results/analysis_tabs.html',
                                _ribbon_ctx(course=_course(),
                                            cls_name=HASH))
        for _, _, course_name in TABS:
            url = reverse('results:' + course_name, kwargs={'cid': 1, 'class_id': HASH})
            assert f'href="{url}"' in html, course_name

    def test_libelles_identiques(self):
        """Mêmes libellés que le mode catégorie — pas de « Duel » seul."""
        html = render_to_string('results/analysis_tabs.html',
                                _ribbon_ctx(course=_course(),
                                            cls_name=HASH))
        for label in TABS_LABELS.values():
            assert label in html, label
        assert '>Duel</span>' not in html

    def test_pas_d_url_categorie(self):
        html = render_to_string('results/analysis_tabs.html',
                                _ribbon_ctx(course=_course(),
                                            cls_name=HASH))
        for _, cat_name, _ in TABS:
            url = reverse('results:' + cat_name, kwargs={'cid': 1, 'class_id': HASH})
            assert url not in html, cat_name

    @pytest.mark.parametrize('key,_,__', TABS)
    def test_onglet_actif(self, key, _, __):
        html = render_to_string(
            'results/analysis_tabs.html',
            {**_ribbon_ctx(course=_course(), cls_name=HASH),
             'current_analysis': key})
        assert 'analysis-tab active' in html
        assert f"current_analysis == '{key}'" not in html  # tag bien évalué


# ─── Ordre visuel des onglets ───────────────────────────────────────────────

class TestOrdreOnglets:

    @pytest.mark.parametrize('course,cls_name',
                             [(None, 'H21'), (_course(), HASH)],
                             ids=['categorie', 'circuit'])
    def test_recapitulatif_en_dernier(self, course, cls_name):
        """Récapitulatif est le dernier onglet (le plus à droite)."""
        html = render_to_string('results/analysis_tabs.html',
                                _ribbon_ctx(course=course,
                                            cls_name=cls_name))
        assert html.rindex('<span>Récapitulatif</span>') > \
            html.rindex('<span>Duel coureurs</span>')

    @pytest.mark.parametrize('course,cls_name',
                             [(None, 'H21'), (_course(), HASH)],
                             ids=['categorie', 'circuit'])
    def test_ordre_complet(self, course, cls_name):
        """Ordre : Live → Résultats → Superman → Indice perf. → Régularité
        → Regroupement → Lièvre/Suiveur → Duel coureurs → Récapitulatif."""
        html = render_to_string('results/analysis_tabs.html',
                                _ribbon_ctx(course=course,
                                            cls_name=cls_name))
        labels = [f'<span>{label}</span>' for label in TABS_LABELS.values()]
        positions = [html.index(lbl) for lbl in labels]
        assert positions == sorted(positions), \
            'Ordre des onglets inattendu : ' + ' → '.join(
                lbl[6:-7] for lbl in labels)


# ─── Un seul partial, inclus partout ────────────────────────────────────────

class TestPartialUnifie:

    def test_ancien_partial_supprime(self):
        assert not (TEMPLATES_DIR / 'course_analysis_tabs.html').exists()

    def test_aucune_reference_ancien_partial(self):
        for tpl in TEMPLATES_DIR.glob('*.html'):
            assert 'course_analysis_tabs' not in tpl.read_text(
                encoding='utf-8'), tpl.name

    @pytest.mark.parametrize('name', PAGES_WITH_RIBBON)
    def test_page_inclut_le_partial_unifie(self, name):
        text = (TEMPLATES_DIR / name).read_text(encoding='utf-8')
        assert 'results/analysis_tabs.html' in text, name


# ─── Rendu complet des 7 pages d'analyse, dans les deux modes ───────────────

@pytest.mark.parametrize('template', ANALYSIS_TEMPLATES)
class TestPagesAnalyse:

    def test_mode_circuit_urls_course(self, template):
        html = render_to_string(template, _page_ctx(course=_course(),
                                                     cls_name=HASH))
        assert _duel_url(True, HASH) in html, template
        assert 'Duel coureurs' in html, template

    def test_mode_circuit_sans_url_categorie(self, template):
        html = render_to_string(template, _page_ctx(course=_course(),
                                                     cls_name=HASH))
        assert _duel_url(False, HASH) not in html, template

    def test_mode_categorie_urls_class(self, template):
        html = render_to_string(template, _page_ctx(course=None))
        assert _duel_url(False, 'H21') in html, template
        assert 'Duel coureurs' in html, template

    def test_mode_categorie_sans_url_circuit(self, template):
        html = render_to_string(template, _page_ctx(course=None))
        assert _duel_url(True, 'H21') not in html, template


# ─── Libellés du dossier duel ───────────────────────────────────────────────

class TestLibellesDuel:

    def test_page_duel_titre_unifie(self):
        html = render_to_string('results/duel.html', _page_ctx())
        assert 'Duel de coureurs' not in html
        assert 'Duel coureurs' in html

    @pytest.mark.parametrize('template', ANALYSIS_TEMPLATES)
    def test_pas_de_mention_decalee(self, template):
        html = render_to_string(template, _page_ctx(course=_course(),
                                                     cls_name=HASH))
        assert 'Duel de coureurs' not in html, template
