"""
Tests pour les template tags Django dans templatetags/meos_tags.py.

Ces filters et tags sont utilisés dans les templates pour formatter
les temps et statuts des concurrents.
"""

import pytest
from django import template

from results.templatetags.meos_tags import (
    meos_time,
    status_badge,
    status_label,
    time_behind,
)


class TestMeosTimeFilter:
    """Tests pour le filter meos_time.
    
    Le filter meos_time attend des temps en 1/10 de secondes (deciseconds).
    Ex: 3660 → '6:06' (366 secondes)
    """

    def test_zero(self):
        """0 (0 deciseconds) retourne '00:00'."""
        assert meos_time(0) == '00:00'

    def test_peu_de_temps(self):
        """Temps < 60 secondes."""
        assert meos_time(590) == '00:59'      # 59 sec
        assert meos_time(600) == '01:00'      # 60 sec = 1 min
        assert meos_time(610) == '01:01'      # 61 sec

    def test_plusieurs_minutes(self):
        """Plusieurs minutes."""
        assert meos_time(1200) == '02:00'     # 120 sec = 2 min
        assert meos_time(3660) == '06:06'     # 366 sec = 6 min 6 sec

    def test_une_heure(self):
        """Une heure."""
        assert meos_time(36000) == '1:00:00'  # 3600 sec = 1h

    def test_une_heure_et_minute(self):
        """Une heure + une minute."""
        assert meos_time(36600) == '1:01:00'  # 3660 sec = 1h 1min
        assert meos_time(36610) == '1:01:01'  # 3661 sec

    def test_avec_dixieme(self):
        """Temps avec dixième de seconde."""
        assert meos_time(601) == '01:00.1'    # 60.1 sec
        assert meos_time(611) == '01:01.1'    # 61.1 sec

    def test_none(self):
        """None retourne '-'."""
        assert meos_time(None) == '-'

    def test_string_invalide(self):
        """Chaîne invalide retourne '-'."""
        assert meos_time('abc') == '-'
        assert meos_time('') == '-'


class TestStatusBadgeFilter:
    """Tests pour le filter status_badge."""

    def test_stat_inconnu(self):
        """STAT_UNKNOWN = 0 retourne 'info'."""
        assert status_badge(0) == 'info'

    def test_stat_ok(self):
        """STAT_OK = 1 retourne 'success'."""
        assert status_badge(1) == 'success'

    def test_stat_nt(self):
        """STAT_NT = 2 retourne 'info'."""
        assert status_badge(2) == 'info'

    def test_stat_mp(self):
        """STAT_MP = 3 retourne 'danger'."""
        assert status_badge(3) == 'danger'

    def test_stat_dnf(self):
        """STAT_DNF = 4 retourne 'warning'."""
        assert status_badge(4) == 'warning'

    def test_stat_dq(self):
        """STAT_DQ = 5 retourne 'danger'."""
        assert status_badge(5) == 'danger'

    def test_stat_ot(self):
        """STAT_OT = 6 retourne 'warning'."""
        assert status_badge(6) == 'warning'

    def test_stat_occ(self):
        """STAT_OCC = 15 retourne 'info'."""
        assert status_badge(15) == 'info'

    def test_stat_dns(self):
        """STAT_DNS = 20 retourne 'secondary'."""
        assert status_badge(20) == 'secondary'

    def test_stat_cancel(self):
        """STAT_CANCEL = 21 retourne 'info'."""
        assert status_badge(21) == 'info'

    def test_stat_np(self):
        """STAT_NP = 99 retourne 'secondary'."""
        assert status_badge(99) == 'secondary'

    def test_invalide(self):
        """Code invalide retourne 'secondary'."""
        assert status_badge(99) == 'secondary'
        assert status_badge(7) == 'secondary'
        assert status_badge(-1) == 'secondary'

    def test_none(self):
        """None retourne 'secondary'."""
        assert status_badge(None) == 'secondary'

    def test_string_invalide(self):
        """Chaîne invalide retourne 'secondary'."""
        assert status_badge('abc') == 'secondary'
        assert status_badge('') == 'secondary'


class TestStatusLabelFilter:
    """Tests pour le filter status_label."""

    def test_stat_inconnu(self):
        """STAT_UNKNOWN = 0 retourne 'Inconnu'."""
        assert status_label(0) == 'Inconnu'

    def test_stat_ok(self):
        """STAT_OK = 1 retourne 'OK'."""
        assert status_label(1) == 'OK'

    def test_stat_nt(self):
        """STAT_NT = 2 retourne 'No Timing'."""
        assert status_label(2) == 'No Timing'

    def test_stat_mp(self):
        """STAT_MP = 3 retourne 'PM'."""
        assert status_label(3) == 'PM'

    def test_stat_dnf(self):
        """STAT_DNF = 4 retourne 'Abandon'."""
        assert status_label(4) == 'Abandon'

    def test_stat_dq(self):
        """STAT_DQ = 5 retourne 'DSQ'."""
        assert status_label(5) == 'DSQ'

    def test_stat_ot(self):
        """STAT_OT = 6 retourne 'H.T.'."""
        assert status_label(6) == 'H.T.'

    def test_stat_occ(self):
        """STAT_OCC = 15 retourne 'Hors compét.'."""
        assert status_label(15) == 'Hors compét.'

    def test_stat_dns(self):
        """STAT_DNS = 20 retourne 'Non partant'."""
        assert status_label(20) == 'Non partant'

    def test_stat_cancel(self):
        """STAT_CANCEL = 21 retourne 'Cancel'."""
        assert status_label(21) == 'Cancel'

    def test_stat_np(self):
        """STAT_NP = 99 retourne 'Non participant'."""
        assert status_label(99) == 'Non participant'

    def test_invalide(self):
        """Code invalide retourne '?'."""
        assert status_label(7) == '?'
        assert status_label(-1) == '?'

    def test_none(self):
        """None retourne '?'."""
        assert status_label(None) == '?'

    def test_string_invalide(self):
        """Chaîne invalide retourne '?'."""
        assert status_label('abc') == '?'
        assert status_label('') == '?'


class TestTimeBehindTag:
    """Tests pour le tag time_behind.
    
    Le tag time_behind attend des temps en deciseconds (1/10 sec).
    Ex: 36000 = 3600 sec = 1 heure
    """

    def test_leader(self):
        """Leader (runner_time == leader_time) retourne chaîne vide."""
        assert time_behind(36000, 36000) == ''

    def test_leader_zero(self):
        """Leader à 0 retourne chaîne vide."""
        assert time_behind(0, 0) == ''

    def test_behind_un_minute(self):
        """1 minute derrière (60 sec = 600 deciseconds)."""
        assert time_behind(36600, 36000) == '+01:00'

    def test_behind_deux_minutes(self):
        """2 minutes derrière (120 sec = 1200 deciseconds)."""
        assert time_behind(37200, 36000) == '+02:00'

    def test_behind_une_heure(self):
        """1 heure derrière (3600 sec = 36000 deciseconds)."""
        assert time_behind(72000, 36000) == '+1:00:00'  # 36000 diff = 1h

    def test_aller_avant(self):
        """Coureur plus rapide que le leader retourne chaîne vide."""
        assert time_behind(35000, 36000) == ''

    def test_runner_none(self):
        """Runner None retourne '-'."""
        assert time_behind(None, 36000) == '-'

    def test_leader_none(self):
        """Leader None retourne '-'."""
        assert time_behind(36000, None) == '-'

    def test_both_none(self):
        """Both None retourne '-'."""
        assert time_behind(None, None) == '-'

    def test_string_invalide(self):
        """Chaînes invalides retournent '-'."""
        assert time_behind('abc', '36000') == '-'
        assert time_behind('36000', 'abc') == '-'
        assert time_behind('abc', 'def') == '-'

    def test_empty_strings(self):
        """Chaînes vides retournent '-'."""
        assert time_behind('', '') == '-'
        assert time_behind('', '36000') == '-'
        assert time_behind('36000', '') == '-'