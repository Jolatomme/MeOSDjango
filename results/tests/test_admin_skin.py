"""
Tests de l'habillage de l'admin (« look & feel » du site) — sans base de données.

Couvre :
  - la surcharge de templates/admin/base_site.html (prioritaire sur
    django.contrib.admin grâce à TEMPLATES['DIRS']) ;
  - le chargement de la charte (site.css + admin.css + admin-theme.js) ;
  - la synchronisation du thème sombre avec le site (clé « co-theme ») ;
  - le pont de variables de admin.css et le partage du thème côté JS.
"""

from pathlib import Path

from django.template.loader import get_template
from django.test import RequestFactory

RESULTS_DIR = Path(__file__).resolve().parents[1]
ADMIN_CSS = RESULTS_DIR / 'static' / 'results' / 'css' / 'admin.css'
ADMIN_JS = RESULTS_DIR / 'static' / 'results' / 'js' / 'admin-theme.js'


def _login_response():
    """Rendu réel de la page de connexion /admin/login/ (aucune requête DB)."""
    from django.contrib.admin.sites import site
    from django.contrib.auth.models import AnonymousUser

    request = RequestFactory().get('/admin/login/')
    request.user = AnonymousUser()
    response = site.login(request)
    response.render()
    return response


# ─── Surcharge du template de base ────────────────────────────────────────────

class TestBaseSiteOverride:

    def test_notre_template_gagne_sur_django(self):
        """DIRS du projet prioritaire : django.contrib.admin est 1er dans
        INSTALLED_APPS, son base_site.html l'emporterait sinon (silencieusement)."""
        origin = get_template('admin/base_site.html').origin.name
        assert origin.endswith('templates/admin/base_site.html')
        assert 'site-packages' not in origin

    def test_login_affiche_la_charte_du_site(self):
        html = _login_response().content.decode()
        assert 'results/css/site.css' in html          # polices + tokens --co-*
        assert 'results/css/admin.css' in html         # habillage de l'admin
        assert 'results/js/admin-theme.js' in html     # bascule partagée
        assert 'co-theme' in html                      # clé localStorage du site
        # admin/js/theme.js (clé « theme » concurrente) est retiré
        assert 'admin/js/theme.js' not in html

    def test_login_porte_l_identite_du_site(self):
        html = _login_response().content.decode()
        assert 'brand-accent' in html                  # point doré du logotype
        assert 'admin-back-site' in html               # lien « Retour au site »
        assert 'darkModeToggle' in html                # bouton lune/soleil du site
        assert 'Résultats CO' in html                  # SITE_NAME (context processor)
        assert '<title>Connexion | Résultats CO</title>' in html

    def test_branding_rend_logo_et_retour_site(self):
        from django.contrib.auth.models import AnonymousUser
        template = get_template('admin/base_site.html')
        html = template.render({
            'SITE_NAME': 'Résultats CO',
            'CLUB_COLOR_PRIMARY': '#1a6b3c',
            'CLUB_COLOR_ACCENT': '#f0a500',
            'user': AnonymousUser(),
            'has_permission': False,
        })
        assert '<span>Résultats CO</span>' in html
        assert 'brand-accent' in html
        assert 'href="/"' in html
        assert 'admin/js/theme.js' not in html

    def test_usertools_sans_bouton_theme_natif(self):
        """Le bandeau garde un seul bouton de thème : le nôtre (#darkModeToggle)."""
        from django.contrib.auth.models import AnonymousUser
        template = get_template('admin/base_site.html')
        html = template.render({
            'SITE_NAME': 'Résultats CO',
            'CLUB_COLOR_PRIMARY': '#1a6b3c',
            'CLUB_COLOR_ACCENT': '#f0a500',
            'user': AnonymousUser(),
            'has_permission': True,
        })
        assert 'id="logout-form"' in html
        assert 'darkModeToggle' in html
        assert 'class="theme-toggle"' not in html   # bouton natif retiré du bandeau


# ─── Feuille de style d'habillage ─────────────────────────────────────────────

class TestAdminCss:

    def test_fichier_present(self):
        assert ADMIN_CSS.is_file()

    def test_ponte_les_variables_de_django(self):
        """Toutes les couleurs de l'admin passent par les tokens du site."""
        css = ADMIN_CSS.read_text()
        assert ':root,' in css and 'html[data-theme] {' in css
        assert '--primary:             var(--co-green);' in css
        assert '--header-bg:           var(--co-forest);' in css
        assert '--button-bg:           var(--co-green);' in css

    def test_regle_le_theme_sombre(self):
        css = ADMIN_CSS.read_text()
        assert 'html[data-theme="dark"]' in css

    def test_cartes_et_tableaux_comme_le_site(self):
        css = ADMIN_CSS.read_text()
        assert 'var(--co-radius-lg)' in css      # rayon des cartes
        assert 'var(--co-shadow)' in css         # ombre des cartes
        assert '#result_list thead th' in css    # en-tête de tableau façon site


# ─── Bascule de thème partagée ────────────────────────────────────────────────

class TestAdminThemeJs:

    def test_fichier_present(self):
        assert ADMIN_JS.is_file()

    def test_utilise_la_cle_du_site(self):
        js = ADMIN_JS.read_text()
        assert "'co-theme'" in js
        assert 'darkModeToggle' in js            # bouton du site
        assert '.theme-toggle' in js             # bouton natif conservé (mdp)
        # la clé « theme » de Django (admin/js/theme.js) n'est pas lue ici
        assert "localStorage.getItem('theme')" not in js
