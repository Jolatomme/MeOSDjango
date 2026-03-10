"""
Tests unitaires pour les utilitaires de models.py.
Aucune DB requise.
"""

import pytest
from results.models import format_time, STATUS_LABELS, STAT_OK, STAT_DNS, STAT_DNF


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
