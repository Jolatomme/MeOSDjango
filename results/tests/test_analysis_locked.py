"""
Tests unitaires — blocage des analyses pendant la course.

Tant qu'un coureur PARTI (st > 0, heure de départ passée) n'a pas de statut
attribué par MeOS (lecture de puce à la GEC, ou statut définitif), les pages
d'analyse sont verrouillées (``analysis_locked``) : aucun calcul n'est lancé.
Les coureurs jamais partis (st = 0), au départ futur, ou avec un statut
définitif (OK, DNF, …) ne bloquent pas.

Couvre :
  - les 7 vues d'analyse (catégorie et circuit) : verrouillées quand un
    coureur parti est sans statut, sans appel aux services de calcul
  - grouping_analysis : cas non bloquants (st = 0, départ futur, statuts
    définitifs) — les autres vues avec peloton complet sont déjà couvertes
    par test_grouping.py / test_performance.py / test_courses.py / test_views.py
  - recapitulatif_csv : 409 quand la course est en cours, 200 sinon
"""

from unittest.mock import patch, MagicMock
import pytest

from django.test import RequestFactory

from results.models import STAT_OK, STAT_UNKNOWN, STAT_DNF
from results import views


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_competitor(id, *, st=1, stat=STAT_UNKNOWN, rt=0, is_ok=None):
    """Construit un MagicMock représentant un Mopcompetitor."""
    c = MagicMock()
    c.id    = id
    c.name  = f'Coureur {id}'
    c.org   = 1
    c.st    = st
    c.stat  = stat
    c.rt    = rt
    c.is_ok = (stat == STAT_OK and rt > 0) if is_ok is None else is_ok
    return c


def _get(url='/'):
    return RequestFactory().get(url)


# Départ toujours dans le passé (1 s après minuit) / toujours futur (24 h)
ST_PASSE  = 10
ST_FUTUR  = 24 * 3600 * 10


ANALYSIS_VIEWS = [
    pytest.param(views.superman_analysis,       'results/superman.html',       'superman',       id='superman'),
    pytest.param(views.performance_analysis,    'results/performance.html',    'performance',    id='performance'),
    pytest.param(views.regularity_analysis,     'results/regularity.html',     'regularity',     id='regularity'),
    pytest.param(views.grouping_analysis,       'results/grouping.html',       'grouping',       id='grouping'),
    pytest.param(views.grouping_index_analysis, 'results/grouping_index.html', 'grouping_index', id='grouping_index'),
    pytest.param(views.duel_analysis,           'results/duel.html',           'duel',           id='duel'),
    pytest.param(views.recapitulatif_analysis,  'results/recapitulatif.html',  'recapitulatif',  id='recapitulatif'),
]


# ─── Vue verrouillée : course en cours ───────────────────────────────────────

class TestAnalysisViewsLocked:

    def _run(self, view_fn, competitors, course=None):
        """Exécute une vue d'analyse et renvoie le contexte de rendu."""
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10; cls.name = 'H21'
        with patch('results.views._load_class_context',
                   return_value=(competition, cls, competitors, course)), \
             patch('results.views.Mopteam') as MockTeam, \
             patch('results.views.rank_finishers')   as mock_rank, \
             patch('results.views.get_org_map')      as mock_org, \
             patch('results.views.get_class_controls') as mock_ctrl, \
             patch('results.views.get_radio_map')    as mock_radio, \
             patch('results.views.render') as mock_render:
            MockTeam.objects.filter.return_value.exists.return_value = False
            view_fn(_get(), cid=1, class_id=10)
            _, template, ctx = mock_render.call_args[0]
        return template, ctx, mock_rank, mock_org, mock_ctrl, mock_radio

    @pytest.mark.parametrize('view_fn,template,analysis_key', ANALYSIS_VIEWS)
    def test_bloque_si_coureur_partie_sans_statut(self, view_fn, template, analysis_key):
        """Un coureur parti (st > 0, départ passé) sans statut → verrouillé."""
        en_course = make_competitor(1, st=ST_PASSE, stat=STAT_UNKNOWN)
        ok        = make_competitor(2, st=ST_PASSE, stat=STAT_OK, rt=5000)
        tpl, ctx, mock_rank, mock_org, mock_ctrl, mock_radio = self._run(
            view_fn, [en_course, ok]
        )
        assert tpl == template
        assert ctx['analysis_locked'] is True
        assert ctx['no_data'] is True
        assert ctx['race_in_progress'] is True
        assert ctx['current_analysis'] == analysis_key
        assert ctx['course'] is None

        # Aucun calcul d'analyse ne doit avoir lieu
        mock_rank.assert_not_called()
        mock_org.assert_not_called()
        mock_ctrl.assert_not_called()
        mock_radio.assert_not_called()

    @pytest.mark.parametrize('view_fn,template,analysis_key', ANALYSIS_VIEWS)
    def test_bloque_si_coureur_partie_sans_statut_circuit(self, view_fn, template, analysis_key):
        """Même comportement en mode circuit (hash)."""
        en_course = make_competitor(1, st=ST_PASSE, stat=STAT_UNKNOWN)
        ok        = make_competitor(2, st=ST_PASSE, stat=STAT_OK, rt=5000)
        course    = {'hash': 'abc12345', 'controls_seq': [], 'classes': [], 'display_name': 'H21'}
        tpl, ctx, mock_rank, mock_org, mock_ctrl, mock_radio = self._run(
            view_fn, [en_course, ok], course=course
        )
        assert tpl == template
        assert ctx['analysis_locked'] is True
        assert ctx['course'] is course
        mock_rank.assert_not_called()
        mock_org.assert_not_called()
        mock_ctrl.assert_not_called()
        mock_radio.assert_not_called()


# ─── Vue non verrouillée : cas autorisés ─────────────────────────────────────

class TestAnalysisNotLocked:
    """Les coureurs jamais partis / au départ futur / aux statuts définitifs
    ne bloquent pas l'analyse (vérifié sur grouping_analysis, représentative)."""

    def _run_grouping(self, competitors):
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10; cls.name = 'H21'
        with patch('results.views._load_class_context',
                   return_value=(competition, cls, competitors, None)), \
             patch('results.views.get_org_map',   return_value={}), \
             patch('results.views.get_class_controls', return_value=([], {})), \
             patch('results.views.get_radio_map', return_value={}), \
             patch('results.views.render') as mock_render:
            views.grouping_analysis(_get(), cid=1, class_id=10)
            _, _, ctx = mock_render.call_args[0]
        return ctx

    def test_coureur_jamais_parti_ne_bloque_pas(self):
        """st = 0 (jamais parti, sans statut) → analyse calculée."""
        jamais_parti = make_competitor(1, st=0, stat=STAT_UNKNOWN)
        ok           = make_competitor(2, st=ST_PASSE, stat=STAT_OK, rt=5000)
        ctx = self._run_grouping([jamais_parti, ok])
        assert ctx.get('analysis_locked') is not True
        assert ctx['no_data'] is False
        assert ctx['n_runners'] == 1

    def test_depart_futur_ne_bloque_pas(self):
        """st dans le futur (départ pas encore passé) → analyse calculée."""
        futur = make_competitor(1, st=ST_FUTUR, stat=STAT_UNKNOWN)
        ok    = make_competitor(2, st=ST_PASSE, stat=STAT_OK, rt=5000)
        ctx = self._run_grouping([futur, ok])
        assert ctx.get('analysis_locked') is not True
        assert ctx['no_data'] is False
        assert ctx['n_runners'] == 2

    def test_statut_definitif_ne_bloque_pas(self):
        """Statuts définitifs (OK + DNF) → analyse calculée."""
        dnf = make_competitor(1, st=ST_PASSE, stat=STAT_DNF)
        ok  = make_competitor(2, st=ST_PASSE, stat=STAT_OK, rt=5000)
        ctx = self._run_grouping([dnf, ok])
        assert ctx.get('analysis_locked') is not True
        assert ctx['no_data'] is False
        assert ctx['n_runners'] == 2


# ─── Rendu des templates verrouillés ────────────────────────────────────────

class TestLockedTemplates:
    """Les 7 pages d'analyse affichent le message de blocage (rendu réel).

    Chaque template a sa propre structure de bloc `content` (analysis_base,
    duel, grouping_index, regularity, recapitulatif) : on vérifie que le
    message dédié apparaît bien dans le HTML rendu.
    """

    @pytest.mark.parametrize('template', [
        'results/superman.html',
        'results/performance.html',
        'results/regularity.html',
        'results/grouping.html',
        'results/grouping_index.html',
        'results/duel.html',
        'results/recapitulatif.html',
    ])
    def test_message_blocage_affiche(self, template):
        from types import SimpleNamespace
        from django.template.loader import render_to_string
        ctx = {
            'competition':      SimpleNamespace(cid=1, name='Test', date=None),
            'cls':              SimpleNamespace(id=10, name='H21', cid=1),
            'course':           None,
            'current_analysis': 'x',
            'analysis_locked':  True,
            'no_data':          True,
            'race_in_progress': True,
        }
        html = render_to_string(template, ctx)
        assert 'Analyse indisponible pendant la course' in html
        assert 'Analyse bloquée' not in html

    def test_message_pas_de_blocage_sans_verrou(self):
        """Sans verrou (et sans données), le message de blocage n'apparaît pas."""
        from types import SimpleNamespace
        from django.template.loader import render_to_string
        ctx = {
            'competition':      SimpleNamespace(cid=1, name='Test', date=None),
            'cls':              SimpleNamespace(id=10, name='H21', cid=1),
            'course':           None,
            'current_analysis': 'regularity',
            'analysis_locked':  False,
            'no_data':          True,
        }
        html = render_to_string('results/regularity.html', ctx)
        assert 'Analyse indisponible pendant la course' not in html
        assert 'minimum 2 requis' in html


# ─── Export CSV du récapitulatif ─────────────────────────────────────────────

class TestRecapitulatifCsv:

    def _setup(self):
        competition = MagicMock(); competition.cid = 1
        cls         = MagicMock(); cls.id = 10; cls.name = 'H21'
        return competition, cls

    def test_csv_409_course_en_cours(self):
        """Course en cours → pas d'export CSV (409)."""
        competition, cls = self._setup()
        en_course = make_competitor(1, st=ST_PASSE, stat=STAT_UNKNOWN)
        with patch('results.views._load_class_context',
                   return_value=(competition, cls, [en_course], None)), \
             patch('results.views.Mopteam') as MockTeam, \
             patch('results.views._load_recapitulatif_data') as mock_data:
            MockTeam.objects.filter.return_value.exists.return_value = False
            resp = views.recapitulatif_csv(_get(), cid=1, class_id=10)
        assert resp.status_code == 409
        mock_data.assert_not_called()

    def test_csv_200_course_finie(self):
        """Course terminée (statuts définitifs) → export CSV normal."""
        competition, cls = self._setup()
        ok = make_competitor(1, st=ST_PASSE, stat=STAT_OK, rt=5000)
        with patch('results.views._load_class_context',
                   return_value=(competition, cls, [ok], None)), \
             patch('results.views.Mopteam') as MockTeam, \
             patch('results.views._load_recapitulatif_data') as mock_data:
            MockTeam.objects.filter.return_value.exists.return_value = False
            mock_data.return_value = tuple(MagicMock() for _ in range(9))
            resp = views.recapitulatif_csv(_get(), cid=1, class_id=10)
        assert resp.status_code == 200
        assert 'text/csv' in resp['Content-Type']
