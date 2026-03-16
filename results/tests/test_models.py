"""
Tests unitaires pour les utilitaires de models.py.
Aucune DB requise.
"""

import pytest
from results.models import (
    format_time,
    STATUS_LABELS,
    STAT_UNKNOWN, STAT_OK, STAT_NT, STAT_MP, STAT_DNF,
    STAT_DQ, STAT_OT, STAT_OCC, STAT_DNS, STAT_CANCEL, STAT_NP,
    Mopcompetition, Mopclass, Moporganization, Mopcompetitor,
    Mopcontrol, MeosTutorial,
)
from unittest.mock import MagicMock


# ─── Tests format_time ────────────────────────────────────────────────────────

class TestFormatTime:
    """format_time convertit des dixièmes de seconde en chaîne lisible."""

    def test_minutes_secondes(self):
        # 3660 dixièmes = 366 s = 6 min 6 s
        assert format_time(3660) == "06:06"

    def test_avec_dixieme(self):
        # 6001 = 600.1 s = 10 min 0.1 s
        assert format_time(6001) == "10:00.1"

    def test_heures(self):
        # 36615 = 3661.5 s = 1h 1min 1.5s
        assert format_time(36615) == "1:01:01.5"

    def test_zero(self):
        assert format_time(0) == "00:00"

    def test_valeur_ronde_sans_dixieme(self):
        # 600 = 60 s = 1 min exactement
        assert format_time(600) == "01:00"

    def test_negatif_leve_exception(self):
        with pytest.raises(ValueError):
            format_time(-1)

    def test_type_float_converti(self):
        # La fonction doit accepter les floats (int() coerce)
        assert format_time(3660.9) == "06:06"

    def test_heures_sans_dixieme(self):
        assert format_time(36000) == "1:00:00"

    def test_dixieme_seul(self):
        # 1 dixième = 0 s et 1 dixième
        assert format_time(1) == "00:00.1"

    def test_exactement_une_heure(self):
        # 36000 dixièmes = 3600 s = 1h00:00
        assert format_time(36000) == "1:00:00"

    def test_minutes_padded(self):
        # 1200 dixièmes = 120 s = 2 min 0 s
        assert format_time(1200) == "02:00"

    def test_secondes_padded(self):
        # 15 dixièmes = 1.5 s
        assert format_time(15) == "00:01.5"

    def test_grande_valeur(self):
        # 10 heures = 360000 dixièmes
        assert format_time(360000) == "10:00:00"


# ─── Tests STATUS_LABELS ──────────────────────────────────────────────────────

class TestStatusLabels:
    """Vérifie que STATUS_LABELS est cohérent."""

    def test_stat_ok_label(self):
        label, badge = STATUS_LABELS[STAT_OK]
        assert label == 'OK'
        assert badge == 'success'

    def test_stat_dns_label(self):
        label, _ = STATUS_LABELS[STAT_DNS]
        assert 'partant' in label.lower() or label == 'Non partant'

    def test_stat_dnf_label(self):
        label, badge = STATUS_LABELS[STAT_DNF]
        assert label in ('Abandon', 'DNF')

    def test_tous_les_statuts_ont_deux_elements(self):
        for code, value in STATUS_LABELS.items():
            assert len(value) == 2, f"Statut {code} devrait avoir (label, badge)"
            assert isinstance(value[0], str), f"Label du statut {code} doit être str"
            assert isinstance(value[1], str), f"Badge du statut {code} doit être str"

    def test_stat_unknown(self):
        label, badge = STATUS_LABELS[STAT_UNKNOWN]
        assert isinstance(label, str)
        assert badge == 'info'

    def test_stat_nt(self):
        label, badge = STATUS_LABELS[STAT_NT]
        assert 'Timing' in label or label == 'No Timing'

    def test_stat_mp(self):
        label, badge = STATUS_LABELS[STAT_MP]
        assert badge == 'danger'

    def test_stat_dq(self):
        label, badge = STATUS_LABELS[STAT_DQ]
        assert badge == 'danger'

    def test_stat_ot(self):
        label, badge = STATUS_LABELS[STAT_OT]
        assert badge == 'warning'

    def test_stat_occ(self):
        label, badge = STATUS_LABELS[STAT_OCC]
        assert badge == 'info'

    def test_stat_cancel(self):
        label, badge = STATUS_LABELS[STAT_CANCEL]
        assert badge == 'info'

    def test_stat_np(self):
        label, badge = STATUS_LABELS[STAT_NP]
        assert badge == 'secondary'

    def test_tous_les_codes_presents(self):
        """Chaque constante de statut doit avoir une entrée dans STATUS_LABELS."""
        codes = [
            STAT_UNKNOWN, STAT_OK, STAT_NT, STAT_MP, STAT_DNF,
            STAT_DQ, STAT_OT, STAT_OCC, STAT_DNS, STAT_CANCEL, STAT_NP,
        ]
        for code in codes:
            assert code in STATUS_LABELS, f"STAT {code} absent de STATUS_LABELS"


# ─── Tests Mopcompetitor properties ──────────────────────────────────────────

class TestMopcompetitorProperties:
    """Vérifie les propriétés calculées is_ok, status_label, status_badge."""

    def _make(self, stat, rt):
        """Construit un Mopcompetitor sans accès DB."""
        c = Mopcompetitor.__new__(Mopcompetitor)
        c.stat = stat
        c.rt   = rt
        return c

    # ── is_ok ─────────────────────────────────────────────────────────────────

    def test_is_ok_true_quand_stat_ok_et_rt_positif(self):
        c = self._make(stat=STAT_OK, rt=3600)
        assert c.is_ok is True

    def test_is_ok_false_quand_stat_ok_mais_rt_zero(self):
        c = self._make(stat=STAT_OK, rt=0)
        assert c.is_ok is False

    def test_is_ok_false_quand_stat_ok_mais_rt_negatif(self):
        c = self._make(stat=STAT_OK, rt=-1)
        assert c.is_ok is False

    def test_is_ok_false_quand_stat_dnf(self):
        c = self._make(stat=STAT_DNF, rt=3600)
        assert c.is_ok is False

    def test_is_ok_false_quand_stat_mp(self):
        c = self._make(stat=STAT_MP, rt=3600)
        assert c.is_ok is False

    def test_is_ok_false_quand_stat_dns(self):
        c = self._make(stat=STAT_DNS, rt=0)
        assert c.is_ok is False

    # ── status_label ──────────────────────────────────────────────────────────

    def test_status_label_ok(self):
        c = self._make(stat=STAT_OK, rt=3600)
        assert c.status_label == 'OK'

    def test_status_label_dnf(self):
        c = self._make(stat=STAT_DNF, rt=-1)
        assert c.status_label == STATUS_LABELS[STAT_DNF][0]

    def test_status_label_mp(self):
        c = self._make(stat=STAT_MP, rt=-1)
        assert c.status_label == STATUS_LABELS[STAT_MP][0]

    def test_status_label_dns(self):
        c = self._make(stat=STAT_DNS, rt=0)
        assert c.status_label == STATUS_LABELS[STAT_DNS][0]

    def test_status_label_statut_inconnu_retourne_point_interrogation(self):
        """Un code de statut non référencé renvoie '?'."""
        c = self._make(stat=9999, rt=0)
        assert c.status_label == '?'

    # ── status_badge ──────────────────────────────────────────────────────────

    def test_status_badge_ok(self):
        c = self._make(stat=STAT_OK, rt=3600)
        assert c.status_badge == 'success'

    def test_status_badge_dnf(self):
        c = self._make(stat=STAT_DNF, rt=-1)
        assert c.status_badge == 'warning'

    def test_status_badge_mp(self):
        c = self._make(stat=STAT_MP, rt=-1)
        assert c.status_badge == 'danger'

    def test_status_badge_dns(self):
        c = self._make(stat=STAT_DNS, rt=0)
        assert c.status_badge == 'secondary'

    def test_status_badge_statut_inconnu_retourne_secondary(self):
        """Un code de statut non référencé renvoie 'secondary'."""
        c = self._make(stat=9999, rt=0)
        assert c.status_badge == 'secondary'


# ─── Tests __str__ des modèles ────────────────────────────────────────────────

class TestModelStr:
    """Vérifie que __str__ retourne bien le nom de chaque modèle."""

    def test_mopcompetition_str(self):
        obj = Mopcompetition.__new__(Mopcompetition)
        obj.name = 'Championnat régional'
        assert str(obj) == 'Championnat régional'

    def test_mopclass_str(self):
        obj = Mopclass.__new__(Mopclass)
        obj.name = 'H21'
        assert str(obj) == 'H21'

    def test_moporganization_str(self):
        obj = Moporganization.__new__(Moporganization)
        obj.name = 'COLE'
        assert str(obj) == 'COLE'

    def test_mopcompetitor_str(self):
        obj = Mopcompetitor.__new__(Mopcompetitor)
        obj.name = 'Jean Dupont'
        assert str(obj) == 'Jean Dupont'

    def test_mopcontrol_str(self):
        obj = Mopcontrol.__new__(Mopcontrol)
        obj.name = 'P31'
        assert str(obj) == 'P31'

    def test_meostutorial_str(self):
        obj = MeosTutorial.__new__(MeosTutorial)
        obj.title = 'Guide de démarrage'
        assert str(obj) == 'Guide de démarrage'

    def test_str_chaine_vide(self):
        """__str__ doit tolérer un nom vide."""
        obj = Mopcompetitor.__new__(Mopcompetitor)
        obj.name = ''
        assert str(obj) == ''
