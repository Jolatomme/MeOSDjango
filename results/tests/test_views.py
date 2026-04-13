"""
Tests d'intégration pour les vues — DB entièrement mockée.

On vérifie que chaque vue :
  - retourne le bon code HTTP
  - utilise le bon template
  - passe les bonnes clés de contexte
"""

from unittest.mock import patch, MagicMock
import pytest
import json
from django.test import RequestFactory
from django.http import Http404

from results.models import (
    STAT_OK, STAT_MP, STAT_DNF, STAT_DNS, STAT_NP, STAT_CANCEL,
    STAT_OCC, STAT_NT, STAT_OT, STAT_DQ,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_competition(cid=1):
    c = MagicMock()
    c.cid  = cid
    c.name = 'Compétition Test'
    return c


def make_cls(cid=1, class_id=10, name='H21', ord_=10):
    c = MagicMock()
    c.cid  = cid
    c.id   = class_id
    c.name = name
    c.ord  = ord_
    return c


def make_competitor(id=1, rt=6000, stat=STAT_OK, org=1, cls=10, name=None):
    c = MagicMock()
    c.id    = id
    c.rt    = rt
    c.stat  = stat
    c.org   = org
    c.cls   = cls
    c.name  = name if name is not None else f'Coureur {id}'
    c.is_ok = (stat == STAT_OK and rt > 0)
    c.status_label = 'OK'
    return c


def make_nf(id, stat, name, rt=-1):
    """Construit un non-classé avec le statut et le nom donnés."""
    c = MagicMock()
    c.id           = id
    c.stat         = stat
    c.name         = name
    c.rt           = rt
    c.is_ok        = False
    c.status_label = 'non-classé'
    return c


def rf_get(url='/'):
    """Retourne un GET request via RequestFactory."""
    return RequestFactory().get(url)


# ─── Tests _sort_non_finishers ────────────────────────────────────────────────

class TestSortNonFinishers:
    """Tests unitaires du helper _sort_non_finishers (sans DB)."""

    def _call(self, competitors):
        from results.views import _sort_non_finishers
        return _sort_non_finishers(competitors)

    def test_pm_apres_nc(self):
        nc = make_nf(1, STAT_OCC, 'Alice')
        pm = make_nf(2, STAT_MP, 'Bob')
        result = self._call([pm, nc])
        assert result[0].id == nc.id
        assert result[1].id == pm.id

    def test_abandon_apres_pm(self):
        pm  = make_nf(1, STAT_MP,  'Alice')
        dnf = make_nf(2, STAT_DNF, 'Bob')
        result = self._call([dnf, pm])
        assert result[0].id == pm.id
        assert result[1].id == dnf.id

    def test_dns_apres_abandon(self):
        dnf = make_nf(1, STAT_DNF, 'Alice')
        dns = make_nf(2, STAT_DNS, 'Bob')
        result = self._call([dns, dnf])
        assert result[0].id == dnf.id
        assert result[1].id == dns.id

    def test_np_groupe_avec_dns(self):
        dns = make_nf(1, STAT_DNS, 'Alice')
        np_ = make_nf(2, STAT_NP,  'Bob')
        result = self._call([np_, dns])
        noms = [r.name for r in result]
        assert noms == ['Alice', 'Bob']

    def test_cancel_groupe_avec_dns(self):
        dns    = make_nf(1, STAT_DNS,    'Zara')
        cancel = make_nf(2, STAT_CANCEL, 'Alice')
        result = self._call([dns, cancel])
        assert result[0].name == 'Alice'
        assert result[1].name == 'Zara'

    def test_ordre_complet_nc_pm_dnf_dns(self):
        dns = make_nf(1, STAT_DNS, 'DNS')
        dnf = make_nf(2, STAT_DNF, 'DNF')
        pm  = make_nf(3, STAT_MP,  'PM')
        nc  = make_nf(4, STAT_OCC, 'NC')
        result = self._call([dns, dnf, pm, nc])
        assert [r.id for r in result] == [4, 3, 2, 1]

    def test_alpha_dans_groupe_pm(self):
        pm1 = make_nf(1, STAT_MP, 'Zara')
        pm2 = make_nf(2, STAT_MP, 'Alice')
        pm3 = make_nf(3, STAT_MP, 'Martin')
        result = self._call([pm1, pm2, pm3])
        noms = [r.name for r in result]
        assert noms == ['Alice', 'Martin', 'Zara']

    def test_alpha_dans_groupe_dnf(self):
        d1 = make_nf(1, STAT_DNF, 'Zorro')
        d2 = make_nf(2, STAT_DNF, 'Alice')
        result = self._call([d1, d2])
        assert result[0].name == 'Alice'

    def test_alpha_dans_groupe_nc(self):
        n1 = make_nf(1, STAT_OCC, 'Zara')
        n2 = make_nf(2, STAT_OCC, 'Alice')
        n3 = make_nf(3, STAT_NT,  'Martin')
        result = self._call([n1, n2, n3])
        noms = [r.name for r in result]
        assert noms == ['Alice', 'Martin', 'Zara']

    def test_alpha_insensible_a_la_casse(self):
        d1 = make_nf(1, STAT_DNF, 'alice')
        d2 = make_nf(2, STAT_DNF, 'Bob')
        d3 = make_nf(3, STAT_DNF, 'CHARLIE')
        result = self._call([d3, d2, d1])
        noms = [r.name for r in result]
        assert noms == ['alice', 'Bob', 'CHARLIE']

    def test_liste_vide(self):
        assert self._call([]) == []

    def test_un_seul_element(self):
        c = make_nf(1, STAT_DNF, 'Alice')
        assert self._call([c]) == [c]

    def test_ne_modifie_pas_liste_originale(self):
        original = [make_nf(1, STAT_DNS, 'B'), make_nf(2, STAT_MP, 'A')]
        ids_avant = [c.id for c in original]
        self._call(original)
        assert [c.id for c in original] == ids_avant

    def test_statut_inconnu_en_dernier(self):
        dnf     = make_nf(1, STAT_DNF, 'Alice')
        inconnu = make_nf(2, 99,       'Zara')
        result = self._call([inconnu, dnf])
        assert result[0].id == dnf.id
        assert result[1].id == inconnu.id

    def test_nt_groupe_nc(self):
        nt = make_nf(1, STAT_NT, 'Alice')
        pm = make_nf(2, STAT_MP, 'Bob')
        result = self._call([pm, nt])
        assert result[0].id == nt.id

    def test_ot_groupe_nc(self):
        ot = make_nf(1, STAT_OT, 'Alice')
        pm = make_nf(2, STAT_MP, 'Bob')
        result = self._call([pm, ot])
        assert result[0].id == ot.id

    def test_dq_groupe_nc(self):
        dq = make_nf(1, STAT_DQ, 'Alice')
        pm = make_nf(2, STAT_MP, 'Bob')
        result = self._call([pm, dq])
        assert result[0].id == dq.id

    def test_mixte_meme_groupe_alpha_pas_id(self):
        pm_z = make_nf(10, STAT_MP, 'Zara')
        pm_a = make_nf(99, STAT_MP, 'Alice')
        result = self._call([pm_z, pm_a])
        assert result[0].name == 'Alice'
        assert result[1].name == 'Zara'


# ─── Tests _load_class_context ───────────────────────────────────────────────

class TestLoadClassContext:

    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_object_or_404')
    def test_retourne_competition_cls_competitors(self, mock_get404, MockCompetitor):
        competition = make_competition()
        cls         = make_cls()
        mock_get404.side_effect = [competition, cls]
        c1 = make_competitor(1)
        c2 = make_competitor(2)
        MockCompetitor.objects.filter.return_value = [c1, c2]

        from results.views import _load_class_context
        comp_out, cls_out, competitors = _load_class_context(cid=1, class_id=10)

        assert comp_out is competition
        assert cls_out is cls
        assert len(competitors) == 2

    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_object_or_404')
    def test_appelle_get_object_or_404_deux_fois(self, mock_get404, MockCompetitor):
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockCompetitor.objects.filter.return_value = []

        from results.views import _load_class_context
        _load_class_context(cid=5, class_id=20)

        assert mock_get404.call_count == 2

    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_object_or_404')
    def test_filtre_concurrents_par_cid_et_class_id(self, mock_get404, MockCompetitor):
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockCompetitor.objects.filter.return_value = []

        from results.views import _load_class_context
        _load_class_context(cid=3, class_id=15)

        MockCompetitor.objects.filter.assert_called_once_with(cid=3, cls=15)

    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_object_or_404')
    def test_retourne_liste_et_non_queryset(self, mock_get404, MockCompetitor):
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockCompetitor.objects.filter.return_value = [make_competitor(1)]

        from results.views import _load_class_context
        _, _, competitors = _load_class_context(cid=1, class_id=10)

        assert isinstance(competitors, list)

    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_object_or_404', side_effect=Http404)
    def test_leve_404_si_objet_absent(self, mock_get404, MockCompetitor):
        from django.http import Http404 as Http404Ex
        from results.views import _load_class_context
        import pytest
        with pytest.raises(Http404Ex):
            _load_class_context(cid=999, class_id=10)


# ─── Tests _get_adjacent_classes ─────────────────────────────────────────────

class TestGetAdjacentClasses:

    def _mk_cls(self, class_id, name, ord_=10):
        c = MagicMock()
        c.id   = class_id
        c.name = name
        c.ord  = ord_
        return c

    def _call(self, mock_qs, cid, class_id):
        from results.views import _get_adjacent_classes
        with patch('results.views.Mopclass') as MockMopclass:
            MockMopclass.objects.filter.return_value.order_by.return_value = mock_qs
            return _get_adjacent_classes(cid, class_id)

    def test_classe_unique_aucun_voisin(self):
        cls_list = [self._mk_cls(10, 'H21')]
        prev, nxt = self._call(cls_list, cid=1, class_id=10)
        assert prev is None
        assert nxt  is None

    def test_premiere_classe_pas_de_precedent(self):
        cls_list = [self._mk_cls(10, 'H21'), self._mk_cls(20, 'D21'), self._mk_cls(30, 'H35')]
        prev, nxt = self._call(cls_list, cid=1, class_id=10)
        assert prev is None
        assert nxt.id == 20

    def test_derniere_classe_pas_de_suivant(self):
        cls_list = [self._mk_cls(10, 'H21'), self._mk_cls(20, 'D21'), self._mk_cls(30, 'H35')]
        prev, nxt = self._call(cls_list, cid=1, class_id=30)
        assert prev.id == 20
        assert nxt is None

    def test_classe_du_milieu(self):
        cls_list = [self._mk_cls(10, 'H21'), self._mk_cls(20, 'D21'), self._mk_cls(30, 'H35')]
        prev, nxt = self._call(cls_list, cid=1, class_id=20)
        assert prev.id == 10
        assert nxt.id  == 30

    def test_classe_inexistante_retourne_double_none(self):
        cls_list = [self._mk_cls(10, 'H21')]
        prev, nxt = self._call(cls_list, cid=1, class_id=999)
        assert prev is None
        assert nxt  is None

    def test_noms_corrects(self):
        cls_list = [self._mk_cls(10, 'H21'), self._mk_cls(20, 'D21'), self._mk_cls(30, 'H35')]
        prev, nxt = self._call(cls_list, cid=1, class_id=20)
        assert prev.name == 'H21'
        assert nxt.name  == 'H35'

    def test_filtre_par_cid(self):
        from results.views import _get_adjacent_classes
        with patch('results.views.Mopclass') as MockMopclass:
            MockMopclass.objects.filter.return_value.order_by.return_value = []
            _get_adjacent_classes(cid=42, class_id=10)
            MockMopclass.objects.filter.assert_called_once_with(cid=42)


# ─── Tests home ───────────────────────────────────────────────────────────────

class TestHomeView:

    @patch('results.views.Mopcompetition')
    @patch('results.views.render')
    def test_passe_competitions_au_contexte(self, mock_render, MockComp):
        comps = [make_competition(1), make_competition(2)]
        MockComp.objects.all.return_value = comps

        from results.views import home
        request = rf_get()
        home(request)

        _, template, context = mock_render.call_args[0]
        assert template == 'results/home.html'
        assert context['competitions'] == comps


# ─── Tests class_results ──────────────────────────────────────────────────────

class TestClassResultsView:

    def _patch_all(self, mock_mopteam, mock_mopcomp, mock_mopclass,
                   mock_mopcompetitor, mock_get404):
        mock_mopteam.objects.filter.return_value.exists.return_value = False

        competition = make_competition()
        cls         = make_cls()
        mock_get404.side_effect = [competition, cls]

        c1 = make_competitor(1, rt=5000)
        c2 = make_competitor(2, rt=6000)
        mock_mopcompetitor.objects.filter.return_value = [c1, c2]

    @patch('results.views._get_adjacent_classes', return_value=(None, None))
    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.compute_splits',     return_value=[])
    @patch('results.views.mark_best_splits')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopclass')
    @patch('results.views.Mopcompetition')
    @patch('results.views.Mopteam')
    def test_contexte_contient_resultats(
        self, MockTeam, MockComp, MockClass, MockCompetitor, mock_get404,
        mock_render, mock_mark, mock_splits, mock_radio, mock_controls, mock_org,
        mock_adj,
    ):
        self._patch_all(MockTeam, MockComp, MockClass, MockCompetitor, mock_get404)

        from results.views import class_results
        request = rf_get()
        class_results(request, cid=1, class_id=10)

        _, template, context = mock_render.call_args[0]
        assert template == 'results/class_results.html'
        assert 'results' in context
        assert 'leader_time' in context
        assert 'has_splits' in context

    @patch('results.views.redirect')
    @patch('results.views.Mopteam')
    def test_redirige_si_relais(self, MockTeam, mock_redirect):
        MockTeam.objects.filter.return_value.exists.return_value = True

        from results.views import class_results
        request = rf_get()
        class_results(request, cid=1, class_id=10)

        mock_redirect.assert_called_once_with(
            'results:relay_results', cid=1, class_id=10
        )

    @patch('results.views._get_adjacent_classes', return_value=(None, None))
    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.compute_splits',     return_value=[])
    @patch('results.views.mark_best_splits')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteam')
    def test_prev_cls_et_next_cls_dans_contexte(
        self, MockTeam, MockCompetitor, mock_get404, mock_render,
        mock_mark, mock_splits, mock_radio, mock_controls, mock_org,
        mock_adj,
    ):
        MockTeam.objects.filter.return_value.exists.return_value = False
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockCompetitor.objects.filter.return_value = [make_competitor()]

        from results.views import class_results
        class_results(rf_get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        assert 'prev_cls' in context
        assert 'next_cls' in context

    @patch('results.views._get_adjacent_classes', return_value=(make_cls(class_id=5, name='H20'), make_cls(class_id=15, name='D21')))
    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.compute_splits',     return_value=[])
    @patch('results.views.mark_best_splits')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteam')
    def test_prev_cls_et_next_cls_transmis_depuis_helper(
        self, MockTeam, MockCompetitor, mock_get404, mock_render,
        mock_mark, mock_splits, mock_radio, mock_controls, mock_org,
        mock_adj,
    ):
        MockTeam.objects.filter.return_value.exists.return_value = False
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockCompetitor.objects.filter.return_value = [make_competitor()]

        from results.views import class_results
        class_results(rf_get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        assert context['prev_cls'].id   == 5
        assert context['next_cls'].id   == 15
        assert context['prev_cls'].name == 'H20'
        assert context['next_cls'].name == 'D21'


# ─── Tests class_results — ordre des non-classés ──────────────────────────────

class TestClassResultsNonFinisherOrdering:

    def _run(self, competitors):
        comp = make_competition()
        cls  = make_cls()
        with patch('results.views.Mopteam') as MockTeam, \
             patch('results.views.Mopcompetitor') as MockComp, \
             patch('results.views.get_object_or_404', side_effect=[comp, cls]), \
             patch('results.views._get_adjacent_classes', return_value=(None, None)), \
             patch('results.views.get_org_map', return_value={}), \
             patch('results.views.get_class_controls', return_value=([], {})), \
             patch('results.views.get_radio_map', return_value={}), \
             patch('results.views.compute_splits', return_value=[]), \
             patch('results.views.mark_best_splits'), \
             patch('results.views.rank_splits'), \
             patch('results.views.render') as mock_render:
            MockTeam.objects.filter.return_value.exists.return_value = False
            MockComp.objects.filter.return_value = competitors
            from results.views import class_results
            class_results(rf_get(), cid=1, class_id=10)
            _, _, ctx = mock_render.call_args[0]
            return ctx

    def test_classés_en_premier(self):
        ok1 = make_competitor(1, rt=5000, stat=STAT_OK, name='Alice')
        ok2 = make_competitor(2, rt=6000, stat=STAT_OK, name='Bob')
        dnf = make_nf(3, STAT_DNF, 'Charlie')
        ctx = self._run([dnf, ok1, ok2])
        noms = [r.name for r in ctx['results']]
        assert noms.index('Alice') < noms.index('Charlie')
        assert noms.index('Bob')   < noms.index('Charlie')

    def test_nc_avant_pm(self):
        pm = make_nf(1, STAT_MP,  'Alice PM')
        nc = make_nf(2, STAT_OCC, 'Bob NC')
        ctx = self._run([pm, nc])
        noms = [r.name for r in ctx['results']]
        assert noms.index('Bob NC') < noms.index('Alice PM')

    def test_pm_avant_abandon(self):
        dnf = make_nf(1, STAT_DNF, 'Alice DNF')
        pm  = make_nf(2, STAT_MP,  'Bob PM')
        ctx = self._run([dnf, pm])
        noms = [r.name for r in ctx['results']]
        assert noms.index('Bob PM') < noms.index('Alice DNF')

    def test_abandon_avant_dns(self):
        dns = make_nf(1, STAT_DNS, 'Alice DNS')
        dnf = make_nf(2, STAT_DNF, 'Bob DNF')
        ctx = self._run([dns, dnf])
        noms = [r.name for r in ctx['results']]
        assert noms.index('Bob DNF') < noms.index('Alice DNS')

    def test_ordre_complet_quatre_groupes(self):
        dns = make_nf(1, STAT_DNS, 'DNS')
        dnf = make_nf(2, STAT_DNF, 'DNF')
        pm  = make_nf(3, STAT_MP,  'PM')
        nc  = make_nf(4, STAT_OCC, 'NC')
        ok  = make_competitor(5, rt=5000, name='OK')
        ctx = self._run([dns, dnf, pm, nc, ok])
        noms = [r.name for r in ctx['results']]
        idx  = {n: noms.index(n) for n in ['OK', 'NC', 'PM', 'DNF', 'DNS']}
        assert idx['OK']  < idx['NC']
        assert idx['NC']  < idx['PM']
        assert idx['PM']  < idx['DNF']
        assert idx['DNF'] < idx['DNS']

    def test_alpha_dans_groupe_pm(self):
        pm_z = make_nf(1, STAT_MP, 'Zara')
        pm_a = make_nf(2, STAT_MP, 'Alice')
        pm_m = make_nf(3, STAT_MP, 'Martin')
        ctx = self._run([pm_z, pm_a, pm_m])
        noms = [r.name for r in ctx['results']]
        assert noms == ['Alice', 'Martin', 'Zara']

    def test_seulement_non_classes(self):
        dnf = make_nf(1, STAT_DNF, 'Bob')
        dns = make_nf(2, STAT_DNS, 'Alice')
        pm  = make_nf(3, STAT_MP,  'Charlie')
        ctx = self._run([dnf, dns, pm])
        noms = [r.name for r in ctx['results']]
        assert noms == ['Charlie', 'Bob', 'Alice']

    def test_n_results_correct(self):
        ok  = make_competitor(1, rt=5000, name='OK')
        dnf = make_nf(2, STAT_DNF, 'DNF')
        dns = make_nf(3, STAT_DNS, 'DNS')
        ctx = self._run([ok, dnf, dns])
        assert len(ctx['results']) == 3


# ─── Tests competitor_detail ──────────────────────────────────────────────────

class TestCompetitorDetailView:

    @patch('results.views.compute_splits', return_value=[])
    @patch('results.views.get_radio_map',  return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.Moporganization')
    @patch('results.views.Mopclass')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_contexte(self, mock_get404, mock_render, MockClass,
                      MockOrg, mock_ctrl, mock_radio, mock_splits):
        competition = make_competition()
        competitor  = make_competitor()
        mock_get404.side_effect = [competition, competitor]
        MockOrg.objects.filter.return_value.first.return_value  = MagicMock(name='COLE')
        MockClass.objects.filter.return_value.first.return_value = MagicMock(name='H21')

        from results.views import competitor_detail
        competitor_detail(rf_get(), cid=1, competitor_id=1)

        _, template, context = mock_render.call_args[0]
        assert template == 'results/competitor_detail.html'
        assert 'competitor' in context
        assert 'splits' in context
        assert 'total_time' in context


# ─── Tests api_class_results ──────────────────────────────────────────────────

class TestApiClassResults:

    @patch('results.views.get_org_map', return_value={1: 'COLE'})
    @patch('results.views.Mopcompetitor')
    def test_retourne_json(self, MockCompetitor, mock_org):
        c1 = make_competitor(1, rt=5000)
        c2 = make_competitor(2, rt=6000)
        MockCompetitor.objects.filter.return_value = [c1, c2]

        from results.views import api_class_results
        response = api_class_results(rf_get(), cid=1, class_id=10)

        import json
        data = json.loads(response.content)
        assert 'results' in data
        assert data['results'][0]['rank'] == 1
        assert data['results'][0]['time'] == '08:20'
        assert data['results'][1]['behind'].startswith('+')

    @patch('results.views.get_org_map', return_value={})
    @patch('results.views.Mopcompetitor')
    def test_liste_vide(self, MockCompetitor, mock_org):
        MockCompetitor.objects.filter.return_value = []
        from results.views import api_class_results
        import json
        response = api_class_results(rf_get(), cid=1, class_id=10)
        data = json.loads(response.content)
        assert data['results'] == []


# ─── Tests superman_analysis ──────────────────────────────────────────────────

class TestSupermanAnalysis:

    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_no_data_si_aucun_classe(self, MockCompetitor, mock_get404, mock_render):
        competition = make_competition()
        cls         = make_cls()
        mock_get404.side_effect = [competition, cls]
        dnf = make_competitor(1, rt=-1, stat=4)
        dnf.is_ok = False
        MockCompetitor.objects.filter.return_value = [dnf]

        from results.views import superman_analysis
        superman_analysis(rf_get(), cid=1, class_id=10)

        _, template, context = mock_render.call_args[0]
        assert template == 'results/superman.html'
        assert context['no_data'] is True

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_contexte_avec_classement(
        self, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        competition = make_competition()
        cls         = make_cls()
        mock_get404.side_effect = [competition, cls]

        c1 = make_competitor(1, rt=6000)
        c2 = make_competitor(2, rt=7200)
        MockCompetitor.objects.filter.return_value = [c1, c2]

        from results.views import superman_analysis
        superman_analysis(rf_get(), cid=1, class_id=10)

        _, template, context = mock_render.call_args[0]
        assert context['no_data'] is False
        assert 'series' in context
        assert 'superman_total' in context
        assert len(context['series']) == 2


# ─── Tests superman — invariants de couleur tableau/graphique ──────────────────

class TestSupermanColorInvariants:

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_series_json_contient_champs_table(
        self, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        competition = make_competition(); cls = make_cls()
        mock_get404.side_effect = [competition, cls]
        c = make_competitor(1, rt=6000)
        MockCompetitor.objects.filter.return_value = [c]

        from results.views import superman_analysis
        superman_analysis(rf_get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        series = json.loads(context['series_json'])
        assert len(series) == 1
        s = series[0]
        for field in ('id', 'name', 'org', 'rank', 'total', 'loss'):
            assert field in s

    @patch('results.views.get_org_map',        return_value={1: 'Club A', 2: 'Club B'})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_series_ordre_par_classement(
        self, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        competition = make_competition(); cls = make_cls()
        mock_get404.side_effect = [competition, cls]

        alice = make_competitor(1, rt=8000, name='Alice')
        bob   = make_competitor(2, rt=5000, name='Bob')
        alice.org = 1; bob.org = 2
        MockCompetitor.objects.filter.return_value = [alice, bob]

        from results.views import superman_analysis
        superman_analysis(rf_get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        series = json.loads(context['series_json'])

        assert series[0]['name'] == 'Bob'
        assert series[1]['name'] == 'Alice'
        assert series[0]['rank'] == 1
        assert series[1]['rank'] == 2


class TestClassResultsRankSplits:

    @patch('results.views._get_adjacent_classes', return_value=(None, None))
    @patch('results.views.rank_splits')
    @patch('results.views.mark_best_splits')
    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=(
        [{'ctrl_id': 31, 'ctrl_name': 'P31'}], {}
    ))
    @patch('results.views.get_radio_map',      return_value={1: {31: 1200}, 2: {31: 1100}})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteam')
    def test_rank_splits_appele(
        self, MockTeam, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org, mock_mark, mock_rank, mock_adj,
    ):
        MockTeam.objects.filter.return_value.exists.return_value = False
        competition = make_competition(); cls = make_cls()
        mock_get404.side_effect = [competition, cls]
        c1 = make_competitor(1, rt=5000); c2 = make_competitor(2, rt=6000)
        MockCompetitor.objects.filter.return_value = [c1, c2]

        from results.views import class_results
        class_results(rf_get(), cid=1, class_id=10)

        assert mock_rank.called


# ─── Tests org_results ───────────────────────────────────────────────────────

class TestOrgResultsView:

    def _make_cls_obj(self, id_, name, ord_=10):
        c = MagicMock()
        c.id   = id_
        c.name = name
        c.ord  = ord_
        return c

    @patch('results.views.Mopclass')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_contexte_de_base(self, mock_get404, mock_render, MockCompetitor, MockClass):
        competition  = make_competition()
        organization = MagicMock(); organization.name = 'COLE'
        mock_get404.side_effect = [competition, organization]

        c1 = make_competitor(1, cls=10); c2 = make_competitor(2, cls=11)
        MockCompetitor.objects.filter.side_effect = [
            [c1, c2],   # org competitors
            [c1],       # all in class 10
            [c2],       # all in class 11
        ]
        MockClass.objects.filter.return_value = []

        from results.views import org_results
        org_results(rf_get(), cid=1, org_id=5)

        _, template, context = mock_render.call_args[0]
        assert template == 'results/org_results.html'
        assert 'organization' in context
        assert 'competitors' in context
        assert 'competition' in context

    @patch('results.views.Mopclass')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_class_obj_attache_aux_coureurs(
        self, mock_get404, mock_render, MockCompetitor, MockClass
    ):
        competition  = make_competition()
        organization = MagicMock()
        mock_get404.side_effect = [competition, organization]

        c = make_competitor(1, cls=10)
        MockCompetitor.objects.filter.side_effect = [
            [c],   # org competitors
            [c],   # all in class 10
        ]
        cls_obj = self._make_cls_obj(10, 'H21')
        MockClass.objects.filter.return_value = [cls_obj]

        from results.views import org_results
        org_results(rf_get(), cid=1, org_id=5)

        assert hasattr(c, 'class_obj')
        assert c.class_obj is cls_obj

    @patch('results.views.Mopclass')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_cat_rank_attribue_aux_coureurs(
        self, mock_get404, mock_render, MockCompetitor, MockClass
    ):
        """cat_rank est le rang dans la catégorie (tous compétiteurs, pas seulement le club)."""
        competition  = make_competition()
        organization = MagicMock()
        mock_get404.side_effect = [competition, organization]

        # Alice (org=5) est 2e dans sa catégorie derrière Bob (org=9)
        alice = make_competitor(1, rt=6000, stat=STAT_OK, cls=10, name='Alice')
        bob   = make_competitor(2, rt=5000, stat=STAT_OK, cls=10, name='Bob', org=9)
        MockCompetitor.objects.filter.side_effect = [
            [alice],        # org competitors (seulement Alice du club 5)
            [alice, bob],   # ALL competitors in class 10
        ]
        MockClass.objects.filter.return_value = []

        from results.views import org_results
        org_results(rf_get(), cid=1, org_id=5)

        _, _, context = mock_render.call_args[0]
        competitors_out = context['competitors']
        alice_out = next(c for c in competitors_out if c.name == 'Alice')
        assert alice_out.cat_rank == 2, "Alice doit être 2e (Bob est plus rapide)"

    @patch('results.views.Mopclass')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_classés_triés_par_rang_croissant(
        self, mock_get404, mock_render, MockCompetitor, MockClass
    ):
        """Les classés apparaissent du meilleur rang au moins bon."""
        competition  = make_competition()
        organization = MagicMock()
        mock_get404.side_effect = [competition, organization]

        # Trois coureurs du club, dans des classes différentes
        a = make_competitor(1, rt=5000, stat=STAT_OK, cls=10, name='A')
        b = make_competitor(2, rt=6000, stat=STAT_OK, cls=10, name='B')
        c = make_competitor(3, rt=4000, stat=STAT_OK, cls=10, name='C')
        MockCompetitor.objects.filter.side_effect = [
            [a, b, c],        # org competitors
            [a, b, c],        # all in class 10
        ]
        MockClass.objects.filter.return_value = []

        from results.views import org_results
        org_results(rf_get(), cid=1, org_id=5)

        _, _, context = mock_render.call_args[0]
        noms = [x.name for x in context['competitors']]
        # C (rt=4000) → rang 1, A (rt=5000) → rang 2, B (rt=6000) → rang 3
        assert noms == ['C', 'A', 'B']

    @patch('results.views.Mopclass')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_exaequo_trié_par_ord_catégorie(
        self, mock_get404, mock_render, MockCompetitor, MockClass
    ):
        """Pour des rangs identiques (ex-æquo), on trie par ord de catégorie."""
        competition  = make_competition()
        organization = MagicMock()
        mock_get404.side_effect = [competition, organization]

        # Deux coureurs du club : même rang 1 dans leurs catégories respectives
        # cat H21 (ord=20) et cat D21 (ord=10) — D21 doit passer en premier
        alice = make_competitor(1, rt=5000, stat=STAT_OK, cls=20, name='Alice')
        bob   = make_competitor(2, rt=4000, stat=STAT_OK, cls=10, name='Bob')
        cls_h21 = self._make_cls_obj(20, 'H21', ord_=20)
        cls_d21 = self._make_cls_obj(10, 'D21', ord_=10)

        MockCompetitor.objects.filter.side_effect = [
            [alice, bob],  # org competitors
            [alice],       # all in class 20 (H21)
            [bob],         # all in class 10 (D21)
        ]
        MockClass.objects.filter.return_value = [cls_d21, cls_h21]

        from results.views import org_results
        org_results(rf_get(), cid=1, org_id=5)

        _, _, context = mock_render.call_args[0]
        noms = [x.name for x in context['competitors']]
        # Les deux sont rang 1 chacun dans leur cat.
        # D21 (ord=10) avant H21 (ord=20)
        assert noms.index('Bob') < noms.index('Alice'), \
            "Bob (D21, ord=10) doit précéder Alice (H21, ord=20) pour les ex-æquo"

    @patch('results.views.Mopclass')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_classés_avant_non_classés(
        self, mock_get404, mock_render, MockCompetitor, MockClass
    ):
        """Les classés (is_ok=True) apparaissent toujours avant les non-classés."""
        competition  = make_competition()
        organization = MagicMock()
        mock_get404.side_effect = [competition, organization]

        ok  = make_competitor(1, rt=5000, stat=STAT_OK, cls=10, name='Alice OK')
        dnf = make_nf(2, STAT_DNF, 'Bob DNF')
        dnf.cls = 10
        MockCompetitor.objects.filter.side_effect = [
            [ok, dnf],   # org competitors
            [ok],        # all in class 10 (seul ok est is_ok)
        ]
        MockClass.objects.filter.return_value = []

        from results.views import org_results
        org_results(rf_get(), cid=1, org_id=5)

        _, _, context = mock_render.call_args[0]
        noms = [x.name for x in context['competitors']]
        assert noms.index('Alice OK') < noms.index('Bob DNF')

    @patch('results.views.Mopclass')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_non_classés_triés_nc_pm_dnf_dns(
        self, mock_get404, mock_render, MockCompetitor, MockClass
    ):
        """Les non-classés sont triés NC → PM → Abandon → Non-partants."""
        competition  = make_competition()
        organization = MagicMock()
        mock_get404.side_effect = [competition, organization]

        dns = make_nf(1, STAT_DNS, 'DNS')
        dnf = make_nf(2, STAT_DNF, 'DNF')
        pm  = make_nf(3, STAT_MP,  'PM')
        nc  = make_nf(4, STAT_OCC, 'NC')
        for c in [dns, dnf, pm, nc]:
            c.cls = 10

        MockCompetitor.objects.filter.side_effect = [
            [dns, dnf, pm, nc],  # org competitors (tous non-classés)
            [],                  # no finishers in class 10
        ]
        MockClass.objects.filter.return_value = []

        from results.views import org_results
        org_results(rf_get(), cid=1, org_id=5)

        _, _, context = mock_render.call_args[0]
        noms = [x.name for x in context['competitors']]
        assert noms == ['NC', 'PM', 'DNF', 'DNS']

    @patch('results.views.Mopclass')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_non_classés_alpha_dans_chaque_groupe(
        self, mock_get404, mock_render, MockCompetitor, MockClass
    ):
        """Dans chaque groupe de non-classés, le tri est alphabétique."""
        competition  = make_competition()
        organization = MagicMock()
        mock_get404.side_effect = [competition, organization]

        dnf1 = make_nf(1, STAT_DNF, 'Zara')
        dnf2 = make_nf(2, STAT_DNF, 'Alice')
        dnf3 = make_nf(3, STAT_DNF, 'Martin')
        for c in [dnf1, dnf2, dnf3]:
            c.cls = 10

        MockCompetitor.objects.filter.side_effect = [
            [dnf1, dnf2, dnf3],  # org competitors
            [],                  # no finishers
        ]
        MockClass.objects.filter.return_value = []

        from results.views import org_results
        org_results(rf_get(), cid=1, org_id=5)

        _, _, context = mock_render.call_args[0]
        noms = [x.name for x in context['competitors']]
        assert noms == ['Alice', 'Martin', 'Zara']

    @patch('results.views.Mopclass')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_non_classé_cat_rank_est_none(
        self, mock_get404, mock_render, MockCompetitor, MockClass
    ):
        """Un non-classé doit avoir cat_rank = None."""
        competition  = make_competition()
        organization = MagicMock()
        mock_get404.side_effect = [competition, organization]

        dnf = make_nf(1, STAT_DNF, 'Bob')
        dnf.cls = 10
        MockCompetitor.objects.filter.side_effect = [
            [dnf],  # org competitors
            [],     # no finishers in class 10
        ]
        MockClass.objects.filter.return_value = []

        from results.views import org_results
        org_results(rf_get(), cid=1, org_id=5)

        _, _, context = mock_render.call_args[0]
        bob_out = context['competitors'][0]
        assert bob_out.cat_rank is None

    @patch('results.views.Mopclass')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_classement_basé_sur_tous_les_compétiteurs_de_la_catégorie(
        self, mock_get404, mock_render, MockCompetitor, MockClass
    ):
        """Le rang d'un coureur reflète sa position parmi TOUS les coureurs de sa
        catégorie, pas seulement ceux du club."""
        competition  = make_competition()
        organization = MagicMock()
        mock_get404.side_effect = [competition, organization]

        # Alice (club 5) est dans la catégorie 10 avec 4 autres coureurs extérieurs
        alice = make_competitor(1, rt=8000, stat=STAT_OK, cls=10, name='Alice')
        ext1  = make_competitor(10, rt=5000, stat=STAT_OK, cls=10, org=9)
        ext2  = make_competitor(11, rt=6000, stat=STAT_OK, cls=10, org=9)
        ext3  = make_competitor(12, rt=7000, stat=STAT_OK, cls=10, org=9)

        MockCompetitor.objects.filter.side_effect = [
            [alice],                   # org competitors (seulement Alice)
            [alice, ext1, ext2, ext3], # ALL in class 10
        ]
        MockClass.objects.filter.return_value = []

        from results.views import org_results
        org_results(rf_get(), cid=1, org_id=5)

        _, _, context = mock_render.call_args[0]
        alice_out = context['competitors'][0]
        assert alice_out.cat_rank == 4, "Alice (rt=8000) doit être 4e sur 4 coureurs"

    @patch('results.views.Mopclass')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_plusieurs_catégories_chacune_classée_indépendamment(
        self, mock_get404, mock_render, MockCompetitor, MockClass
    ):
        """Deux coureurs du club dans des catégories différentes ont chacun leur rang."""
        competition  = make_competition()
        organization = MagicMock()
        mock_get404.side_effect = [competition, organization]

        # Alice dans H21 (seule → rang 1), Bob dans D21 (3e sur 3)
        alice = make_competitor(1, rt=5000, stat=STAT_OK, cls=10, name='Alice')
        bob   = make_competitor(2, rt=9000, stat=STAT_OK, cls=20, name='Bob')
        ext_d1 = make_competitor(10, rt=6000, stat=STAT_OK, cls=20, org=9)
        ext_d2 = make_competitor(11, rt=7000, stat=STAT_OK, cls=20, org=9)

        MockCompetitor.objects.filter.side_effect = [
            [alice, bob],            # org competitors
            [alice],                 # all in class 10 (H21)
            [bob, ext_d1, ext_d2],   # all in class 20 (D21)
        ]
        MockClass.objects.filter.return_value = []

        from results.views import org_results
        org_results(rf_get(), cid=1, org_id=5)

        _, _, context = mock_render.call_args[0]
        comp_map = {c.name: c for c in context['competitors']}
        assert comp_map['Alice'].cat_rank == 1
        assert comp_map['Bob'].cat_rank   == 3

    @patch('results.views.Mopclass')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_classés_premier_non_classés_apres_meme_catégorie(
        self, mock_get404, mock_render, MockCompetitor, MockClass
    ):
        """Mix classé + non-classé dans même catégorie : classé toujours en premier."""
        competition  = make_competition()
        organization = MagicMock()
        mock_get404.side_effect = [competition, organization]

        ok  = make_competitor(1, rt=5000, stat=STAT_OK,  cls=10, name='Alice')
        dnf = make_nf(2, STAT_DNF, 'Bob')
        dnf.cls = 10

        MockCompetitor.objects.filter.side_effect = [
            [ok, dnf],  # org competitors
            [ok],       # all finishers in class 10
        ]
        MockClass.objects.filter.return_value = []

        from results.views import org_results
        org_results(rf_get(), cid=1, org_id=5)

        _, _, context = mock_render.call_args[0]
        noms = [x.name for x in context['competitors']]
        assert noms[0] == 'Alice'
        assert noms[1] == 'Bob'


# ─── Tests statistics ────────────────────────────────────────────────────────

class TestStatisticsView:

    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_contexte_statistiques(self, MockCompetitor, mock_get404, mock_render):
        competition = make_competition()
        mock_get404.return_value = competition

        MockCompetitor.objects.filter.return_value.count.return_value = 120
        MockCompetitor.objects.filter.return_value.exclude.return_value.count.return_value = 95

        with patch('django.db.connection') as mock_conn:
            cursor = MagicMock()
            cursor.fetchall.return_value = [('COLE', 15), ('NOSE', 10)]
            mock_conn.cursor.return_value.__enter__.return_value = cursor

            from results.views import statistics
            statistics(rf_get(), cid=1)

        _, template, context = mock_render.call_args[0]
        assert template == 'results/statistics.html'
        assert 'total'    in context
        assert 'finished' in context
        assert 'top_orgs' in context
        assert 'competition' in context


# ─── Tests relay_results ──────────────────────────────────────────────────────

class TestRelayResultsView:

    def _make_team(self, id_, rt=10000, stat=STAT_OK, org=1, cls=10):
        t = MagicMock()
        t.id   = id_
        t.rt   = rt
        t.stat = stat
        t.org  = org
        t.cls  = cls
        t.name = f'Equipe {id_}'
        return t

    def _make_member(self, team_id, rid, leg=1, ord_=1):
        m = MagicMock()
        m.id  = team_id
        m.rid = rid
        m.leg = leg
        m.ord = ord_
        return m

    @patch('results.views.get_controls_by_leg', return_value=({}, {}))
    @patch('results.views.get_radio_map',        return_value={})
    @patch('results.views.get_org_map',          return_value={1: 'COLE'})
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteammember')
    @patch('results.views.Mopteam')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_contexte_relay(
        self, mock_get404, mock_render, MockTeam, MockTeamMember,
        MockCompetitor, mock_org, mock_radio, mock_ctrl,
    ):
        competition = make_competition(); cls = make_cls()
        mock_get404.side_effect = [competition, cls]

        t1 = self._make_team(1, rt=10000)
        t2 = self._make_team(2, rt=12000)
        MockTeam.objects.filter.return_value = [t1, t2]

        m1 = self._make_member(team_id=1, rid=101, leg=1)
        m2 = self._make_member(team_id=2, rid=102, leg=1)
        MockTeamMember.objects.filter.return_value.order_by.return_value = [m1, m2]

        c101 = make_competitor(101, rt=10000)
        c102 = make_competitor(102, rt=12000)
        MockCompetitor.objects.filter.return_value = [c101, c102]

        from results.views import relay_results
        relay_results(rf_get(), cid=1, class_id=10)

        _, template, context = mock_render.call_args[0]
        assert template == 'results/relay_results.html'
        assert 'teams_data'  in context
        assert 'leader_time' in context
        assert 'n_legs'      in context
        assert len(context['teams_data']) == 2


# ─── Tests duel_analysis ──────────────────────────────────────────────────────

class TestDuelAnalysisView:

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.compute_splits',     return_value=[])
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteam')
    def test_template_et_cles_de_base(
        self, MockTeam, MockCompetitor, mock_get404, mock_render,
        mock_splits, mock_radio, mock_ctrl, mock_org,
    ):
        MockTeam.objects.filter.return_value.exists.return_value = False
        competition = make_competition(); cls = make_cls()
        mock_get404.side_effect = [competition, cls]
        c1 = make_competitor(1, rt=5000); c2 = make_competitor(2, rt=6000)
        MockCompetitor.objects.filter.return_value = [c1, c2]

        from results.views import duel_analysis
        duel_analysis(rf_get(), cid=1, class_id=10)

        _, template, context = mock_render.call_args[0]
        assert template == 'results/duel.html'
        assert 'runners_json' in context
        assert 'n_runners'    in context
        assert context['no_data'] is False
        assert context['current_analysis'] == 'duel'

    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteam')
    def test_no_data_si_aucun_coureur(
        self, MockTeam, MockCompetitor, mock_get404, mock_render,
    ):
        MockTeam.objects.filter.return_value.exists.return_value = False
        competition = make_competition(); cls = make_cls()
        mock_get404.side_effect = [competition, cls]
        MockCompetitor.objects.filter.return_value = []

        from results.views import duel_analysis
        duel_analysis(rf_get(), cid=1, class_id=10)

        _, template, context = mock_render.call_args[0]
        assert template == 'results/duel.html'
        assert context['no_data'] is True

    @patch('results.views.redirect')
    @patch('results.views.Mopteam')
    def test_redirige_vers_relay_si_relais(self, MockTeam, mock_redirect):
        MockTeam.objects.filter.return_value.exists.return_value = True

        from results.views import duel_analysis
        duel_analysis(rf_get(), cid=1, class_id=10)

        mock_redirect.assert_called_once_with(
            'results:relay_results', cid=1, class_id=10
        )


# ─── Tests _slugify_no_prefix ─────────────────────────────────────────────────

class TestSlugifyNoPrefix:

    def _call(self, value):
        from results.views import _slugify_no_prefix
        return _slugify_no_prefix(value, separator='-')

    def test_prefixe_simple_retire(self):
        assert self._call('1 En amont') == 'en-amont'

    def test_prefixe_pointe_retire(self):
        assert self._call('5. Statuts des coureurs') == 'statuts-des-coureurs'

    def test_prefixe_compose_retire(self):
        assert self._call('1.1 Créer la compétition') == 'créer-la-compétition'

    def test_sans_prefixe_inchange(self):
        result = self._call('Introduction')
        assert result == 'introduction'

    def test_prefixe_multi_niveaux(self):
        assert self._call('3.2.1 Sous-section') == 'sous-section'


# ─── Tests competition_detail ─────────────────────────────────────────────────

class TestCompetitionDetailView:

    def _run(self, cid=1, classes=None, teams_cls_ids=None,
             competitors_count=5, finishers_count=3, relay_count=2, relay_finishers=1):
        competition = make_competition(cid)
        classes     = classes or [make_cls(cid, 10), make_cls(cid, 11)]
        relay_cls_ids = teams_cls_ids if teams_cls_ids is not None else set()

        with patch('results.views.get_object_or_404', return_value=competition), \
             patch('results.views.Mopclass') as MockClass, \
             patch('results.views.Mopteam') as MockTeam, \
             patch('results.views.Mopcompetitor') as MockCompetitor, \
             patch('results.views.render') as mock_render:

            MockClass.objects.filter.return_value.order_by.return_value = classes

            MockTeam.objects.filter.return_value \
                .values_list.return_value \
                .distinct.return_value = list(relay_cls_ids)

            comp_qs  = MagicMock()
            comp_qs.count.return_value = competitors_count
            comp_qs.filter.return_value.exclude.return_value.count.return_value = finishers_count
            MockCompetitor.objects.filter.return_value = comp_qs

            MockTeam.objects.filter.return_value.count.return_value = relay_count
            MockTeam.objects.filter.return_value.filter.return_value.exclude.return_value.count.return_value = relay_finishers

            from results.views import competition_detail
            competition_detail(rf_get(), cid=cid)

            _, template, context = mock_render.call_args[0]
            return template, context

    def test_template_correct(self):
        template, _ = self._run()
        assert template == 'results/competition_detail.html'

    def test_cles_de_contexte(self):
        _, context = self._run()
        assert 'competition' in context
        assert 'class_stats' in context

    def test_class_stats_contient_toutes_les_classes(self):
        cls1 = make_cls(1, 10); cls2 = make_cls(1, 11)
        _, context = self._run(classes=[cls1, cls2])
        assert len(context['class_stats']) == 2

    def test_classe_relais_marquee_true(self):
        cls1 = make_cls(1, 10)
        _, context = self._run(classes=[cls1], teams_cls_ids={10})
        stat = context['class_stats'][0]
        assert stat['is_relay'] is True

    def test_classe_individuelle_marquee_false(self):
        cls1 = make_cls(1, 10)
        _, context = self._run(classes=[cls1], teams_cls_ids=set())
        stat = context['class_stats'][0]
        assert stat['is_relay'] is False
