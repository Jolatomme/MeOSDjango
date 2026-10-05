"""Badges d'en-tête unifiés des onglets d'analyse.

Règle : à droite du titre, chaque page affiche
``[badge contextuel]`` + « N coureur(s) » + « N poste(s) » — plus jamais
« tronçon(s) », « contrôle(s) », « partant(s) » ou « participant(s) ».
Le badge « poste(s) » est masqué quand la course n'a aucun poste.

Les assertions portent sur le HTML rendu (le gabarit est monté avec un
contexte ``no_data: False`` minimal).
"""
import re

import pytest

from pathlib import Path

from django.template.loader import render_to_string

from results.tests.test_analysis_tabs import TEMPLATES_DIR, _course, _page_ctx

STATIC_CSS = Path(__file__).resolve().parent.parent / 'static' / 'results' / 'css'


def _ctx(**extra):
    """Contexte minimal d'une page d'analyse avec données (5 coureurs, 2 postes)."""
    ctx = _page_ctx()
    ctx.update(
        no_data=False, n_finishers=5, n_runners=5, n_controls=2, n_legs=3,
        partial_analysis=False, n_ok=0, n_total=5, has_splits=True,
        can_show_splits=True, leader_time='1:02:03',
        controls_seq=[{'ctrl_id': 31, 'ctrl_name': 'P31'},
                      {'ctrl_id': 32, 'ctrl_name': 'P32'}],
        results=[{'id': 1}] * 5,
    )
    ctx.update(extra)
    return ctx


# (gabarit, variables propres à la page pour le rendu complet)
CASES = [
    ('results/superman.html',
     dict(series=[], series_json='[]', x_labels_json='[]', superman_total='1:00:00',
          controls_labels=['P31'],
          superman_leg_data=[{'ctrl': 'P31', 'time': '1:00', 'names': ['X']}])),
    ('results/performance.html',
     dict(series_json='[]', leg_info_json='[]')),
    ('results/regularity.html',
     dict(series_json='[]', leg_info_json='[]', category_regularity=0.5)),
    ('results/grouping.html',
     dict(series_json='[]')),
    ('results/grouping_index.html',
     dict(results_json='[]', leg_labels_json='[]', t1=7, t2=20)),
    ('results/duel.html',
     dict(runners_json='[]', neg_time_warning=None)),
    ('results/class_results.html',
     dict(prev_cls=None, next_cls=None)),
    ('results/course_results.html',
     dict(course=_course())),
    ('results/recapitulatif.html', dict()),
]

# Libellés obsolètes qui ne doivent plus apparaître dans un badge
BADGE_OBSOLETE = ('tronçons</span>', 'contrôles</span>', '5 partants</span>',
                  '5 participants</span>', '5 classés</span>')

# Contexte « course sans poste » : aucun compteur à afficher
ZERO_CTX = dict(n_controls=0, n_legs=1, has_splits=False,
                controls_seq=[], series_json='[]', leg_info_json='[]',
                results_json='[]', leg_labels_json='[]', t1=7, t2=20,
                runners_json='[]', neg_time_warning=None,
                series=[], x_labels_json='[]', superman_total='1:00:00',
                controls_labels=[], superman_leg_data=[],
                category_regularity=None, prev_cls=None, next_cls=None)


@pytest.mark.parametrize('template,extra', CASES, ids=[c[0] for c in CASES])
class TestBadgesEnTeteRendus:

    def test_badges_unifies(self, template, extra):
        """Le rendu affiche « 5 coureurs » et « 2 postes », sans ancien libellé."""
        html = render_to_string(template, _ctx(**extra))
        assert '5 coureurs' in html, template
        assert '2 postes' in html, template
        for obsolete in BADGE_OBSOLETE:
            assert obsolete not in html, (template, obsolete)


@pytest.mark.parametrize('template,extra', CASES, ids=[c[0] for c in CASES])
class TestBadgePostesMasqueSiZero:

    def test_aucun_poste_sans_badge(self, template, extra):
        """Sans aucun poste, le badge disparaît (pas de « 0 poste »)."""
        html = render_to_string(template, _ctx(**{**extra, **ZERO_CTX}))
        assert 'postes</span>' not in html, template


# Enveloppe unique du groupe de badges (aligné à droite dans la rangée du titre)
BADGE_GROUP = '<div class="d-flex align-items-center gap-2 flex-wrap">'


@pytest.mark.parametrize('template,extra', CASES, ids=[c[0] for c in CASES])
class TestGroupeBadgesAlignaDroite:

    def test_groupe_unique_dans_la_rangee_du_titre(self, template, extra):
        """« N coureurs » est dans l'enveloppe commune, à droite du titre (pas en enfant
        direct de la rangée justify-content-between, ce qui décalait les badges)."""
        html = render_to_string(template, _ctx(**extra))
        pos_badge = html.index('5 coureurs')
        pos_groupe = html.rfind(BADGE_GROUP, 0, pos_badge)
        assert pos_groupe != -1, f'{template} : enveloppe de badges absente'
        assert '</div>' not in html[pos_groupe:pos_badge], \
            f'{template} : le badge est hors de l\u2019enveloppe'
        assert 'justify-content-between' in html[max(0, pos_groupe - 1200):pos_groupe], \
            f'{template} : enveloppe hors rangée du titre'


# ─── Pictogramme du titre : doré, jamais blanc hérité de l'en-tête ──────────

class TestPictogrammeTitreDore:

    def test_regle_css_icone_doree(self):
        """L'en-tête est blanche (#fff) : l'icône du <h1> doit être forcée en doré."""
        css = (STATIC_CSS / 'site.css').read_text(encoding='utf-8')
        assert '.co-page-header h1 > i { color: var(--co-gold); }' in css

    @pytest.mark.parametrize('template', ['results/live_results.html',
                                          'results/class_results.html',
                                          'results/course_results.html',
                                          'results/relay_results.html'])
    def test_pas_de_couleur_en_ligne_concurrente(self, template):
        """Pas de style inline sur l'icône du <h1> (sinon la règle CSS est ignorée)."""
        text = (TEMPLATES_DIR / template).read_text(encoding='utf-8')
        h1 = re.search(r'<h1.*?</h1>', text, re.S)
        assert h1, f'{template} : <h1> introuvable'
        icone = re.search(r'<i[^>]*>', h1.group(0))
        assert icone, f'{template} : icône introuvable dans le <h1>'
        assert 'style=' not in icone.group(0), f'{template} : {icone.group(0)}'


# ─── En-tête « Résultats » aligné sur les pages d'analyse ───────────────────
# <h1> = « Résultats », sous-titre = « catégorie — course » (ou circuit — course),
# feuille de fil d'Ariane « Résultats », <title> préfixé « Résultats — ».

CASES_TITRE = [
    pytest.param('results/class_results.html', {}, 'H21 — Test', id='categorie'),
    pytest.param('results/course_results.html', {'course': _course()},
                 'H21 + H35 — Test', id='circuit'),
]


@pytest.mark.parametrize('template,extra,sous_titre', CASES_TITRE)
class TestEnTeteResultats:

    def _html(self, template, extra):
        return render_to_string(template, _ctx(**extra))

    def test_h1_est_resultats(self, template, extra, sous_titre):
        html = self._html(template, extra)
        h1 = re.search(r'<h1.*?</h1>', html, re.S)
        assert h1, f'{template} : <h1> introuvable'
        assert 'Résultats' in h1.group(0), f'{template} : {h1.group(0)}'

    def test_sous_titre_categorie_et_course(self, template, extra, sous_titre):
        """Sous-titre comme les analyses : <catégorie|circuit> — <course>."""
        assert sous_titre in self._html(template, extra), template

    def test_fil_ariane_fin_résultats(self, template, extra, sous_titre):
        html = self._html(template, extra)
        assert 'aria-current="page">Résultats</li>' in html, template

    def test_titre_navigateur_prefixe(self, template, extra, sous_titre):
        html = self._html(template, extra)
        titre = re.search(r'<title>(.*?)</title>', html, re.S)
        assert titre, f'{template} : <title> introuvable'
        titre = ' '.join(titre.group(1).split())
        assert titre.startswith('Résultats — '), f'{template} : {titre}'
        assert sous_titre in titre, f'{template} : {titre}'
