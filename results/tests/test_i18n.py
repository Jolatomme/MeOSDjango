"""
Tests de l'internationalisation (i18n) du site — sans base de données.

Couvre :
  - le sélecteur de drapeaux de la barre (4 langues, drapeau actif, <html lang>) ;
  - la vue Django ``set_language`` (cookie ``co_lang`` + redirection sûre) ;
  - la négociation de langue (cookie ``co_lang`` / ``Accept-Language``) ;
  - l'invariance des URL entre les langues (pas de ``i18n_patterns``) ;
  - la langue source française et les catalogues compilés (``*.mo``) ;
  - l'injection des chaînes traduites dans le JS partagé (``COUtils.setStrings``).

Les tests de contenu traduit sont ignorés quand ``compilemessages`` n'a pas été
exécuté (``locale/*/LC_MESSAGES/django.mo`` est ignoré par git).
"""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.template.loader import get_template
from django.test import RequestFactory
from django.urls import reverse
from django.utils import translation

LOCALE_DIR = Path(settings.BASE_DIR) / 'locale'
FLAGS_DIR = Path(__file__).resolve().parents[1] / 'static' / 'results' / 'img' / 'flags'

FR_LIBELLE = 'Mode sombre / clair'   # titre du bouton lune/soleil (base.html)
FR_ABANDONS_JS = 'Afficher abandons'  # chaîne injectée via COUtils.setStrings


@pytest.fixture(autouse=True)
def _langue_reinitialisee():
    """La locale est un état global par thread : LocaleMiddleware la laisse
    active après la requête (cookie/Accept-Language testés ici) et
    translation.override restaure l'état précédent — remettre le français
    avant/après évite qu'une fuite contamine les autres fichiers de tests."""
    translation.activate(settings.LANGUAGE_CODE)
    yield
    translation.activate(settings.LANGUAGE_CODE)


def _mo(lang):
    return LOCALE_DIR / lang / 'LC_MESSAGES' / 'django.mo'


def _skip_si_non_compile(lang):
    if not _mo(lang).is_file():
        pytest.skip(f'locale/{lang}/LC_MESSAGES/django.mo non compilé (compilemessages)')


def _render_base(lang='fr'):
    """Rendu complet de results/base.html (context processors inclus, sans DB)."""
    request = RequestFactory().get('/')
    with translation.override(lang):
        return get_template('results/base.html').render({}, request)


# ─── Sélecteur de drapeaux (barre de navigation) ─────────────────────────────

class TestSelecteurDeLangue:

    def test_formulaire_avec_quatre_drapeaux(self):
        html = _render_base()
        assert 'class="co-lang-switch dropdown"' in html
        assert 'action="/i18n/setlang/"' in html
        assert 'method="post"' in html
        assert 'csrfmiddlewaretoken' in html
        for code in ('fr', 'en', 'de', 'sv'):
            assert f'name="language" value="{code}"' in html
        # Pas d'emoji : fichiers SVG (fr / Union Jack / de / sv)
        for flag in ('fr', 'gb', 'de', 'se'):
            assert f'results/img/flags/{flag}.svg' in html

    def test_menu_deroulant_bootstrap(self):
        """Les drapeaux sont repliés dans un menu déroulant (Bootstrap) :
        déclencheur unique (drapeau de la langue courante + chevron) ouvrant
        un menu thématisé (.co-dropdown) avec drapeau + nom natif par langue."""
        html = _render_base()
        assert 'class="co-lang-toggle dropdown-toggle"' in html
        assert 'data-bs-toggle="dropdown"' in html
        assert 'class="dropdown-menu co-dropdown co-lang-menu"' in html
        for name in ('Français', 'English', 'Deutsch', 'Svenska'):
            assert f'<span>{name}</span>' in html

    def test_libelles_natifs_des_drapeaux(self):
        """Les titres viennent de LANGUAGES (noms natifs, jamais traduits)."""
        html = _render_base()
        for name in ('Français', 'English', 'Svenska', 'Deutsch'):
            assert f'title="{name}"' in html

    @pytest.mark.parametrize('lang,flag', [('fr', 'fr'), ('en', 'gb'),
                                           ('de', 'de'), ('sv', 'se')])
    def test_filtre_lang_flag_et_fichiers(self, lang, flag):
        from results.templatetags.meos_tags import lang_flag
        assert lang_flag(lang) == flag
        assert (FLAGS_DIR / f'{flag}.svg').is_file()

    @pytest.mark.parametrize('lang', ['fr', 'en', 'de', 'sv'])
    def test_un_seul_drapeau_actif_coherent(self, lang):
        html = _render_base(lang)
        actifs = re.findall(
            r'name="language" value="(\w+)"[^>]*class="[^"]*\bactive\b', html)
        assert actifs == [lang]

    @pytest.mark.parametrize('lang', ['fr', 'en', 'de', 'sv'])
    def test_balise_html_lang(self, lang):
        assert f'<html lang="{lang}"' in _render_base(lang)


# ─── Vue set_language (Django intégré, branchée sur /i18n/) ───────────────────

class TestVueSetLanguage:

    def test_post_pose_le_cookie_et_redirige_vers_next(self, client):
        resp = client.post('/i18n/setlang/', {'language': 'de', 'next': '/creer-course/'})
        assert resp.status_code == 302
        assert resp['Location'] == '/creer-course/'
        assert resp.cookies['co_lang'].value == 'de'

    def test_next_invalide_retombe_sur_la_racine(self, client):
        resp = client.post('/i18n/setlang/',
                           {'language': 'en', 'next': 'https://evil.example/x'})
        assert resp['Location'] == '/'
        assert resp.cookies['co_lang'].value == 'en'

    def test_get_ne_change_pas_la_langue(self, client):
        resp = client.get('/i18n/setlang/?next=/')
        assert resp.status_code == 302
        assert 'co_lang' not in resp.cookies

    def test_cookie_dure_un_an(self, client):
        resp = client.post('/i18n/setlang/', {'language': 'sv', 'next': '/'})
        assert resp.cookies['co_lang']['max-age'] == settings.LANGUAGE_COOKIE_AGE
        assert settings.LANGUAGE_COOKIE_AGE == 60 * 60 * 24 * 365
        assert settings.LANGUAGE_COOKIE_NAME == 'co_lang'


# ─── Négociation de langue (LocaleMiddleware, page sans DB) ──────────────────

class TestNegociationDeLangue:

    def test_langue_par_defaut_francaise(self, client):
        html = client.get('/admin/login/').content.decode()
        assert '<html lang="fr"' in html
        assert 'Connexion' in html

    def test_cookie_co_lang_guide_localemiddleware(self, client):
        client.cookies['co_lang'] = 'de'
        html = client.get('/admin/login/').content.decode()
        assert '<html lang="de"' in html

    def test_accept_language_pour_une_premiere_visite(self, client):
        html = client.get('/admin/login/',
                          HTTP_ACCEPT_LANGUAGE='sv-SE,sv;q=0.9,en;q=0.8').content.decode()
        assert '<html lang="sv"' in html


# ─── URL invariante entre les langues (pas de i18n_patterns) ─────────────────

class TestUrlInchangees:

    @pytest.mark.parametrize('lang', ['fr', 'en', 'de', 'sv'])
    def test_reverse_identique_quelle_que_soit_la_langue(self, lang):
        """Les liens MeOS, /gestion-course/<token>/, /api/ et CSV ne bougent pas."""
        with translation.override(lang):
            assert reverse('results:home') == '/'
            assert reverse('results:race_create') == '/creer-course/'
            assert reverse('results:competition_detail', args=[42]) == '/competition/42/'
            assert reverse('set_language') == '/i18n/setlang/'


# ─── Langue source et catalogues compilés ────────────────────────────────────

class TestCatalogues:

    def test_le_francais_est_la_langue_source(self):
        """Pas de catalogue fr : le msgid français s'affiche tel quel."""
        with translation.override('fr'):
            assert translation.gettext(FR_LIBELLE) == FR_LIBELLE

    @pytest.mark.parametrize('lang', ['en', 'de', 'sv'])
    def test_catalogue_compile_traduit(self, lang):
        _skip_si_non_compile(lang)
        with translation.override(lang):
            trad = translation.gettext(FR_LIBELLE)
        assert trad and trad != FR_LIBELLE

    @pytest.mark.parametrize('lang', ['en', 'de', 'sv'])
    def test_libelle_traduit_dans_le_template(self, lang):
        _skip_si_non_compile(lang)
        html = _render_base(lang)
        with translation.override(lang):
            attendu = translation.gettext(FR_LIBELLE)
        assert f'title="{attendu}"' in html
        assert f'title="{FR_LIBELLE}"' not in html

    def test_contexte_mopstatus_protege_du_catalogue_coeur(self):
        """« PM » existe dans le catalogue cœur de Django fr (→ « Après-midi ») :
        les étiquettes de statut passent par pgettext('mopstatus', …), ce qui
        renvoie le msgid au lieu d'emprunter la traduction de Django."""
        from results.models import STAT_MP, STATUS_LABELS
        msgid = STATUS_LABELS[STAT_MP][0]                   # 'PM'
        with translation.override('fr'):
            assert translation.gettext(msgid) != msgid      # le leak existe…
            assert translation.pgettext('mopstatus', msgid) == msgid  # …neutralisé


# ─── Chaînes injectées dans le JS partagé (site.js) ──────────────────────────

class TestChainesJavascript:

    def test_setstrings_source_francaise_sans_catalogue(self):
        html = _render_base('fr')
        assert 'showAbandons: "Afficher abandons"' in html
        assert 'hideAbandons: "Masquer abandons"' in html
        assert 'alt1: "1er"' in html

    @pytest.mark.parametrize('lang', ['en', 'de', 'sv'])
    def test_setstrings_injecte_les_traductions(self, lang):
        _skip_si_non_compile(lang)
        html = _render_base(lang)
        with translation.override(lang):
            attendu = translation.gettext(FR_ABANDONS_JS)
        assert attendu != FR_ABANDONS_JS
        assert f'showAbandons: "{attendu}"' in html


# ─── Libellés du menu admin (verbose_name des modèles + section) ─────────────

class TestLibellesAdmin:

    def test_verbose_names_source_francaise(self):
        """Les verbose_name restent des msgid français (langue source)."""
        from results.models import CompetitionConfig, Mopcompetition
        with translation.override('fr'):
            assert str(Mopcompetition._meta.verbose_name) == 'compétition'
            assert str(Mopcompetition._meta.verbose_name_plural) == 'compétitions'
            assert str(CompetitionConfig._meta.verbose_name) == 'configuration compétition'
            assert str(CompetitionConfig._meta.verbose_name_plural) == 'configurations compétitions'

    @pytest.mark.parametrize('lang', ['en', 'de', 'sv'])
    def test_verbose_names_traduits_dans_le_menu(self, lang):
        """Le menu admin affiche les entrées de modèles dans la langue active."""
        _skip_si_non_compile(lang)
        from results.models import CompetitionConfig, Mopcompetition
        with translation.override(lang):
            assert str(Mopcompetition._meta.verbose_name_plural) == translation.gettext('compétitions')
            assert str(CompetitionConfig._meta.verbose_name_plural) == translation.gettext('configurations compétitions')
            assert str(Mopcompetition._meta.verbose_name_plural) != 'compétitions'
            assert str(CompetitionConfig._meta.verbose_name_plural) != 'configurations compétitions'

    @pytest.mark.parametrize('lang', ['en', 'de', 'sv'])
    def test_titre_section_admin_traduit(self, lang):
        """La section de l'app « Résultats » du menu admin suit la langue."""
        _skip_si_non_compile(lang)
        from django.apps import apps
        cfg = apps.get_app_config('results')
        with translation.override(lang):
            assert str(cfg.verbose_name) == translation.gettext('Résultats')
            assert str(cfg.verbose_name) != 'Résultats'

    @pytest.mark.parametrize('lang', ['en', 'de', 'sv'])
    def test_libelles_colonnes_vue_competition(self, lang):
        """Les en-têtes de colonnes de l'admin Mopcompetition (champs name,
        date, organizer, homepage) sont traduits dans la langue active."""
        _skip_si_non_compile(lang)
        from results.models import Mopcompetition
        attendus = {
            'name': 'compétition',
            'date': 'Date',
            'organizer': 'organisateur',
            'homepage': "page d'accueil",
        }
        with translation.override(lang):
            for champ, fr in attendus.items():
                assert str(Mopcompetition._meta.get_field(champ).verbose_name) == translation.gettext(fr)

    def test_libelles_colonnes_vue_competition_source_francaise(self):
        from results.models import Mopcompetition
        with translation.override('fr'):
            assert str(Mopcompetition._meta.get_field('name').verbose_name) == 'compétition'
            assert str(Mopcompetition._meta.get_field('date').verbose_name) == 'Date'
            assert str(Mopcompetition._meta.get_field('organizer').verbose_name) == 'organisateur'
            assert str(Mopcompetition._meta.get_field('homepage').verbose_name) == "page d'accueil"
