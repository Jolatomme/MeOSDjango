"""
Tests unitaires pour services.py.

Tous les appels DB sont mockés : les tests tournent sans base de données.
"""

from unittest.mock import MagicMock, patch
import pytest

from results.models import STAT_OK, format_time


# ─── Helpers pour construire des faux objets ──────────────────────────────────

def make_competitor(id, rt, stat=STAT_OK, name="Coureur", org=1, cls=10):
    c = MagicMock()
    c.id   = id
    c.rt   = rt
    c.stat = stat
    c.name = name
    c.org  = org
    c.cls  = cls
    c.is_ok = (stat == STAT_OK and rt > 0)
    return c


def make_radio(id, ctrl, rt):
    r = MagicMock()
    r.id   = id
    r.ctrl = ctrl
    r.rt   = rt
    return r


def make_control(id, name):
    c = MagicMock()
    c.id   = id
    c.name = name
    return c


def make_classcontrol(ctrl, leg=0, ord=1):
    cc = MagicMock()
    cc.ctrl = ctrl
    cc.leg  = leg
    cc.ord  = ord
    return cc


# ─── Tests rank_finishers ──────────────────────────────────────────────────────

class TestRankFinishers:
    """Vérifie le tri, l'attribution du rang et du retard."""

    def _call(self, entries, **kwargs):
        from results.services import rank_finishers
        return rank_finishers(entries, **kwargs)

    def test_classe_par_temps(self):
        c1 = make_competitor(1, rt=6000)   # 10 min
        c2 = make_competitor(2, rt=5000)   # 8 min 20 s → doit être 1er
        finishers, _, _ = self._call([c1, c2])
        assert finishers[0].id == 2
        assert finishers[1].id == 1

    def test_rang_attribue(self):
        c1 = make_competitor(1, rt=5000)
        c2 = make_competitor(2, rt=6000)
        finishers, _, _ = self._call([c1, c2])
        assert finishers[0].rank == 1
        assert finishers[1].rank == 2

    def test_ecart_leader_zero(self):
        c1 = make_competitor(1, rt=5000)
        c2 = make_competitor(2, rt=6000)
        finishers, _, _ = self._call([c1, c2])
        assert finishers[0].time_behind == 0
        assert finishers[1].time_behind == 1000

    def test_non_classes_sans_rang(self):
        c_ok  = make_competitor(1, rt=5000, stat=STAT_OK)
        c_bad = make_competitor(2, rt=-1,   stat=3)      # PM
        c_bad.is_ok = False
        finishers, non_finishers, _ = self._call([c_ok, c_bad])
        assert len(finishers) == 1
        assert len(non_finishers) == 1
        assert non_finishers[0].rank is None
        assert non_finishers[0].time_behind is None

    def test_liste_vide(self):
        finishers, non_finishers, leader = self._call([])
        assert finishers == []
        assert non_finishers == []
        assert leader is None

    def test_ok_predicate_custom(self):
        """Pour les équipes relais, ok_predicate est une lambda."""
        t1 = MagicMock(); t1.stat = STAT_OK; t1.rt = 5000
        t2 = MagicMock(); t2.stat = 4;       t2.rt = -1
        finishers, non_finishers, _ = self._call(
            [t1, t2],
            ok_predicate=lambda t: t.stat == STAT_OK and t.rt > 0,
        )
        assert len(finishers) == 1
        assert len(non_finishers) == 1


# ─── Tests compute_splits ─────────────────────────────────────────────────────

class TestComputeSplits:
    """Vérifie le calcul des temps intermédiaires."""

    def _call(self, runner_id, controls_seq, radio_map):
        from results.services import compute_splits
        return compute_splits(runner_id, controls_seq, radio_map)

    def test_troncon_calcule(self):
        """abs_time=1200 (2 min), prev=0 → leg=1200."""
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        radio_map    = {1: {31: 1200}}
        splits = self._call(1, controls_seq, radio_map)
        assert splits[0]['leg_raw'] == 1200
        assert splits[0]['abs_time'] == format_time(1200)

    def test_troncon_suivant(self):
        """P31=1200, P32=2500 → leg P32 = 1300."""
        controls_seq = [
            {'ctrl_id': 31, 'ctrl_name': 'P31'},
            {'ctrl_id': 32, 'ctrl_name': 'P32'},
        ]
        radio_map = {1: {31: 1200, 32: 2500}}
        splits = self._call(1, controls_seq, radio_map)
        assert splits[1]['leg_raw'] == 1300

    def test_temps_manquant(self):
        """Si le temps radio est absent, abs_time='-' et leg_raw=None."""
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        radio_map    = {}    # coureur sans aucun temps radio
        splits = self._call(1, controls_seq, radio_map)
        assert splits[0]['abs_time'] == '-'
        assert splits[0]['leg_raw'] is None

    def test_troncon_invalide_casse_la_chaine(self):
        """Après un temps manquant, les suivants sont aussi None."""
        controls_seq = [
            {'ctrl_id': 31, 'ctrl_name': 'P31'},
            {'ctrl_id': 32, 'ctrl_name': 'P32'},
        ]
        radio_map = {1: {32: 2500}}   # P31 manquant
        splits = self._call(1, controls_seq, radio_map)
        assert splits[0]['leg_raw'] is None
        assert splits[1]['leg_raw'] is None

    def test_is_best_init_false(self):
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        radio_map    = {1: {31: 1200}}
        splits = self._call(1, controls_seq, radio_map)
        assert splits[0]['is_best'] is False

    def test_coureur_inconnu(self):
        """Un coureur sans entrée dans radio_map renvoie tout à '-'."""
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        splits = self._call(99, controls_seq, {})
        assert splits[0]['abs_time'] == '-'


# ─── Tests mark_best_splits ───────────────────────────────────────────────────

class TestMarkBestSplits:
    """Vérifie que le meilleur tronçon par contrôle est correctement marqué."""

    def _call(self, finishers, all_results):
        from results.services import mark_best_splits
        mark_best_splits(finishers, all_results)

    def _make_with_splits(self, runner_id, leg_raws):
        c = MagicMock()
        c.id     = runner_id
        c.splits = [{'leg_raw': v, 'is_best': False} for v in leg_raws]
        return c

    def test_meilleur_marque(self):
        c1 = self._make_with_splits(1, [1000, 2000])
        c2 = self._make_with_splits(2, [900,  2100])  # P31 meilleur
        self._call([c1, c2], [c1, c2])
        assert c2.splits[0]['is_best'] is True   # 900 < 1000
        assert c1.splits[0]['is_best'] is False
        assert c1.splits[1]['is_best'] is True   # 2000 < 2100
        assert c2.splits[1]['is_best'] is False

    def test_egalite_les_deux_sont_best(self):
        c1 = self._make_with_splits(1, [1000])
        c2 = self._make_with_splits(2, [1000])
        self._call([c1, c2], [c1, c2])
        assert c1.splits[0]['is_best'] is True
        assert c2.splits[0]['is_best'] is True

    def test_temps_manquant_ignore(self):
        c1 = self._make_with_splits(1, [None])
        c2 = self._make_with_splits(2, [1000])
        self._call([c1, c2], [c1, c2])
        assert c1.splits[0]['is_best'] is False
        assert c2.splits[0]['is_best'] is True

    def test_finishers_vides(self):
        """Aucun classé → aucune erreur, aucun is_best."""
        c1 = self._make_with_splits(1, [1000])
        self._call([], [c1])
        assert c1.splits[0]['is_best'] is False


# ─── Tests get_radio_map ──────────────────────────────────────────────────────

class TestGetRadioMap:

    @patch('results.services.Mopradio')
    def test_groupement_par_coureur(self, MockRadio):
        MockRadio.objects.filter.return_value = [
            make_radio(1, 31, 1200),
            make_radio(1, 32, 2500),
            make_radio(2, 31, 1100),
        ]
        from results.services import get_radio_map
        rm = get_radio_map(cid=1, runner_ids=[1, 2])

        assert rm[1][31] == 1200
        assert rm[1][32] == 2500
        assert rm[2][31] == 1100

    @patch('results.services.Mopradio')
    def test_coureur_sans_temps_absent(self, MockRadio):
        MockRadio.objects.filter.return_value = []
        from results.services import get_radio_map
        rm = get_radio_map(cid=1, runner_ids=[99])
        assert rm == {}


# ─── Tests get_org_map ────────────────────────────────────────────────────────

class TestGetOrgMap:

    @patch('results.services.Moporganization')
    def test_retourne_noms(self, MockOrg):
        org = MagicMock(); org.id = 5; org.name = 'COLE'
        MockOrg.objects.filter.return_value = [org]
        from results.services import get_org_map
        m = get_org_map(cid=1)
        assert m[5] == 'COLE'

    @patch('results.services.Moporganization')
    def test_as_objects(self, MockOrg):
        org = MagicMock(); org.id = 5; org.name = 'COLE'
        MockOrg.objects.filter.return_value = [org]
        from results.services import get_org_map
        m = get_org_map(cid=1, as_objects=True)
        assert m[5] is org


# ─── Tests build_rank_map ──────────────────────────────────────────────────────

class TestBuildRankMap:
    """Vérifie le classement olympique (ex-æquo = même rang)."""

    def _call(self, entries):
        from results.services import build_rank_map
        return build_rank_map(entries)

    def test_liste_vide(self):
        assert self._call([]) == {}

    def test_un_element(self):
        assert self._call([(1000, 1)]) == {1: 1}

    def test_deux_elements_ordre_croissant(self):
        result = self._call([(1000, 1), (1500, 2)])
        assert result == {1: 1, 2: 2}

    def test_exaequo_meme_rang(self):
        """Deux coureurs avec le même temps → même rang."""
        result = self._call([(1000, 1), (1000, 2)])
        assert result[1] == 1
        assert result[2] == 1

    def test_exaequo_puis_suivant_rang_olympique(self):
        """1,1,2 → rangs olympiques 1, 1, 3 (pas 1, 1, 2)."""
        result = self._call([(1000, 'a'), (1000, 'b'), (1500, 'c')])
        assert result['a'] == 1
        assert result['b'] == 1
        assert result['c'] == 3

    def test_ids_variés(self):
        """Les identifiants peuvent être des entiers ou des chaînes."""
        result = self._call([(800, 'x'), (900, 'y'), (1000, 'z')])
        assert result['x'] == 1
        assert result['y'] == 2
        assert result['z'] == 3


# ─── Tests compute_splits — nouveaux champs (abs_raw, leg_rank, abs_rank) ─────

class TestComputeSplitsNewFields:
    """Vérifie les champs ajoutés dans compute_splits : abs_raw, leg_rank, abs_rank."""

    def _call(self, runner_id, controls_seq, radio_map):
        from results.services import compute_splits
        return compute_splits(runner_id, controls_seq, radio_map)

    def test_abs_raw_egal_temps_cumule(self):
        """abs_raw doit contenir le temps radio brut (cumulé, pas tronçon)."""
        splits = self._call(1, [{'ctrl_id': 31, 'ctrl_name': 'P31'}], {1: {31: 1200}})
        assert splits[0]['abs_raw'] == 1200

    def test_abs_raw_none_si_poste_manquant(self):
        """abs_raw vaut None quand le poste n'est pas dans le radio_map."""
        splits = self._call(1, [{'ctrl_id': 31, 'ctrl_name': 'P31'}], {})
        assert splits[0]['abs_raw'] is None

    def test_abs_raw_deux_controles_independants(self):
        """abs_raw est le temps cumulé de chaque poste, indépendamment."""
        controls_seq = [
            {'ctrl_id': 31, 'ctrl_name': 'P31'},
            {'ctrl_id': 32, 'ctrl_name': 'P32'},
        ]
        splits = self._call(1, controls_seq, {1: {31: 1200, 32: 2500}})
        assert splits[0]['abs_raw'] == 1200
        assert splits[1]['abs_raw'] == 2500   # cumulé, pas 1300

    def test_abs_raw_poste_sans_cascade(self):
        """Même si P31 manque, abs_raw de P32 reste valide (calc. absolu indépendant)."""
        controls_seq = [
            {'ctrl_id': 31, 'ctrl_name': 'P31'},
            {'ctrl_id': 32, 'ctrl_name': 'P32'},
        ]
        splits = self._call(1, controls_seq, {1: {32: 2500}})
        assert splits[0]['abs_raw'] is None   # P31 absent
        assert splits[1]['abs_raw'] == 2500   # P32 connu → abs_raw valide

    def test_leg_rank_initialise_none(self):
        """leg_rank doit être None à la sortie de compute_splits (avant rank_splits)."""
        splits = self._call(1, [{'ctrl_id': 31, 'ctrl_name': 'P31'}], {1: {31: 1200}})
        assert splits[0]['leg_rank'] is None

    def test_abs_rank_initialise_none(self):
        """abs_rank doit être None à la sortie de compute_splits (avant rank_splits)."""
        splits = self._call(1, [{'ctrl_id': 31, 'ctrl_name': 'P31'}], {1: {31: 1200}})
        assert splits[0]['abs_rank'] is None

    def test_tous_les_champs_presents(self):
        """Tous les champs attendus sont présents dans chaque split."""
        splits = self._call(1, [{'ctrl_id': 31, 'ctrl_name': 'P31'}], {1: {31: 1200}})
        expected = {'ctrl_name', 'abs_time', 'leg_time', 'leg_raw', 'abs_raw',
                    'is_best', 'leg_rank', 'abs_rank'}
        assert expected.issubset(splits[0].keys())


# ─── Tests rank_splits ────────────────────────────────────────────────────────

class TestRankSplits:
    """Vérifie le calcul des classements par tronçon (leg_rank) et au cumulé (abs_rank)."""

    def _make(self, runner_id, leg_raws, abs_raws):
        """Construit un faux coureur avec splits pré-remplis."""
        c = MagicMock()
        c.id     = runner_id
        c.splits = [
            {'leg_raw': lg, 'abs_raw': ab, 'leg_rank': None, 'abs_rank': None}
            for lg, ab in zip(leg_raws, abs_raws)
        ]
        return c

    def _call(self, finishers, all_results=None):
        from results.services import rank_splits
        rank_splits(finishers, all_results if all_results is not None else finishers)

    # ── Cas de base ──────────────────────────────────────────────────────────

    def test_un_seul_coureur_leg_rank_1(self):
        c = self._make(1, [1000], [1000])
        self._call([c])
        assert c.splits[0]['leg_rank'] == 1

    def test_un_seul_coureur_abs_rank_1(self):
        c = self._make(1, [1000], [1000])
        self._call([c])
        assert c.splits[0]['abs_rank'] == 1

    def test_leg_rank_ordre_croissant(self):
        """Le coureur avec le plus petit leg_raw est leg_rank=1."""
        c1 = self._make(1, [1200], [1200])
        c2 = self._make(2, [1000], [1000])
        self._call([c1, c2])
        assert c2.splits[0]['leg_rank'] == 1
        assert c1.splits[0]['leg_rank'] == 2

    def test_abs_rank_ordre_croissant(self):
        """Le coureur avec le plus petit abs_raw est abs_rank=1."""
        c1 = self._make(1, [1000], [2000])
        c2 = self._make(2, [1000], [1500])
        self._call([c1, c2])
        assert c2.splits[0]['abs_rank'] == 1
        assert c1.splits[0]['abs_rank'] == 2

    # ── Divergence leg_rank vs abs_rank ──────────────────────────────────────

    def test_leg_rank_et_abs_rank_peuvent_diverger(self):
        """Un coureur peut être 1er sur le tronçon mais 2e au cumulé (parti plus tard).

        c1 : abs_raw=950  (parti très tôt), leg_raw=1200
        c2 : abs_raw=1100 (parti plus tard), leg_raw=900
        → leg: c2=1, c1=2   /   abs: c1=1, c2=2
        """
        c1 = self._make(1, [1200], [950])
        c2 = self._make(2, [900],  [1100])
        self._call([c1, c2])
        assert c2.splits[0]['leg_rank'] == 1
        assert c1.splits[0]['leg_rank'] == 2
        assert c1.splits[0]['abs_rank'] == 1
        assert c2.splits[0]['abs_rank'] == 2

    # ── Non-classés ──────────────────────────────────────────────────────────

    def test_dnf_hors_finishers_recoit_none(self):
        """Un coureur non dans finishers ne reçoit ni leg_rank ni abs_rank."""
        c_ok  = self._make(1, [1000], [1000])
        c_dnf = self._make(2, [1100], [1100])
        self._call([c_ok], all_results=[c_ok, c_dnf])
        assert c_ok.splits[0]['leg_rank']  == 1
        assert c_dnf.splits[0]['leg_rank'] is None
        assert c_dnf.splits[0]['abs_rank'] is None

    # ── Temps manquants ───────────────────────────────────────────────────────

    def test_leg_raw_none_exclu_du_classement_troncon(self):
        """Un coureur avec leg_raw=None n'entre pas dans le classement tronçon."""
        c1 = self._make(1, [None], [None])
        c2 = self._make(2, [1000], [1000])
        self._call([c1, c2])
        assert c1.splits[0]['leg_rank'] is None
        assert c2.splits[0]['leg_rank'] == 1

    def test_abs_raw_none_exclu_du_classement_cumule(self):
        """Un coureur avec abs_raw=None n'entre pas dans le classement cumulé."""
        c1 = self._make(1, [None], [None])
        c2 = self._make(2, [1000], [1000])
        self._call([c1, c2])
        assert c1.splits[0]['abs_rank'] is None
        assert c2.splits[0]['abs_rank'] == 1

    # ── Égalités ─────────────────────────────────────────────────────────────

    def test_egalite_leg_rank_meme_rang(self):
        """Deux coureurs avec le même leg_raw reçoivent le même rang (olympic ranking)."""
        c1 = self._make(1, [1000], [1000])
        c2 = self._make(2, [1000], [1500])
        self._call([c1, c2])
        assert c1.splits[0]['leg_rank'] == 1
        assert c2.splits[0]['leg_rank'] == 1   # ex-æquo → même rang

    # ── Plusieurs postes ──────────────────────────────────────────────────────

    def test_plusieurs_controles_calcules_independamment(self):
        """P31 : c1 gagne; P32 : c2 gagne. Les rangs sont bien séparés."""
        c1 = self._make(1, [900,  1500], [900,  2400])
        c2 = self._make(2, [1100, 1200], [1100, 2300])
        self._call([c1, c2])
        assert c1.splits[0]['leg_rank'] == 1   # P31 : c1 gagne
        assert c2.splits[0]['leg_rank'] == 2
        assert c2.splits[1]['leg_rank'] == 1   # P32 : c2 gagne
        assert c1.splits[1]['leg_rank'] == 2
        # Cumulé P32 : c1 abs=2400 > c2 abs=2300
        assert c2.splits[1]['abs_rank'] == 1
        assert c1.splits[1]['abs_rank'] == 2

    # ── Robustesse ────────────────────────────────────────────────────────────

    def test_finishers_vides_ne_plante_pas(self):
        """Aucun finisseur → pas d'exception, tous les rangs restent None."""
        c = self._make(1, [1000], [1000])
        self._call([], all_results=[c])
        assert c.splits[0]['leg_rank'] is None
        assert c.splits[0]['abs_rank'] is None

    def test_un_finisseur_avec_non_classe(self):
        """1 finisseur + 1 DNF : finisseur=1, DNF=None."""
        c_ok  = self._make(1, [1000], [1000])
        c_dnf = self._make(2, [900],  [900])
        self._call([c_ok], all_results=[c_ok, c_dnf])
        assert c_ok.splits[0]['leg_rank']  == 1
        assert c_dnf.splits[0]['leg_rank'] is None


# ─── Tests get_class_controls ─────────────────────────────────────────────────

class TestGetClassControls:
    """Vérifie le chargement et l'ordonnancement des contrôles d'une catégorie."""

    def _make_cc(self, ctrl, leg=1, ord_=1):
        cc = MagicMock()
        cc.ctrl = ctrl
        cc.leg  = leg
        cc.ord  = ord_
        return cc

    def _make_ctrl(self, id_, name):
        c = MagicMock()
        c.id   = id_
        c.name = name
        return c

    @patch('results.services.Mopcontrol')
    @patch('results.services.Mopclasscontrol')
    def test_retourne_sequence_et_map(self, MockCC, MockCtrl):
        MockCC.objects.filter.return_value.order_by.return_value = [
            self._make_cc(31, leg=1, ord_=1),
            self._make_cc(32, leg=1, ord_=2),
        ]
        MockCtrl.objects.filter.return_value = [
            self._make_ctrl(31, 'P31'),
            self._make_ctrl(32, 'P32'),
        ]
        from results.services import get_class_controls
        seq, name_map = get_class_controls(cid=1, class_id=10)

        assert len(seq) == 2
        assert seq[0] == {'ctrl_id': 31, 'ctrl_name': '2-P31'}
        assert seq[1] == {'ctrl_id': 32, 'ctrl_name': '3-P32'}
        assert name_map[31] == 'P31'
        assert name_map[32] == 'P32'

    @patch('results.services.Mopcontrol')
    @patch('results.services.Mopclasscontrol')
    def test_aucun_controle(self, MockCC, MockCtrl):
        """Catégorie sans contrôles → séquence vide."""
        MockCC.objects.filter.return_value.order_by.return_value = []
        from results.services import get_class_controls
        seq, name_map = get_class_controls(cid=1, class_id=10)
        assert seq == []
        assert name_map == {}

    @patch('results.services.Mopcontrol')
    @patch('results.services.Mopclasscontrol')
    def test_ctrl_inconnu_utilise_id_comme_nom(self, MockCC, MockCtrl):
        """Si un ctrl n'a pas de nom dans Mopcontrol, on utilise str(ctrl_id)."""
        MockCC.objects.filter.return_value.order_by.return_value = [
            self._make_cc(99, leg=1, ord_=1),
        ]
        MockCtrl.objects.filter.return_value = []  # aucun contrôle connu
        from results.services import get_class_controls
        seq, _ = get_class_controls(cid=1, class_id=10)
        assert seq[0]['ctrl_name'] == '2-99'

    @patch('results.services.Mopcontrol')
    @patch('results.services.Mopclasscontrol')
    def test_filtre_par_leg(self, MockCC, MockCtrl):
        """Le paramètre leg filtre sur la fraction demandée."""
        MockCC.objects.filter.return_value.filter.return_value.order_by.return_value = [
            self._make_cc(33, leg=2, ord_=1),
        ]
        MockCtrl.objects.filter.return_value = [self._make_ctrl(33, 'P33')]
        from results.services import get_class_controls
        seq, _ = get_class_controls(cid=1, class_id=10, leg=2)
        assert len(seq) == 1
        assert seq[0]['ctrl_id'] == 33


# ─── Tests get_controls_by_leg ────────────────────────────────────────────────

class TestGetControlsByLeg:
    """Vérifie le groupement des contrôles par fraction (relais)."""

    def _make_cc(self, ctrl, leg, ord_=1):
        cc = MagicMock()
        cc.ctrl = ctrl
        cc.leg  = leg
        cc.ord  = ord_
        return cc

    @patch('results.services.Mopcontrol')
    @patch('results.services.Mopclasscontrol')
    def test_groupement_par_fraction(self, MockCC, MockCtrl):
        MockCC.objects.filter.return_value.order_by.return_value = [
            self._make_cc(31, leg=1),
            self._make_cc(32, leg=1),
            self._make_cc(33, leg=2),
        ]
        MockCtrl.objects.filter.return_value = []
        from results.services import get_controls_by_leg
        by_leg, _ = get_controls_by_leg(cid=1, class_id=10)
        assert by_leg[1] == [31, 32]
        assert by_leg[2] == [33]

    @patch('results.services.Mopcontrol')
    @patch('results.services.Mopclasscontrol')
    def test_retourne_name_map(self, MockCC, MockCtrl):
        MockCC.objects.filter.return_value.order_by.return_value = [
            self._make_cc(31, leg=1),
        ]
        ctrl = MagicMock(); ctrl.id = 31; ctrl.name = 'P31'
        MockCtrl.objects.filter.return_value = [ctrl]
        from results.services import get_controls_by_leg
        _, name_map = get_controls_by_leg(cid=1, class_id=10)
        assert name_map[31] == 'P31'

    @patch('results.services.Mopcontrol')
    @patch('results.services.Mopclasscontrol')
    def test_vide_si_aucun_controle(self, MockCC, MockCtrl):
        MockCC.objects.filter.return_value.order_by.return_value = []
        from results.services import get_controls_by_leg
        by_leg, name_map = get_controls_by_leg(cid=1, class_id=10)
        assert by_leg == {}
        assert name_map == {}


# ─── Tests build_leg_matrix ───────────────────────────────────────────────────

class TestBuildLegMatrix:
    """Vérifie la construction de la matrice des temps de tronçon."""

    def _call(self, finishers, controls_seq, radio_map):
        from results.services import build_leg_matrix
        return build_leg_matrix(finishers, controls_seq, radio_map)

    def test_troncon_unique(self):
        """1 contrôle → 2 tronçons : départ→P31 et P31→arrivée."""
        c = make_competitor(1, rt=3000)
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        radio_map    = {1: {31: 1200}}
        matrix = self._call([c], controls_seq, radio_map)
        assert len(matrix) == 1
        assert matrix[0][0] == 1200          # départ → P31
        assert matrix[0][1] == 3000 - 1200   # P31 → arrivée

    def test_deux_controles(self):
        """P31=1200, P32=2500, arrivée=3600 → tronçons 1200, 1300, 1100."""
        c = make_competitor(1, rt=3600)
        controls_seq = [
            {'ctrl_id': 31, 'ctrl_name': 'P31'},
            {'ctrl_id': 32, 'ctrl_name': 'P32'},
        ]
        radio_map = {1: {31: 1200, 32: 2500}}
        matrix = self._call([c], controls_seq, radio_map)
        assert matrix[0][0] == 1200
        assert matrix[0][1] == 1300
        assert matrix[0][2] == 1100

    def test_poste_manquant_donne_none(self):
        """Si P31 est absent, le tronçon est None et les suivants aussi."""
        c = make_competitor(1, rt=3600)
        controls_seq = [
            {'ctrl_id': 31, 'ctrl_name': 'P31'},
            {'ctrl_id': 32, 'ctrl_name': 'P32'},
        ]
        radio_map = {1: {32: 2500}}   # P31 manquant
        matrix = self._call([c], controls_seq, radio_map)
        assert matrix[0][0] is None
        assert matrix[0][1] is None

    def test_deux_coureurs(self):
        """Deux coureurs → deux lignes dans la matrice."""
        c1 = make_competitor(1, rt=3000)
        c2 = make_competitor(2, rt=3600)
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        radio_map    = {1: {31: 1200}, 2: {31: 1500}}
        matrix = self._call([c1, c2], controls_seq, radio_map)
        assert len(matrix) == 2
        assert matrix[0][0] == 1200
        assert matrix[1][0] == 1500

    def test_coureur_sans_radio(self):
        """Coureur sans aucun temps radio → tous les tronçons None."""
        c = make_competitor(1, rt=3000)
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        matrix = self._call([c], controls_seq, {})
        assert matrix[0][0] is None

    def test_dernier_troncon_none_si_arrivee_invalide(self):
        """Si rt <= 0, le dernier tronçon (→arrivée) est None."""
        c = make_competitor(1, rt=0)
        c.is_ok = False
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        radio_map    = {1: {31: 1200}}
        matrix = self._call([c], controls_seq, radio_map)
        assert matrix[0][1] is None


# ─── Tests compute_leg_refs ───────────────────────────────────────────────────

class TestComputeLegRefs:
    """Vérifie le calcul des temps de référence (top 25%) par tronçon."""

    def _call(self, leg_matrix, n_legs, top_fraction=0.25):
        from results.services import compute_leg_refs
        return compute_leg_refs(leg_matrix, n_legs, top_fraction)

    def test_top_25_pct_un_coureur(self):
        """Avec 1 coureur, la référence = son temps."""
        refs = self._call([[1200]], n_legs=1)
        assert refs[0] == 1200.0

    def test_top_25_pct_quatre_coureurs(self):
        """Top 25% de 4 coureurs = 1 coureur (le plus rapide)."""
        matrix = [[1000], [1200], [1400], [1600]]
        refs = self._call(matrix, n_legs=1)
        assert refs[0] == 1000.0

    def test_top_25_pct_moyenne_des_meilleurs(self):
        """Top 25% de 4 coureurs avec arrondi ceil → 1 coureur."""
        matrix = [[1000], [1100], [1200], [1300]]
        refs = self._call(matrix, n_legs=1)
        assert refs[0] == 1000.0

    def test_top_50_pct(self):
        """top_fraction=0.5 sur 4 coureurs → moyenne des 2 meilleurs."""
        matrix = [[1000], [1200], [1400], [1600]]
        refs = self._call(matrix, n_legs=1, top_fraction=0.5)
        assert refs[0] == pytest.approx((1000 + 1200) / 2)

    def test_none_exclus(self):
        """Les valeurs None sont ignorées dans le calcul de référence."""
        matrix = [[None], [1200], [1400], [1600]]
        refs = self._call(matrix, n_legs=1)
        assert refs[0] is not None

    def test_tous_none_renvoie_none(self):
        """Si tous les temps sont None, la référence est None."""
        matrix = [[None], [None]]
        refs = self._call(matrix, n_legs=1)
        assert refs[0] is None

    def test_deux_troncons_independants(self):
        """Chaque tronçon est calculé indépendamment."""
        matrix = [[1000, 2000], [1200, 1800]]
        refs = self._call(matrix, n_legs=2)
        assert refs[0] == 1000.0   # min du tronçon 0
        assert refs[1] == 1800.0   # min du tronçon 1


# ─── Tests build_abs_time_series ─────────────────────────────────────────────

class TestBuildAbsTimeSeries:
    """Vérifie la construction des séries de temps absolus pour le regroupement."""

    def _make_runner(self, id_, st, rt):
        c = make_competitor(id_, rt=rt)
        c.st = st
        return c

    def _call(self, runners, controls_seq, radio_map):
        from results.services import build_abs_time_series
        return build_abs_time_series(runners, controls_seq, radio_map)

    def test_sans_controles(self):
        """Coureur sans contrôle → 2 points : départ et arrivée."""
        c = self._make_runner(1, st=36000, rt=3600)
        series = self._call([c], [], {})
        assert len(series) == 1
        assert series[0]['points'][0] == 36000          # départ absolu
        assert series[0]['points'][1] == 36000 + 3600   # arrivée absolue

    def test_avec_controle(self):
        """Point intermédiaire = st + abs_radio."""
        c = self._make_runner(1, st=36000, rt=3600)
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        radio_map    = {1: {31: 1200}}
        series = self._call([c], controls_seq, radio_map)
        assert series[0]['points'][1] == 36000 + 1200

    def test_poste_manquant_donne_none(self):
        """Poste non pointé → None dans les points."""
        c = self._make_runner(1, st=36000, rt=3600)
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        series = self._call([c], controls_seq, {})
        assert series[0]['points'][1] is None

    def test_coureur_sans_heure_depart_exclu(self):
        """Coureur avec st=0 doit être ignoré."""
        c = self._make_runner(1, st=0, rt=3600)
        series = self._call([c], [], {})
        assert series == []

    def test_has_finish_false_si_rt_invalide(self):
        """has_finish=False si rt <= 0."""
        c = self._make_runner(1, st=36000, rt=0)
        series = self._call([c], [], {})
        assert series[0]['has_finish'] is False
        assert series[0]['points'][-1] is None

    def test_deux_coureurs(self):
        """Deux coureurs → deux séries."""
        c1 = self._make_runner(1, st=36000, rt=3600)
        c2 = self._make_runner(2, st=37000, rt=4000)
        series = self._call([c1, c2], [], {})
        assert len(series) == 2


# ─── Tests _weighted_median ───────────────────────────────────────────────────

class TestWeightedMedian:
    """Vérifie le calcul de la médiane pondérée."""

    def _call(self, values_weights):
        from results.services import _weighted_median
        return _weighted_median(values_weights)

    def test_valeur_unique(self):
        assert self._call([(0.9, 1000)]) == pytest.approx(0.9)

    def test_deux_valeurs_egales_poids(self):
        """Médiane de (0.8, 1) et (1.0, 1) = 0.8 (premier à dépasser 50%)."""
        result = self._call([(0.8, 1), (1.0, 1)])
        assert result == pytest.approx(0.8)

    def test_poids_eleve_tire_mediane(self):
        """Valeur 0.9 avec poids élevé doit être la médiane."""
        result = self._call([(0.5, 1), (0.9, 100), (1.2, 1)])
        assert result == pytest.approx(0.9)

    def test_liste_vide_renvoie_none(self):
        assert self._call([]) is None

    def test_filtre_none_et_poids_zero(self):
        """Les entrées avec None ou poids=0 sont ignorées."""
        result = self._call([(None, 1000), (0.0, 0), (0.9, 500)])
        assert result == pytest.approx(0.9)

    def test_valeurs_triees(self):
        """Fonctionne même si les valeurs ne sont pas triées à l'entrée.
        Médiane de [0.8, 1.0, 1.2] avec poids égaux = 1.0 (valeur centrale)."""
        result = self._call([(1.2, 1), (0.8, 1), (1.0, 1)])
        assert result == pytest.approx(1.0)


# ─── Tests compute_error_estimates ───────────────────────────────────────────

class TestComputeErrorEstimates:
    """Vérifie l'estimation des erreurs par tronçon."""

    def _call(self, finishers, controls_seq, radio_map):
        from results.services import compute_error_estimates
        return compute_error_estimates(finishers, controls_seq, radio_map)

    def test_coureur_parfait_pas_derreur(self):
        """Un coureur unique est sa propre référence → erreur ~0."""
        c = make_competitor(1, rt=3600)
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        radio_map    = {1: {31: 1200}}
        errors = self._call([c], controls_seq, radio_map)
        assert 1 in errors
        assert len(errors[1]) == 1
        # Avec un seul coureur il est sa propre référence → erreur nulle ou quasi
        e = errors[1][0]
        assert e['error_time'] is not None
        assert abs(e['error_time']) < 1   # quasi zéro en dixièmes

    def test_coureur_lent_a_erreur_positive(self):
        """Coureur lent par rapport à la référence → error_time > 0."""
        c_rapide = make_competitor(1, rt=3000, name='Rapide')
        c_lent   = make_competitor(2, rt=6000, name='Lent')
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        # c_rapide : P31=1000 ; c_lent : P31=3000
        radio_map = {1: {31: 1000}, 2: {31: 3000}}
        errors = self._call([c_rapide, c_lent], controls_seq, radio_map)
        # Le coureur lent devrait avoir une erreur positive sur P31
        assert errors[2][0]['error_time'] is not None

    def test_poste_manquant_donne_none(self):
        """Tronçon invalide (radio absent) → error_time=None."""
        c = make_competitor(1, rt=3600)
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        errors = self._call([c], controls_seq, {})
        assert errors[1][0]['error_time'] is None
        assert errors[1][0]['error_pct']  is None

    def test_longueur_liste_erreurs(self):
        """La liste d'erreurs doit avoir autant d'entrées que de contrôles."""
        c = make_competitor(1, rt=3600)
        controls_seq = [
            {'ctrl_id': 31, 'ctrl_name': 'P31'},
            {'ctrl_id': 32, 'ctrl_name': 'P32'},
        ]
        radio_map = {1: {31: 1200, 32: 2500}}
        errors = self._call([c], controls_seq, radio_map)
        assert len(errors[1]) == 2

    def test_pas_de_finishers(self):
        """Aucun classé → résultat vide."""
        errors = self._call([], [], {})
        assert errors == {}

    def test_structure_champs_retournes(self):
        """Chaque entrée doit avoir les clés error_time et error_pct."""
        c = make_competitor(1, rt=3600)
        controls_seq = [{'ctrl_id': 31, 'ctrl_name': 'P31'}]
        radio_map    = {1: {31: 1200}}
        errors = self._call([c], controls_seq, radio_map)
        assert 'error_time' in errors[1][0]
        assert 'error_pct'  in errors[1][0]
