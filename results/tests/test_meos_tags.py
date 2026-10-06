"""
Tests pour les template tags Django dans templatetags/meos_tags.py.

Ces filters et tags sont utilisés dans les templates pour formatter
les temps et statuts des concurrents.
"""

import pytest
from django import template
from django.conf import settings
from django.test import override_settings

from datetime import date, datetime

from results.templatetags.meos_tags import (
    meos_time,
    status_badge,
    status_label,
    time_behind,
    display_name,
    iso_date,
    site_logo,
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

    def test_negatif_non_classe(self):
        """MeOS utilise -1 pour les non classés : on ne formate pas les négatifs ici."""
        assert meos_time(-1) == '-'
        assert meos_time(-500) == '-'


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


class TestDisplayNameFilter:
    """Tests pour le filter display_name (Prénom Nom → 'Nom,<br>Prénom')."""

    def test_deux_parties(self):
        from django.utils.safestring import SafeString
        result = display_name('Luc Martin')
        assert isinstance(result, SafeString)
        assert result == 'Martin,<br>Luc'

    def test_triple_nom_tout_dans_seconde_partie(self):
        assert display_name('Jean Paul Sartre') == 'Paul Sartre,<br>Jean'

    def test_nom_seul(self):
        assert display_name('Martin') == 'Martin'

    def test_nom_vide(self):
        assert display_name('') == ''

    def test_espaces_superflus(self):
        assert display_name('  Luc Martin  ') == 'Martin,<br>Luc'


class TestIsoDateFilter:
    """Filter iso_date : valeur attendue par <input type="date"> (YYYY-MM-DD).

    Un objet date rendu brut dans un template est localisé (« 17 mai 2026 »)
    et le navigateur vide alors le champ.
    """

    def test_date_objet_vers_iso(self):
        assert iso_date(date(2026, 5, 17)) == '2026-05-17'

    def test_datetime_reduite_ala_date(self):
        assert iso_date(datetime(2026, 5, 17, 14, 30)) == '2026-05-17'

    def test_chaine_deja_iso_inchangee(self):
        """Formulaire lié (valeur saisie) : la chaîne passe telle quelle."""
        assert iso_date('2026-05-17') == '2026-05-17'

    def test_none_et_vide_renvoient_vide(self):
        assert iso_date(None) == ''
        assert iso_date('') == ''

    def test_rendu_template_non_localise(self):
        """Rendu réel : la valeur reste ISO malgré LANGUAGE_CODE fr."""
        tpl = template.Template('{% load meos_tags %}{{ d|iso_date }}')
        out = tpl.render(template.Context({'d': date(2026, 5, 17)}))
        assert out == '2026-05-17'
        brut = template.Template('{{ d }}').render(
            template.Context({'d': date(2026, 5, 17)})
        )
        if settings.USE_I18N:
            assert brut != '2026-05-17'    # localisé sans le filter (bug d'origine)


class TestSiteLogoTag:
    """Tag site_logo : logo du club déposé dans org_logo/site.* (racine projet)."""

    def test_absent_renvoie_vide(self, tmp_path):
        with override_settings(ORG_LOGO_DIR=tmp_path):
            assert site_logo() == ''

    def test_svg_renvoie_url_org_logo(self, tmp_path):
        (tmp_path / 'site.svg').write_text('<svg></svg>')
        with override_settings(ORG_LOGO_DIR=tmp_path):
            assert site_logo() == '/org_logo/site.svg'

    def test_priorite_svg_sur_png(self, tmp_path):
        (tmp_path / 'site.svg').write_text('<svg></svg>')
        (tmp_path / 'site.png').write_bytes(b'\x89PNG\r\n\x1a\n')
        with override_settings(ORG_LOGO_DIR=tmp_path):
            assert site_logo() == '/org_logo/site.svg'

    def test_png_seul(self, tmp_path):
        (tmp_path / 'site.png').write_bytes(b'\x89PNG\r\n\x1a\n')
        with override_settings(ORG_LOGO_DIR=tmp_path):
            assert site_logo() == '/org_logo/site.png'

    def test_jpeg_seul(self, tmp_path):
        (tmp_path / 'site.jpeg').write_bytes(b'\xff\xd8\xff')
        with override_settings(ORG_LOGO_DIR=tmp_path):
            assert site_logo() == '/org_logo/site.jpeg'

    def test_autre_fichier_ignore(self, tmp_path):
        (tmp_path / 'logo-abc123.svg').write_text('<svg></svg>')
        with override_settings(ORG_LOGO_DIR=tmp_path):
            assert site_logo() == ''