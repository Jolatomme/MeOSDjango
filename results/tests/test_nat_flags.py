"""
Tests de results.nat_flags — drapeaux nationaux (MOP « nat » → SVG).

Le protocole MOP transmet la nationalité en code 3 lettres sur <org> et
<base> des <cmp>. Les SVG sont nommés à la CIO (``swe.svg``) dans
``static/results/img/flags/nat/`` ; les variantes ISO passent par
``NAT_ALIASES``. Un code inconnu ne rend rien (jamais d'image cassée).
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.template import Context, Template

from results.nat_flags import (
    NAT_ALIASES,
    NAT_FLAGS_DIR,
    nat_display_code,
    nat_flag_html,
    nat_flag_url,
    normalize_nat,
)


class TestNormalizeNat:
    def test_valeurs_vides(self):
        assert normalize_nat('') == ''
        assert normalize_nat(None) == ''
        assert normalize_nat('   ') == ''

    def test_majuscules_et_espaces(self):
        assert normalize_nat(' swe ') == 'swe'
        assert normalize_nat('SWE') == 'swe'

    def test_alias_iso_vers_cio(self):
        assert normalize_nat('CHE') == 'sui'   # Suisse
        assert normalize_nat('nld') == 'ned'   # Pays-Bas
        assert normalize_nat('svn') == 'slo'   # Slovénie

    def test_alias_inconnu_passe_tel_quel(self):
        assert normalize_nat('zzz') == 'zzz'


class TestNatFlagUrl:
    def test_code_connu(self):
        url = nat_flag_url('SWE')
        assert url.endswith('/results/img/flags/nat/swe.svg')

    def test_alias_resolu(self):
        assert nat_flag_url('CHE').endswith('/sui.svg')
        assert nat_flag_url('dnk').endswith('/den.svg')

    def test_code_inconnu_rend_vide(self):
        assert nat_flag_url('XXX') == ''
        assert nat_flag_url('') == ''
        assert nat_flag_url(None) == ''

    def test_cascade_coureur_puis_club(self):
        """Premier code avec SVG connu : le nat du coureur d'abord."""
        assert nat_flag_url('XXX', 'NOR').endswith('/nor.svg')
        assert nat_flag_url('FRA', 'NOR').endswith('/fra.svg')

    def test_cascade_tous_inconnus(self):
        assert nat_flag_url('XXX', 'ZZZ') == ''


class TestNatFlagHtml:
    def test_attributs_de_la_balise(self):
        html = nat_flag_html('swe')
        assert 'class="nat-flag"' in html
        assert 'src="' in html and 'swe.svg' in html
        assert 'alt="SWE"' in html
        assert 'title="SWE"' in html
        assert 'loading="lazy"' in html
        assert 'width="20"' in html and 'height="14"' in html

    def test_decoratif_sans_alt_ni_title(self):
        html = nat_flag_html('swe', decorative=True)
        assert 'alt=' not in html and 'title=' not in html

    def test_code_inconnu_rend_vide(self):
        assert nat_flag_html('XXX') == ''

    def test_marque_safe(self):
        """Sortie mark_safe : utilisable telle quelle dans un template."""
        from django.utils.safestring import SafeString
        assert isinstance(nat_flag_html('swe'), SafeString)

    def test_espace_explicite_apres_l_image(self):
        """L'image est terminée par une espace : jamais collée au nom.

        L'écart drapeau/nom est porté par le HTML, pas par le CSS — il
        survit à un ``site.css`` périmé ou caché côté client.
        """
        assert nat_flag_html('swe').endswith('height="14"> ')
        assert nat_flag_html('swe', decorative=True).endswith('height="14"> ')
        assert nat_flag_html('XXX') == ''

    def test_surcharge_css_marge_supprimee(self):
        """Plus de ``margin-inline-end`` sur ``.nat-flag`` : sinon
        l'espace HTML et la marge s'additionneraient (et la marge seule
        disparaîtrait avec un CSS périmé — un seul écart, dans le HTML)."""
        css = (Path(__file__).resolve().parents[1]
               / 'static' / 'results' / 'css' / 'site.css').read_text(encoding='utf-8')
        bloc = css.split('.nat-flag {', 1)[1].split('}', 1)[0]
        assert 'margin' not in bloc


class TestNatDisplayCode:
    def test_premier_code_non_vide(self):
        assert nat_display_code('', 'nor') == 'nor'
        assert nat_display_code('SWE', 'nor') == 'swe'

    def test_valeurs_non_chaine_ignorees(self):
        """Mocks de tests / valeurs exotiques : jamais de code bidon."""
        assert nat_display_code(MagicMock(), 42, '') == ''
        assert nat_display_code(MagicMock(), 'swe') == 'swe'


class TestDossierDesDrapeaux:
    def test_dossier_existe_et_non_vide(self):
        assert NAT_FLAGS_DIR.is_dir()
        assert list(NAT_FLAGS_DIR.glob('*.svg'))

    @pytest.mark.parametrize('code', ['swe', 'nor', 'fra', 'ger', 'sui',
                                      'ned', 'den', 'gbr', 'fin', 'est'])
    def test_nations_de_base_presentes(self, code):
        """Les nations de base du orienteering ont leur SVG."""
        assert (NAT_FLAGS_DIR / f'{code}.svg').is_file()


class TestTagTemplate:
    """``comp`` est un objet (modèle) portant ``org_obj`` attaché par les
    vues — comme dans les vrais templates."""

    @staticmethod
    def _comp(nat='', org_nat=''):
        return SimpleNamespace(
            nat=nat, org_obj=SimpleNamespace(nat=org_nat))

    def test_tag_nat_flag_rendu(self):
        html = Template(
            '{% load meos_tags %}{% nat_flag comp.nat comp.org_obj.nat %}'
        ).render(Context({'comp': self._comp(nat='swe', org_nat='nor')}))
        assert 'swe.svg' in html

    def test_tag_nat_flag_repli_club(self):
        html = Template(
            '{% load meos_tags %}{% nat_flag comp.nat comp.org_obj.nat %}'
        ).render(Context({'comp': self._comp(nat='', org_nat='nor')}))
        assert 'nor.svg' in html

    def test_tag_nat_flag_sans_drapeau(self):
        html = Template(
            '{% load meos_tags %}{% nat_flag comp.nat comp.org_obj.nat %}'
        ).render(Context({'comp': self._comp()}))
        assert html == ''


class TestEspaceApresLeDrapeau:
    """Les constructions **manuelles** d'``<img class="nat-flag">``
    (templates + JS, là où le tag ``{% nat_flag %}`` ne suffit pas)
    terminent par une espace : le drapeau n'est jamais collé au nom, même
    si ``site.css`` n'est pas déployé ou est resté en cache."""

    FICHIERS = (
        'templates/results/start_list.html',
        'templates/results/relay_results.html',
        'static/results/js/live.js',
    )

    @pytest.mark.parametrize('rel', FICHIERS)
    def test_chaque_image_est_suivie_d_une_espace(self, rel):
        contenu = (Path(__file__).resolve().parents[1] / rel).read_text(
            encoding='utf-8')
        total = contenu.count('height="14">')
        assert total > 0, f'{rel} : aucune construction de drapeau trouvée'
        assert contenu.count('height="14"> ') == total, (
            f'{rel} : une construction drapeau sans espace avant la suite')


class TestAlias:
    def test_toutes_les_alias_pointent_un_svg_existant(self):
        """Aucune alias ne doit pointer vers un fichier absent."""
        for variant, canonical in NAT_ALIASES.items():
            assert (NAT_FLAGS_DIR / f'{canonical}.svg').is_file(), (
                f"alias {variant!r} → {canonical!r} sans SVG")
