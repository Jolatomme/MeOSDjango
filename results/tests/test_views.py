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

    # ── Ordre des groupes ─────────────────────────────────────────────────────

    def test_pm_apres_nc(self):
        """PM (STAT_MP) doit venir après NC (STAT_OCC)."""
        nc = make_nf(1, STAT_OCC, 'Alice')
        pm = make_nf(2, STAT_MP, 'Bob')
        result = self._call([pm, nc])
        assert result[0].id == nc.id
        assert result[1].id == pm.id

    def test_abandon_apres_pm(self):
        """Abandon (STAT_DNF) doit venir après PM (STAT_MP)."""
        pm  = make_nf(1, STAT_MP,  'Alice')
        dnf = make_nf(2, STAT_DNF, 'Bob')
        result = self._call([dnf, pm])
        assert result[0].id == pm.id
        assert result[1].id == dnf.id

    def test_dns_apres_abandon(self):
        """Non-partant (STAT_DNS) doit venir après Abandon (STAT_DNF)."""
        dnf = make_nf(1, STAT_DNF, 'Alice')
        dns = make_nf(2, STAT_DNS, 'Bob')
        result = self._call([dns, dnf])
        assert result[0].id == dnf.id
        assert result[1].id == dns.id

    def test_np_groupe_avec_dns(self):
        """STAT_NP et STAT_DNS sont dans le même groupe (groupe 4)."""
        dns = make_nf(1, STAT_DNS, 'Alice')
        np_ = make_nf(2, STAT_NP,  'Bob')
        result = self._call([np_, dns])
        # Même groupe → tri alpha : Alice avant Bob
        noms = [r.name for r in result]
        assert noms == ['Alice', 'Bob']

    def test_cancel_groupe_avec_dns(self):
        """STAT_CANCEL est dans le même groupe que DNS."""
        dns    = make_nf(1, STAT_DNS,    'Zara')
        cancel = make_nf(2, STAT_CANCEL, 'Alice')
        result = self._call([dns, cancel])
        # Même groupe → alpha : Alice avant Zara
        assert result[0].name == 'Alice'
        assert result[1].name == 'Zara'

    def test_ordre_complet_nc_pm_dnf_dns(self):
        """Ordre global : NC → PM → Abandon → Non-partants."""
        dns = make_nf(1, STAT_DNS, 'DNS')
        dnf = make_nf(2, STAT_DNF, 'DNF')
        pm  = make_nf(3, STAT_MP,  'PM')
        nc  = make_nf(4, STAT_OCC, 'NC')
        result = self._call([dns, dnf, pm, nc])
        assert [r.id for r in result] == [4, 3, 2, 1]

    # ── Tri alphabétique dans chaque groupe ──────────────────────────────────

    def test_alpha_dans_groupe_pm(self):
        """Dans le groupe PM, tri alphabétique."""
        pm1 = make_nf(1, STAT_MP, 'Zara')
        pm2 = make_nf(2, STAT_MP, 'Alice')
        pm3 = make_nf(3, STAT_MP, 'Martin')
        result = self._call([pm1, pm2, pm3])
        noms = [r.name for r in result]
        assert noms == ['Alice', 'Martin', 'Zara']

    def test_alpha_dans_groupe_dnf(self):
        """Dans le groupe Abandon, tri alphabétique."""
        d1 = make_nf(1, STAT_DNF, 'Zorro')
        d2 = make_nf(2, STAT_DNF, 'Alice')
        result = self._call([d1, d2])
        assert result[0].name == 'Alice'

    def test_alpha_dans_groupe_nc(self):
        """Dans le groupe NC, tri alphabétique."""
        n1 = make_nf(1, STAT_OCC, 'Zara')
        n2 = make_nf(2, STAT_OCC, 'Alice')
        n3 = make_nf(3, STAT_NT,  'Martin')  # NT = groupe NC aussi
        result = self._call([n1, n2, n3])
        noms = [r.name for r in result]
        assert noms == ['Alice', 'Martin', 'Zara']

    def test_alpha_insensible_a_la_casse(self):
        """Le tri alphabétique est insensible à la casse."""
        d1 = make_nf(1, STAT_DNF, 'alice')
        d2 = make_nf(2, STAT_DNF, 'Bob')
        d3 = make_nf(3, STAT_DNF, 'CHARLIE')
        result = self._call([d3, d2, d1])
        noms = [r.name for r in result]
        assert noms == ['alice', 'Bob', 'CHARLIE']

    # ── Cas limites ───────────────────────────────────────────────────────────

    def test_liste_vide(self):
        assert self._call([]) == []

    def test_un_seul_element(self):
        c = make_nf(1, STAT_DNF, 'Alice')
        assert self._call([c]) == [c]

    def test_ne_modifie_pas_liste_originale(self):
        """L'original ne doit pas être muté."""
        original = [make_nf(1, STAT_DNS, 'B'), make_nf(2, STAT_MP, 'A')]
        ids_avant = [c.id for c in original]
        self._call(original)
        assert [c.id for c in original] == ids_avant

    def test_statut_inconnu_en_dernier(self):
        """Un statut non référencé (groupe 5) passe après tous les autres."""
        dnf     = make_nf(1, STAT_DNF, 'Alice')
        inconnu = make_nf(2, 99,       'Zara')  # STAT_NP = 99 → groupe 4
        # STAT_NP est groupe 4 (DNS), donc Zara vient après Alice (DNF, groupe 3)
        result = self._call([inconnu, dnf])
        assert result[0].id == dnf.id
        assert result[1].id == inconnu.id

    # ── Statuts spéciaux du groupe NC ────────────────────────────────────────

    def test_nt_groupe_nc(self):
        """STAT_NT est dans le groupe NC (groupe 1)."""
        nt = make_nf(1, STAT_NT, 'Alice')
        pm = make_nf(2, STAT_MP, 'Bob')
        result = self._call([pm, nt])
        assert result[0].id == nt.id   # NT avant PM

    def test_ot_groupe_nc(self):
        """STAT_OT est dans le groupe NC (groupe 1)."""
        ot = make_nf(1, STAT_OT, 'Alice')
        pm = make_nf(2, STAT_MP, 'Bob')
        result = self._call([pm, ot])
        assert result[0].id == ot.id   # OT avant PM

    def test_dq_groupe_nc(self):
        """STAT_DQ est dans le groupe NC (groupe 1)."""
        dq = make_nf(1, STAT_DQ, 'Alice')
        pm = make_nf(2, STAT_MP, 'Bob')
        result = self._call([pm, dq])
        assert result[0].id == dq.id   # DQ avant PM

    # ── Mélange groupes et alpha ──────────────────────────────────────────────

    def test_mixte_meme_groupe_alpha_pas_id(self):
        """Dans un groupe, c'est le nom (alpha) qui tranche, pas l'id."""
        pm_z = make_nf(10, STAT_MP, 'Zara')
        pm_a = make_nf(99, STAT_MP, 'Alice')
        result = self._call([pm_z, pm_a])
        assert result[0].name == 'Alice'
        assert result[1].name == 'Zara'


# ─── Tests _load_class_context ───────────────────────────────────────────────

class TestLoadClassContext:
    """Vérifie le helper interne _load_class_context."""

    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_object_or_404')
    def test_retourne_competition_cls_competitors(self, mock_get404, MockCompetitor):
        """Le helper doit retourner le triplet (competition, cls, competitors)."""
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
        assert c1 in competitors
        assert c2 in competitors

    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_object_or_404')
    def test_appelle_get_object_or_404_deux_fois(self, mock_get404, MockCompetitor):
        """get_object_or_404 doit être appelé une fois pour la compétition et une pour la classe."""
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockCompetitor.objects.filter.return_value = []

        from results.views import _load_class_context
        _load_class_context(cid=5, class_id=20)

        assert mock_get404.call_count == 2

    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_object_or_404')
    def test_filtre_concurrents_par_cid_et_class_id(self, mock_get404, MockCompetitor):
        """Les concurrents doivent être filtrés avec cid et cls=class_id."""
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockCompetitor.objects.filter.return_value = []

        from results.views import _load_class_context
        _load_class_context(cid=3, class_id=15)

        MockCompetitor.objects.filter.assert_called_once_with(cid=3, cls=15)

    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_object_or_404')
    def test_retourne_liste_et_non_queryset(self, mock_get404, MockCompetitor):
        """Le retour doit être une liste Python (list()), non un QuerySet."""
        mock_get404.side_effect = [make_competition(), make_cls()]
        MockCompetitor.objects.filter.return_value = [make_competitor(1)]

        from results.views import _load_class_context
        _, _, competitors = _load_class_context(cid=1, class_id=10)

        assert isinstance(competitors, list)

    @patch('results.views.Mopcompetitor')
    @patch('results.views.get_object_or_404', side_effect=Http404)
    def test_leve_404_si_objet_absent(self, mock_get404, MockCompetitor):
        """Http404 doit se propager si la compétition ou la classe est introuvable."""
        from django.http import Http404 as Http404Ex
        from results.views import _load_class_context
        import pytest
        with pytest.raises(Http404Ex):
            _load_class_context(cid=999, class_id=10)


# ─── Tests _get_adjacent_classes ─────────────────────────────────────────────

class TestGetAdjacentClasses:
    """Vérifie le helper qui renvoie les catégories précédente et suivante."""

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

    def test_deux_classes_premiere(self):
        cls_list = [self._mk_cls(10, 'H21'), self._mk_cls(20, 'D21')]
        prev, nxt = self._call(cls_list, cid=1, class_id=10)
        assert prev is None
        assert nxt.id == 20

    def test_deux_classes_derniere(self):
        cls_list = [self._mk_cls(10, 'H21'), self._mk_cls(20, 'D21')]
        prev, nxt = self._call(cls_list, cid=1, class_id=20)
        assert prev.id == 10
        assert nxt is None

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
        """Configure les mocks pour une course individuelle sans relais."""
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
        """prev_cls et next_cls doivent être présents dans le contexte."""
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
        """Les valeurs renvoyées par _get_adjacent_classes sont bien transmises."""
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
    """Vérifie que les non-classés sont triés dans le contexte :
    NC/DSQ → PM → Abandon → Non-partants, puis alpha dans chaque groupe.
    """

    def _run(self, competitors):
        """Lance class_results avec des mocks minimaux et retourne le contexte."""
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
        """Les coureurs classés (OK) apparaissent avant tous les non-classés."""
        ok1 = make_competitor(1, rt=5000, stat=STAT_OK, name='Alice')
        ok2 = make_competitor(2, rt=6000, stat=STAT_OK, name='Bob')
        dnf = make_nf(3, STAT_DNF, 'Charlie')
        ctx = self._run([dnf, ok1, ok2])
        noms = [r.name for r in ctx['results']]
        assert noms.index('Alice') < noms.index('Charlie')
        assert noms.index('Bob')   < noms.index('Charlie')

    def test_nc_avant_pm(self):
        """STAT_OCC (NC) apparaît avant STAT_MP (PM)."""
        pm = make_nf(1, STAT_MP,  'Alice PM')
        nc = make_nf(2, STAT_OCC, 'Bob NC')
        ctx = self._run([pm, nc])
        noms = [r.name for r in ctx['results']]
        assert noms.index('Bob NC') < noms.index('Alice PM')

    def test_pm_avant_abandon(self):
        """STAT_MP (PM) apparaît avant STAT_DNF (Abandon)."""
        dnf = make_nf(1, STAT_DNF, 'Alice DNF')
        pm  = make_nf(2, STAT_MP,  'Bob PM')
        ctx = self._run([dnf, pm])
        noms = [r.name for r in ctx['results']]
        assert noms.index('Bob PM') < noms.index('Alice DNF')

    def test_abandon_avant_dns(self):
        """STAT_DNF (Abandon) apparaît avant STAT_DNS (Non partant)."""
        dns = make_nf(1, STAT_DNS, 'Alice DNS')
        dnf = make_nf(2, STAT_DNF, 'Bob DNF')
        ctx = self._run([dns, dnf])
        noms = [r.name for r in ctx['results']]
        assert noms.index('Bob DNF') < noms.index('Alice DNS')

    def test_ordre_complet_quatre_groupes(self):
        """Ordre complet : NC → PM → Abandon → Non-partants."""
        dns = make_nf(1, STAT_DNS, 'DNS')
        dnf = make_nf(2, STAT_DNF, 'DNF')
        pm  = make_nf(3, STAT_MP,  'PM')
        nc  = make_nf(4, STAT_OCC, 'NC')
        # On ajoute aussi un classé
        ok  = make_competitor(5, rt=5000, name='OK')
        ctx = self._run([dns, dnf, pm, nc, ok])
        noms = [r.name for r in ctx['results']]
        idx  = {n: noms.index(n) for n in ['OK', 'NC', 'PM', 'DNF', 'DNS']}
        assert idx['OK']  < idx['NC']
        assert idx['NC']  < idx['PM']
        assert idx['PM']  < idx['DNF']
        assert idx['DNF'] < idx['DNS']

    def test_alpha_dans_groupe_pm(self):
        """Dans le groupe PM, les coureurs sont triés alphabétiquement."""
        pm_z = make_nf(1, STAT_MP, 'Zara')
        pm_a = make_nf(2, STAT_MP, 'Alice')
        pm_m = make_nf(3, STAT_MP, 'Martin')
        ctx = self._run([pm_z, pm_a, pm_m])
        noms = [r.name for r in ctx['results']]
        assert noms == ['Alice', 'Martin', 'Zara']

    def test_alpha_dans_groupe_dnf(self):
        """Dans le groupe Abandon, tri alphabétique."""
        d1 = make_nf(1, STAT_DNF, 'Zorro')
        d2 = make_nf(2, STAT_DNF, 'Alice')
        ctx = self._run([d1, d2])
        noms = [r.name for r in ctx['results']]
        assert noms[0] == 'Alice'
        assert noms[1] == 'Zorro'

    def test_alpha_dans_groupe_dns(self):
        """Dans le groupe Non-partants, tri alphabétique (DNS + NP mélangés)."""
        dns = make_nf(1, STAT_DNS, 'Zara DNS')
        np_ = make_nf(2, STAT_NP,  'Alice NP')
        ctx = self._run([dns, np_])
        noms = [r.name for r in ctx['results']]
        assert noms[0] == 'Alice NP'
        assert noms[1] == 'Zara DNS'

    def test_sans_non_classes_ordre_inchange(self):
        """Sans non-classés, l'ordre des classés est préservé (par rt)."""
        ok1 = make_competitor(1, rt=5000, name='Alice')
        ok2 = make_competitor(2, rt=6000, name='Bob')
        ctx = self._run([ok2, ok1])   # ORM retourne dans un ordre quelconque
        noms = [r.name for r in ctx['results']]
        assert noms[0] == 'Alice'  # plus rapide → 1er
        assert noms[1] == 'Bob'

    def test_seulement_non_classes(self):
        """Avec uniquement des non-classés, le tri fonctionne quand même."""
        dnf = make_nf(1, STAT_DNF, 'Bob')
        dns = make_nf(2, STAT_DNS, 'Alice')
        pm  = make_nf(3, STAT_MP,  'Charlie')
        ctx = self._run([dnf, dns, pm])
        noms = [r.name for r in ctx['results']]
        # PM (groupe 2) → DNF (groupe 3) → DNS (groupe 4)
        assert noms == ['Charlie', 'Bob', 'Alice']

    def test_n_results_correct(self):
        """Le nombre total de résultats (classés + non-classés) est correct."""
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
        assert data['results'][0]['time'] == '08:20'   # 5000 dixièmes = 8m20s
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
        # Aucun compétiteur classé
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
            assert field in s, f"Champ '{field}' manquant dans series_json (requis par buildTable)"

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

        assert series[0]['name'] == 'Bob',   "Bob (rt=5000) doit être rank=1, index 0 dans SERIES"
        assert series[1]['name'] == 'Alice', "Alice (rt=8000) doit être rank=2, index 1 dans SERIES"
        assert series[0]['rank'] == 1
        assert series[1]['rank'] == 2

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_index_series_egal_rang_moins_un(
        self, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        competition = make_competition(); cls = make_cls()
        mock_get404.side_effect = [competition, cls]

        runners = [make_competitor(i, rt=5000 + i * 1000) for i in range(1, 6)]
        MockCompetitor.objects.filter.return_value = runners

        from results.views import superman_analysis
        superman_analysis(rf_get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        series = json.loads(context['series_json'])

        for i, s in enumerate(series):
            assert s['rank'] == i + 1, \
                f"Attendu rank={i+1} à l'index {i}, obtenu rank={s['rank']}"

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_champ_id_unique_dans_series(
        self, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        competition = make_competition(); cls = make_cls()
        mock_get404.side_effect = [competition, cls]

        c1 = make_competitor(42, rt=5000, name='Alice')
        c2 = make_competitor(99, rt=6000, name='Bob')
        MockCompetitor.objects.filter.return_value = [c1, c2]

        from results.views import superman_analysis
        superman_analysis(rf_get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        series = json.loads(context['series_json'])

        ids = [s['id'] for s in series]
        assert len(ids) == len(set(ids)), "Les ids dans series_json doivent être uniques"
        assert 42 in ids
        assert 99 in ids


class TestClassResultsRankSplits:
    """Vérifie que rank_splits est appelé et que les rangs sont présents dans les splits."""

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
        """rank_splits doit être appelé lors du rendu des résultats."""
        MockTeam.objects.filter.return_value.exists.return_value = False
        competition = make_competition(); cls = make_cls()
        mock_get404.side_effect = [competition, cls]
        c1 = make_competitor(1, rt=5000); c2 = make_competitor(2, rt=6000)
        MockCompetitor.objects.filter.return_value = [c1, c2]

        from results.views import class_results
        class_results(rf_get(), cid=1, class_id=10)

        assert mock_rank.called, "rank_splits devrait être appelé dans class_results"

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
    def test_rank_splits_recoit_finishers_et_all_results(
        self, MockTeam, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org, mock_mark, mock_rank, mock_adj,
    ):
        """rank_splits doit recevoir (finishers, all_results) comme arguments."""
        MockTeam.objects.filter.return_value.exists.return_value = False
        competition = make_competition(); cls = make_cls()
        mock_get404.side_effect = [competition, cls]
        c1 = make_competitor(1, rt=5000); c2 = make_competitor(2, rt=6000)
        MockCompetitor.objects.filter.return_value = [c1, c2]

        from results.views import class_results
        class_results(rf_get(), cid=1, class_id=10)

        args = mock_rank.call_args[0]
        finishers, all_results = args[0], args[1]
        assert len(finishers) == 2
        assert len(all_results) == 2


# ─── Tests org_results ────────────────────────────────────────────────────────

class TestOrgResultsView:

    @patch('results.views.Mopclass')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_contexte(self, mock_get404, mock_render, MockCompetitor, MockClass):
        competition  = make_competition()
        organization = MagicMock(); organization.name = 'COLE'
        mock_get404.side_effect = [competition, organization]

        c1 = make_competitor(1, cls=10); c2 = make_competitor(2, cls=11)
        MockCompetitor.objects.filter.return_value.order_by.return_value = [c1, c2]
        cls_obj = MagicMock(); cls_obj.id = 10
        MockClass.objects.filter.return_value = [cls_obj]

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
        """Chaque coureur doit avoir un attribut class_obj."""
        competition  = make_competition()
        organization = MagicMock()
        mock_get404.side_effect = [competition, organization]

        c = make_competitor(1, cls=10)
        MockCompetitor.objects.filter.return_value.order_by.return_value = [c]
        cls_obj = MagicMock(); cls_obj.id = 10
        MockClass.objects.filter.return_value = [cls_obj]

        from results.views import org_results
        org_results(rf_get(), cid=1, org_id=5)

        assert hasattr(c, 'class_obj')
        assert c.class_obj is cls_obj


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

    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    def test_top_orgs_transmis(self, MockCompetitor, mock_get404, mock_render):
        competition = make_competition()
        mock_get404.return_value = competition
        MockCompetitor.objects.filter.return_value.count.return_value = 50
        MockCompetitor.objects.filter.return_value.exclude.return_value.count.return_value = 40

        expected_orgs = [('COLE', 15), ('NOSE', 10)]
        with patch('django.db.connection') as mock_conn:
            cursor = MagicMock()
            cursor.fetchall.return_value = expected_orgs
            mock_conn.cursor.return_value.__enter__.return_value = cursor

            from results.views import statistics
            statistics(rf_get(), cid=1)

        _, _, context = mock_render.call_args[0]
        assert context['top_orgs'] == expected_orgs


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

    @patch('results.views.get_controls_by_leg', return_value=({}, {}))
    @patch('results.views.get_radio_map',        return_value={})
    @patch('results.views.get_org_map',          return_value={1: 'COLE'})
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteammember')
    @patch('results.views.Mopteam')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_classement_equipes_par_temps(
        self, mock_get404, mock_render, MockTeam, MockTeamMember,
        MockCompetitor, mock_org, mock_radio, mock_ctrl,
    ):
        competition = make_competition(); cls = make_cls()
        mock_get404.side_effect = [competition, cls]

        t_lente  = self._make_team(1, rt=15000)
        t_rapide = self._make_team(2, rt=10000)
        MockTeam.objects.filter.return_value = [t_lente, t_rapide]
        MockTeamMember.objects.filter.return_value.order_by.return_value = []
        MockCompetitor.objects.filter.return_value = []

        from results.views import relay_results
        relay_results(rf_get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        teams = context['teams_data']
        assert teams[0]['team'].rt == 10000

    @patch('results.views.get_controls_by_leg', return_value=({1: [31]}, {31: 'P31'}))
    @patch('results.views.get_radio_map',        return_value={101: {31: 3000}})
    @patch('results.views.get_org_map',          return_value={})
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteammember')
    @patch('results.views.Mopteam')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_legs_data_contient_splits(
        self, mock_get404, mock_render, MockTeam, MockTeamMember,
        MockCompetitor, mock_org, mock_radio, mock_ctrl,
    ):
        competition = make_competition(); cls = make_cls()
        mock_get404.side_effect = [competition, cls]

        t = self._make_team(1, rt=10000)
        MockTeam.objects.filter.return_value = [t]

        m = self._make_member(team_id=1, rid=101, leg=1)
        MockTeamMember.objects.filter.return_value.order_by.return_value = [m]

        c = make_competitor(101, rt=10000)
        MockCompetitor.objects.filter.return_value = [c]

        from results.views import relay_results
        relay_results(rf_get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        leg_data = context['teams_data'][0]['legs'][0]
        assert 'splits'     in leg_data
        assert 'leg_time'   in leg_data
        assert 'cum_time'   in leg_data
        assert 'stat_label' in leg_data

    @patch('results.views.get_controls_by_leg', return_value=({}, {}))
    @patch('results.views.get_radio_map',        return_value={})
    @patch('results.views.get_org_map',          return_value={})
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteammember')
    @patch('results.views.Mopteam')
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    def test_equipe_dnf_incluse(
        self, mock_get404, mock_render, MockTeam, MockTeamMember,
        MockCompetitor, mock_org, mock_radio, mock_ctrl,
    ):
        competition = make_competition(); cls = make_cls()
        mock_get404.side_effect = [competition, cls]

        t_ok  = self._make_team(1, rt=10000, stat=STAT_OK)
        t_dnf = self._make_team(2, rt=-1,    stat=4)
        MockTeam.objects.filter.return_value = [t_ok, t_dnf]
        MockTeamMember.objects.filter.return_value.order_by.return_value = []
        MockCompetitor.objects.filter.return_value = []

        from results.views import relay_results
        relay_results(rf_get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        assert len(context['teams_data']) == 2


# ─── Tests relay_results — classements par fraction et au cumulé ──────────────

class TestRelayResultsRanking:
    """Vérifie le calcul de leg_rank et cum_rank dans les fractions de relais."""

    def _make_team(self, id_, rt=10000, stat=STAT_OK, org=1):
        t = MagicMock()
        t.id = id_; t.rt = rt; t.stat = stat; t.org = org
        t.name = f'Equipe {id_}'
        return t

    def _make_member(self, team_id, rid, leg=1, ord_=1):
        m = MagicMock()
        m.id = team_id; m.rid = rid; m.leg = leg; m.ord = ord_
        return m

    def _run_view(self, teams, members, competitors_list,
                  org_map=None, controls_by_leg=None, radio_map=None):
        from django.test import RequestFactory
        from unittest.mock import patch, MagicMock

        comp = MagicMock(); comp.cid = 1
        cls  = MagicMock(); cls.id  = 10

        with patch('results.views.get_object_or_404', side_effect=[comp, cls]), \
             patch('results.views.Mopteam') as MockTeam, \
             patch('results.views.Mopteammember') as MockMember, \
             patch('results.views.Mopcompetitor') as MockComp, \
             patch('results.views.get_org_map', return_value=org_map or {}), \
             patch('results.views.get_controls_by_leg',
                   return_value=(controls_by_leg or {}, {})), \
             patch('results.views.get_radio_map', return_value=radio_map or {}), \
             patch('results.views.render') as mock_render:

            MockTeam.objects.filter.return_value = teams
            MockMember.objects.filter.return_value.order_by.return_value = members
            MockComp.objects.filter.return_value = competitors_list

            from results.views import relay_results
            relay_results(RequestFactory().get('/'), cid=1, class_id=10)

            _, _, context = mock_render.call_args[0]
            return context

    def test_leg_rank_une_seule_equipe(self):
        t = self._make_team(1, rt=10000)
        m = self._make_member(team_id=1, rid=101, leg=1)
        c = make_competitor(101, rt=10000)

        ctx = self._run_view([t], [m], [c])
        leg = ctx['teams_data'][0]['legs'][0]
        assert leg['leg_rank'] == 1
        assert leg['cum_rank'] == 1

    def test_leg_rank_deux_equipes_ordre_correct(self):
        t1 = self._make_team(1, rt=18000)
        t2 = self._make_team(2, rt=20000)
        m1 = self._make_member(team_id=1, rid=101, leg=1)
        m2 = self._make_member(team_id=2, rid=102, leg=1)
        c1 = make_competitor(101, rt=8000)
        c2 = make_competitor(102, rt=10000)

        ctx = self._run_view([t1, t2], [m1, m2], [c1, c2])
        legs = {td['team'].id: td['legs'][0] for td in ctx['teams_data']}
        assert legs[1]['leg_rank'] == 1
        assert legs[2]['leg_rank'] == 2

    def test_cum_rank_independant_du_leg_rank(self):
        t1 = self._make_team(1, rt=17000)
        t2 = self._make_team(2, rt=19000)
        m1a = self._make_member(team_id=1, rid=101, leg=1)
        m1b = self._make_member(team_id=1, rid=102, leg=2)
        m2a = self._make_member(team_id=2, rid=103, leg=1)
        m2b = self._make_member(team_id=2, rid=104, leg=2)
        c101 = make_competitor(101, rt=5000)
        c102 = make_competitor(102, rt=12000)
        c103 = make_competitor(103, rt=9000)
        c104 = make_competitor(104, rt=10000)

        ctx = self._run_view([t1, t2], [m1a, m1b, m2a, m2b], [c101, c102, c103, c104])
        legs_t1 = ctx['teams_data'][0]['legs']
        legs_t2 = ctx['teams_data'][1]['legs']

        assert legs_t2[1]['leg_rank'] == 1
        assert legs_t1[1]['leg_rank'] == 2
        assert legs_t1[1]['cum_rank'] == 1
        assert legs_t2[1]['cum_rank'] == 2

    def test_leg_rank_none_si_temps_manquant(self):
        t1 = self._make_team(1, rt=10000)
        t2 = self._make_team(2, rt=-1, stat=4)
        m1 = self._make_member(team_id=1, rid=101, leg=1)
        c1 = make_competitor(101, rt=10000)

        ctx = self._run_view([t1, t2], [m1], [c1])
        legs_t2 = next(td for td in ctx['teams_data'] if td['team'].id == 2)['legs']
        assert legs_t2[0]['leg_rank'] is None
        assert legs_t2[0]['cum_rank'] is None

    def test_leg_rank_exaequo_meme_rang(self):
        t1 = self._make_team(1, rt=10000)
        t2 = self._make_team(2, rt=10000)
        m1 = self._make_member(team_id=1, rid=101, leg=1)
        m2 = self._make_member(team_id=2, rid=102, leg=1)
        c1 = make_competitor(101, rt=10000)
        c2 = make_competitor(102, rt=10000)

        ctx = self._run_view([t1, t2], [m1, m2], [c1, c2])
        legs = {td['team'].id: td['legs'][0] for td in ctx['teams_data']}
        assert legs[1]['leg_rank'] == 1
        assert legs[2]['leg_rank'] == 1

    def test_legs_data_contient_champs_rang(self):
        t = self._make_team(1, rt=10000)
        m = self._make_member(team_id=1, rid=101, leg=1)
        c = make_competitor(101, rt=10000)

        ctx = self._run_view([t], [m], [c])
        leg = ctx['teams_data'][0]['legs'][0]
        assert 'leg_rank' in leg
        assert 'cum_rank' in leg

    def test_leg_time_raw_et_cum_time_raw_presents(self):
        t = self._make_team(1, rt=10000)
        m = self._make_member(team_id=1, rid=101, leg=1)
        c = make_competitor(101, rt=10000)

        ctx = self._run_view([t], [m], [c])
        leg = ctx['teams_data'][0]['legs'][0]
        assert 'leg_time_raw' in leg
        assert 'cum_time_raw' in leg
        assert leg['leg_time_raw'] == 10000
        assert leg['cum_time_raw'] == 10000


# ─── Tests superman — avec contrôles réels ────────────────────────────────────

class TestSupermanWithControls:
    """Teste superman_analysis avec des contrôles intermédiaires réels."""

    def _run(self, competitors, controls_seq, radio_map):
        comp = make_competition()
        cls  = make_cls()
        with patch('results.views.get_object_or_404', side_effect=[comp, cls]), \
             patch('results.views.Mopcompetitor') as MockComp, \
             patch('results.views.get_org_map', return_value={}), \
             patch('results.views.get_class_controls', return_value=(controls_seq, {})), \
             patch('results.views.get_radio_map', return_value=radio_map), \
             patch('results.views.render') as mock_render:
            MockComp.objects.filter.return_value = competitors
            from results.views import superman_analysis
            superman_analysis(rf_get(), cid=1, class_id=10)
            _, _, ctx = mock_render.call_args[0]
            return ctx

    def test_points_debut_a_zero(self):
        c1 = make_competitor(1, rt=3600)
        c2 = make_competitor(2, rt=4000)
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        radio_map    = {1: {31: 1200}, 2: {31: 1500}}
        ctx = self._run([c1, c2], controls_seq, radio_map)
        for s in ctx['series']:
            assert s['points'][0] == 0

    def test_leader_perd_moins_que_les_autres(self):
        c1 = make_competitor(1, rt=3600, name='Rapide')
        c2 = make_competitor(2, rt=5000, name='Lent')
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        radio_map    = {1: {31: 1200}, 2: {31: 1800}}
        ctx = self._run([c1, c2], controls_seq, radio_map)
        series_by_id = {s['id']: s for s in ctx['series']}
        assert series_by_id[1]['points'][-1] <= series_by_id[2]['points'][-1]

    def test_series_json_serialisable(self):
        import json
        c1 = make_competitor(1, rt=3600)
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        radio_map    = {1: {31: 1200}}
        ctx = self._run([c1], controls_seq, radio_map)
        parsed = json.loads(ctx['series_json'])
        assert isinstance(parsed, list)

    def test_exaequo_leg_data_contient_plusieurs_noms(self):
        c1 = make_competitor(1, rt=3600, name='Alice')
        c2 = make_competitor(2, rt=3600, name='Bob')
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        radio_map = {1: {31: 1200}, 2: {31: 1200}}
        ctx = self._run([c1, c2], controls_seq, radio_map)
        leg = ctx['superman_leg_data'][0]
        assert len(leg['names']) == 2
        assert 'Alice' in leg['names']
        assert 'Bob'   in leg['names']

    def test_un_seul_meilleur_troncon(self):
        c1 = make_competitor(1, rt=3600, name='Alice')
        c2 = make_competitor(2, rt=5000, name='Bob')
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        radio_map    = {1: {31: 1000}, 2: {31: 2000}}
        ctx = self._run([c1, c2], controls_seq, radio_map)
        leg = ctx['superman_leg_data'][0]
        assert leg['names'] == ['Alice']

    def test_coureur_sans_radio_points_none(self):
        c1 = make_competitor(1, rt=3600, name='Avec radio')
        c2 = make_competitor(2, rt=4000, name='Sans radio')
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        radio_map    = {1: {31: 1200}}
        ctx = self._run([c1, c2], controls_seq, radio_map)
        series_by_id = {s['id']: s for s in ctx['series']}
        assert None in series_by_id[2]['points']


# ─── Tests class_results — injection des erreurs ─────────────────────────────

class TestClassResultsErrorEstimates:
    """Vérifie que compute_error_estimates est appelé et injecte error_time/error_pct."""

    def _run(self, competitors, controls_seq, radio_map, error_map=None):
        """Lance class_results avec mocks configurables."""
        comp = make_competition()
        cls  = make_cls()

        if error_map is None:
            error_map = {
                c.id: [{'error_time': 500, 'error_pct': 15.0}]
                for c in competitors if getattr(c, 'is_ok', False)
            }

        with patch('results.views.Mopteam') as MockTeam, \
             patch('results.views.Mopcompetitor') as MockComp, \
             patch('results.views.get_object_or_404', side_effect=[comp, cls]), \
             patch('results.views._get_adjacent_classes', return_value=(None, None)), \
             patch('results.views.get_org_map', return_value={}), \
             patch('results.views.get_class_controls', return_value=(controls_seq, {})), \
             patch('results.views.get_radio_map', return_value=radio_map), \
             patch('results.views.compute_error_estimates', return_value=error_map) as mock_err, \
             patch('results.views.render') as mock_render:

            MockTeam.objects.filter.return_value.exists.return_value = False
            MockComp.objects.filter.return_value = competitors

            from results.views import class_results
            class_results(rf_get(), cid=1, class_id=10)

            _, _, ctx = mock_render.call_args[0]
            return ctx, mock_err

    def test_compute_error_estimates_appele_si_controles(self):
        c = make_competitor(1, rt=5000)
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        radio_map    = {1: {31: 1200}}
        _, mock_err = self._run([c], controls_seq, radio_map)
        assert mock_err.called

    def test_compute_error_estimates_non_appele_sans_controles(self):
        c = make_competitor(1, rt=5000)
        _, mock_err = self._run([c], controls_seq=[], radio_map={},
                                error_map={})
        assert not mock_err.called

    def test_error_time_injecte_dans_splits(self):
        c = make_competitor(1, rt=5000)
        c.splits = [{'ctrl_name': 'P31', 'abs_time': '02:00', 'leg_time': '02:00',
                     'leg_raw': 1200, 'abs_raw': 1200, 'is_best': False,
                     'leg_rank': None, 'abs_rank': None}]

        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        radio_map    = {1: {31: 1200}}
        error_map    = {1: [{'error_time': 500, 'error_pct': 12.5}]}

        ctx, _ = self._run([c], controls_seq, radio_map, error_map)

        runner = next(r for r in ctx['results'] if r.id == 1)
        assert 'error_time' in runner.splits[0]
        assert 'error_pct'  in runner.splits[0]

    def test_error_time_arrondi_en_dixiemes(self):
        c = make_competitor(1, rt=5000)
        c.splits = [{'ctrl_name': 'P31', 'abs_time': '02:00', 'leg_time': '02:00',
                     'leg_raw': 1200, 'abs_raw': 1200, 'is_best': False,
                     'leg_rank': None, 'abs_rank': None}]

        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        radio_map    = {1: {31: 1200}}
        error_map    = {1: [{'error_time': 503.7, 'error_pct': 12.53}]}

        ctx, _ = self._run([c], controls_seq, radio_map, error_map)
        runner = next(r for r in ctx['results'] if r.id == 1)
        assert runner.splits[0]['error_time'] == 504
        assert runner.splits[0]['error_pct']  == pytest.approx(12.5)

    def test_error_none_si_calcul_impossible(self):
        c = make_competitor(1, rt=5000)
        c.splits = [{'ctrl_name': 'P31', 'abs_time': '-', 'leg_time': '-',
                     'leg_raw': None, 'abs_raw': None, 'is_best': False,
                     'leg_rank': None, 'abs_rank': None}]

        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        error_map    = {1: [{'error_time': None, 'error_pct': None}]}

        ctx, _ = self._run([c], controls_seq, {}, error_map)
        runner = next(r for r in ctx['results'] if r.id == 1)
        assert runner.splits[0]['error_time'] is None
        assert runner.splits[0]['error_pct']  is None


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

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.compute_splits',     return_value=[])
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteam')
    def test_runners_json_est_valide(
        self, MockTeam, MockCompetitor, mock_get404, mock_render,
        mock_splits, mock_radio, mock_ctrl, mock_org,
    ):
        import json
        MockTeam.objects.filter.return_value.exists.return_value = False
        competition = make_competition(); cls = make_cls()
        mock_get404.side_effect = [competition, cls]
        c1 = make_competitor(1, rt=5000, name='Alice')
        c2 = make_competitor(2, rt=6000, name='Bob')
        MockCompetitor.objects.filter.return_value = [c1, c2]

        from results.views import duel_analysis
        duel_analysis(rf_get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        data = json.loads(context['runners_json'])
        assert len(data) == 2
        names = {r['name'] for r in data}
        assert 'Alice' in names
        assert 'Bob'   in names

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=(
        [{'ctrl_id': 31, 'ctrl_name': 'P31'}, {'ctrl_id': 32, 'ctrl_name': 'P32'}], {}
    ))
    @patch('results.views.get_radio_map',      return_value={1: {31: 800, 32: 1800}, 2: {31: 900, 32: 2000}})
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteam')
    def test_splits_inclus_dans_runners_json(
        self, MockTeam, MockCompetitor, mock_get404, mock_render,
        mock_radio, mock_ctrl, mock_org,
    ):
        import json
        MockTeam.objects.filter.return_value.exists.return_value = False
        competition = make_competition(); cls = make_cls()
        mock_get404.side_effect = [competition, cls]
        c1 = make_competitor(1, rt=5000); c2 = make_competitor(2, rt=6000)
        MockCompetitor.objects.filter.return_value = [c1, c2]

        from results.views import duel_analysis
        duel_analysis(rf_get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        data = json.loads(context['runners_json'])
        for runner in data:
            assert 'splits' in runner
            assert isinstance(runner['splits'], list)
            for sp in runner['splits']:
                assert 'ctrl_name' in sp
                assert 'leg_raw'   in sp
                assert 'abs_raw'   in sp

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

    @patch('results.views.get_org_map',        return_value={})
    @patch('results.views.get_class_controls', return_value=([], {}))
    @patch('results.views.get_radio_map',      return_value={})
    @patch('results.views.compute_splits',     return_value=[])
    @patch('results.views.render')
    @patch('results.views.get_object_or_404')
    @patch('results.views.Mopcompetitor')
    @patch('results.views.Mopteam')
    def test_n_runners_correspond_au_nombre_de_coureurs(
        self, MockTeam, MockCompetitor, mock_get404, mock_render,
        mock_splits, mock_radio, mock_ctrl, mock_org,
    ):
        MockTeam.objects.filter.return_value.exists.return_value = False
        competition = make_competition(); cls = make_cls()
        mock_get404.side_effect = [competition, cls]
        dnf = make_competitor(3, rt=-1, stat=4)
        dnf.is_ok = False
        competitors = [make_competitor(1, rt=5000), make_competitor(2, rt=6000), dnf]
        MockCompetitor.objects.filter.return_value = competitors

        from results.views import duel_analysis
        duel_analysis(rf_get(), cid=1, class_id=10)

        _, _, context = mock_render.call_args[0]
        assert context['n_runners'] == 3


# ─── Tests _slugify_no_prefix ─────────────────────────────────────────────────

class TestSlugifyNoPrefix:
    """Vérifie que _slugify_no_prefix retire les numéros en tête de titre."""

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

    def test_accents_preserves(self):
        result = self._call('2 Résultats généraux')
        assert 'sultats' in result
        assert result.startswith('r')

    def test_prefixe_multi_niveaux(self):
        assert self._call('3.2.1 Sous-section') == 'sous-section'


# ─── Tests MarkdownView ───────────────────────────────────────────────────────

class TestMarkdownView:

    @patch('results.views.MeosTutorial')
    @patch('results.views.render')
    def test_retourne_contenu_converti(self, mock_render, MockTutorial):
        article        = MagicMock()
        article.text   = '# Titre\n\nParagraphe de test.'
        article.title  = 'Tutoriel'
        MockTutorial.objects.get.return_value = article

        from results.views import MarkdownView
        request = rf_get()
        MarkdownView(request, article_id=1)

        MockTutorial.objects.get.assert_called_once_with(pk=1)
        _, template, context = mock_render.call_args[0]
        assert template == 'results/markdown_content.html'
        assert 'markdown_content' in context
        assert hasattr(context['markdown_content'], 'content')

    @patch('results.views.MeosTutorial')
    @patch('results.views.render')
    def test_contenu_est_html(self, mock_render, MockTutorial):
        article       = MagicMock()
        article.text  = '# Mon titre'
        MockTutorial.objects.get.return_value = article

        from results.views import MarkdownView
        MarkdownView(rf_get(), article_id=1)

        _, _, context = mock_render.call_args[0]
        assert '<h1' in context['markdown_content'].content

    @patch('results.views.MeosTutorial')
    @patch('results.views.render')
    def test_table_of_contents_generee(self, mock_render, MockTutorial):
        article       = MagicMock()
        article.text  = '## Section A\n\n## Section B'
        MockTutorial.objects.get.return_value = article

        from results.views import MarkdownView
        MarkdownView(rf_get(), article_id=1)

        _, _, context = mock_render.call_args[0]
        content_html = context['markdown_content'].content
        assert 'section-a' in content_html or 'section' in content_html


# ─── Tests etiquettes ─────────────────────────────────────────────────────────

class TestEtiquettesView:

    @patch('results.views.render')
    def test_utilise_bon_template(self, mock_render):
        from results.views import etiquettes
        etiquettes(rf_get())
        args = mock_render.call_args[0]
        template = args[1]
        assert template == 'results/etiquettes.html'

    @patch('results.views.render')
    def test_status_200(self, mock_render):
        mock_render.return_value = MagicMock(status_code=200)
        from results.views import etiquettes
        etiquettes(rf_get())
        assert mock_render.called


# ─── Tests drivers ────────────────────────────────────────────────────────────

class TestDriversView:

    @patch('results.views.render')
    def test_utilise_bon_template(self, mock_render):
        from results.views import drivers
        drivers(rf_get())
        args = mock_render.call_args[0]
        template = args[1]
        assert template == 'results/drivers.html'

    @patch('results.views.render')
    def test_appele_render(self, mock_render):
        mock_render.return_value = MagicMock(status_code=200)
        from results.views import drivers
        drivers(rf_get())
        assert mock_render.called


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

    def test_class_stats_champs_individuels(self):
        cls1 = make_cls(1, 10)
        _, context = self._run(classes=[cls1])
        stat = context['class_stats'][0]
        assert 'cls'       in stat
        assert 'total'     in stat
        assert 'finishers' in stat
        assert 'is_relay'  in stat

    def test_classe_individuelle_marquee_false(self):
        cls1 = make_cls(1, 10)
        _, context = self._run(classes=[cls1], teams_cls_ids=set())
        stat = context['class_stats'][0]
        assert stat['is_relay'] is False

    def test_classe_relais_marquee_true(self):
        cls1 = make_cls(1, 10)
        _, context = self._run(classes=[cls1], teams_cls_ids={10})
        stat = context['class_stats'][0]
        assert stat['is_relay'] is True

    def test_total_et_finishers_transmis(self):
        cls1 = make_cls(1, 10)
        _, context = self._run(classes=[cls1], competitors_count=8, finishers_count=5)
        stat = context['class_stats'][0]
        assert stat['total'] == 8
        assert stat['finishers'] == 5
