"""
Tests de l'internationalisation (i18n) du site — sans base de données.

Couvre :
  - le sélecteur de drapeaux de la barre (4 langues, drapeau actif, <html lang>) ;
  - la vue Django ``set_language`` (cookie ``co_lang`` + redirection sûre) ;
  - la négociation de langue (cookie ``co_lang`` / ``Accept-Language``) ;
  - l'invariance des URL entre les langues (pas de ``i18n_patterns``) ;
  - la langue source française et les catalogues compilés (``*.mo``) ;
  - les catalogues **complets** : aucun ``msgstr`` vide ni entrée floue
    (non compilée → chaîne laissée en français, bug « Aucun favori … ») ;
  - l'injection des chaînes traduites dans le JS partagé (``COUtils.setStrings``) ;
  - le bouton « Supprimer la course » du lien privé traduit (une entrée créée
    par appariement flou de ``msgmerge`` ne serait pas compilée).

Les tests de contenu traduit sont ignorés quand ``compilemessages`` n'a pas été
exécuté (``locale/*/LC_MESSAGES/django.mo`` est ignoré par git).
"""

import re
from pathlib import Path
from types import SimpleNamespace

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


# ─── Catalogues complets (aucune chaîne oubliée) ─────────────────────────────

def _lire_po(path):
    """Lit un fichier ``.po`` sans dépendance externe (polib absent).

    Renvoie la liste des entrées ``{'msgid', 'msgstr', 'fuzzy'}`` : les blocs
    d'une même entrée sont concaténés (msgids/multi-lignes et tous les
    ``msgstr[N]``), les commentaires (#, #|) ignorés sauf le drapeau fuzzy.
    """
    entrees, entree, champ, fuzzy = [], None, None, False
    for ligne in path.read_text(encoding='utf-8').splitlines():
        if ligne.startswith('#,') and 'fuzzy' in ligne:
            fuzzy = True
            continue
        if ligne.startswith('#'):
            continue
        if not ligne.strip():
            if entree is not None:
                entrees.append(entree)
                entree = None
            champ = None
            continue
        m = re.match(r'(msgid|msgid_plural|msgstr(?:\[\d+\])?)\s+"(.*)"$', ligne)
        if m:
            champ = m.group(1)
            if entree is None:
                entree = {'msgid': '', 'msgstr': '', 'fuzzy': fuzzy}
                fuzzy = False
            if champ.startswith('msgstr'):
                entree['msgstr'] += m.group(2)
            else:                                   # msgid / msgid_plural
                entree['msgid'] += m.group(2)
        elif ligne.startswith('"') and ligne.endswith('"') and entree is not None:
            texte = ligne[1:-1]
            if champ and champ.startswith('msgstr'):
                entree['msgstr'] += texte
            elif champ:                             # msgid / msgid_plural
                entree['msgid'] += texte
    if entree is not None:
        entrees.append(entree)
    return entrees


class TestCataloguesComplets:
    """Aucune chaîne ne doit rester sans ``msgstr``.

    Une entrée vide (ou floue) n'est **pas** compilée dans le ``.mo`` : la
    chaîne s'affiche alors en français quelle que soit la langue choisie —
    c'est exactement le bug observé sur « Aucun favori pour cette course … »,
    traduite partout sauf dans les catalogues.
    """

    @pytest.mark.parametrize('lang', ['en', 'de', 'sv'])
    def test_aucune_chaine_non_traduite(self, lang):
        po = LOCALE_DIR / lang / 'LC_MESSAGES' / 'django.po'
        entrees = _lire_po(po)
        assert len(entrees) > 100, 'catalogue illisible ou tronqué'

        vides = [e['msgid'] for e in entrees if e['msgid'] and not e['msgstr']]
        assert not vides, 'msgstr manquants : ' + ' | '.join(vides)

        flous = [e['msgid'] for e in entrees if e['fuzzy']]
        assert not flous, 'entrées floues (exclues de la compilation) : ' + ' | '.join(flous)

    @pytest.mark.parametrize('lang,attendu', [
        ('en', 'No favorites for this race'),
        ('de', 'Keine Favoriten für diesen Wettkampf'),
        ('sv', 'Inga favoriter för denna tävling'),
    ])
    def test_chaine_favoris_traduite_dans_la_page_live(self, lang, attendu):
        """La chaîne « Aucun favori … » est injectée traduite par le template."""
        _skip_si_non_compile(lang)
        # Un cid + un nom de classe suffisent : les {% url %} de la page en ont besoin
        competition = SimpleNamespace(cid=42, name='Test', date=None)
        cls = SimpleNamespace(name='H10')
        html = _render('results/live_results.html', lang,
                       {'competition': competition, 'cls': cls})
        assert attendu in html
        assert 'Aucun favori pour cette course' not in html


# ─── Lien privé de gestion : bouton « Supprimer la course » ──────────────────

class TestBoutonSuppressionCourse:
    """Le bouton de suppression de race_manage.html doit être traduit.

    ``msgmerge`` peut rapprocher « Supprimer la course » d'un autre msgid
    (appariement flou) : une entrée floue n'est **pas** compilée dans le
    ``.mo`` → le bouton resterait affiché en français. Le test est ignoré
    tant que ``compilemessages`` n'a pas été lancé.
    """

    FR_BOUTON = 'Supprimer la course'

    @pytest.mark.parametrize('lang,attendu', [
        ('en', 'Delete the race'),
        ('de', 'Wettkampf löschen'),
        ('sv', 'Radera tävlingen'),
    ])
    def test_bouton_traduit_dans_le_catalogue(self, lang, attendu):
        _skip_si_non_compile(lang)
        html = _render('results/race_manage.html', lang)
        with translation.override(lang):
            assert translation.gettext(self.FR_BOUTON) == attendu
        assert attendu in html
        assert 'value="delete"' in html               # action du formulaire
        assert self.FR_BOUTON not in html


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


# ─── Champ fichier personnalisé (checker, vérifie-moi, création de course) ────

TEMPLATES_CHAMP_FICHIER = [
    'results/meos_checker.html',
    'results/verifie_moi.html',
    'results/race_create.html',
]
FR_BOUTON_FICHIER = 'Choisir un fichier'    # bouton affiché par nos soins
FR_AUCUN_FICHIER = 'Aucun fichier choisi'   # nom de fichier par défaut


def _render(template, lang='fr', context=None):
    """Rendu d'une page complète (base.html + context processors, sans DB)."""
    request = RequestFactory().get('/')
    with translation.override(lang):
        return get_template(template).render(context or {}, request)


class TestChampFichierPersonnalise:
    """Le widget natif <input type="file"> est rendu par le navigateur dans
    SA propre langue (jamais celle du site) : les trois pages remplacent
    l'input masqué par leur propre bouton + nom de fichier traduits
    (wrapper ``.co-file``), gérés par ``COUtils.initFileInputs``."""

    def test_markup_sur_les_trois_pages(self):
        for template in TEMPLATES_CHAMP_FICHIER:
            html = _render(template)
            assert 'class="co-file"' in html, template
            assert 'class="co-file-input"' in html, template
            assert 'btn btn-outline-success co-file-btn' in html, template
            assert f'data-default="{FR_AUCUN_FICHIER}"' in html, template
            assert f'<span class="co-file-name">{FR_AUCUN_FICHIER}</span>' in html, template
            assert f'</i>{FR_BOUTON_FICHIER}' in html, template

    def test_plus_de_widget_natif_form_control(self):
        """L'ancien <input type="file" class="form-control"> a disparu."""
        for template in ('results/meos_checker.html', 'results/verifie_moi.html'):
            assert 'class="form-control" id="meosfile"' not in _render(template)

    @pytest.mark.parametrize('lang', ['en', 'de', 'sv'])
    def test_libelles_traduits_dans_le_catalogue(self, lang):
        _skip_si_non_compile(lang)
        html = _render('results/meos_checker.html', lang)
        with translation.override(lang):
            bouton = translation.gettext(FR_BOUTON_FICHIER)
            aucun = translation.gettext(FR_AUCUN_FICHIER)
        assert bouton != FR_BOUTON_FICHIER
        assert aucun != FR_AUCUN_FICHIER
        assert bouton in html
        assert f'data-default="{aucun}"' in html


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
