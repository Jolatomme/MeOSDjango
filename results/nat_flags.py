"""
nat_flags.py — Drapeaux nationaux (code MOP « nat » → SVG statique).

Le protocole MOP transmet la nationalité sous forme de code lettres à
3 caractères (« Three letter nationality », mop.xsd) sur <org> et sur
<base> des <cmp>. MeOS utilise en pratique des codes CIO (SWE, SUI,
NED…) ; quelques-uns diffèrent des codes ISO 3166-1 alpha-3 — le dict
``NAT_ALIASES`` absorbe ces variantes.

Les SVG vivent dans ``static/results/img/flags/nat/<code>.svg`` :
nommés à la CIO, source flag-icons (licence MIT), format 4x3. Un code
inconnu (pas de fichier) ne rend rien — jamais d'image cassée.

Utilisé par le tag template ``{% nat_flag %}`` et par les vues qui
construisent des payloads JSON (Live, liste de départ, relais).
"""

from functools import lru_cache
from pathlib import Path

from django.templatetags.static import static
from django.utils.html import escape
from django.utils.safestring import mark_safe

# Dossier des SVG (dans le package results/ — pas besoin de collectstatic
# pour le check d'existence, uniquement pour les URL de production).
NAT_FLAGS_DIR = Path(__file__).resolve().parent / 'static' / 'results' / 'img' / 'flags' / 'nat'

# Variante ISO (ou autre convention) → nom de fichier CIO retenu.
NAT_ALIASES = {
    'che': 'sui',    # Suisse
    'nld': 'ned',    # Pays-Bas
    'dnk': 'den',    # Danemark
    'grc': 'gre',    # Grèce
    'svn': 'slo',    # Slovénie (SLO = CIO, SVN = ISO)
    'hrv': 'cro',    # Croatie
    'deu': 'ger',    # Allemagne
    'uk':  'gbr',    # 2 lettres éventuelle
}


def normalize_nat(nat):
    """Normalise un code nationalité (« swe », « SWE « → « swe ») ou ''.

    Les valeurs vides/absentes (None, '') retournent '' — le repli sur un
    autre code (ex. nat du club) est géré par l'appelant.
    """
    if not nat:
        return ''
    code = str(nat).strip().lower()
    if not code:
        return ''
    return NAT_ALIASES.get(code, code)


@lru_cache(maxsize=None)
def _has_flag(code):
    """True si le SVG existe (résultat mis en cache pour la durée du process)."""
    return (NAT_FLAGS_DIR / f'{code}.svg').is_file()


def _resolve(*nats):
    """Premier code pour lequel un SVG existe, sinon ''.

    Sert de cascade : coureur d'abord, club ensuite
    (``_resolve(comp.nat, org.nat)``).
    """
    for nat in nats:
        code = normalize_nat(nat)
        if code and _has_flag(code):
            return code
    return ''


def nat_flag_url(*nats):
    """URL statique du drapeau pour le premier code connu, sinon ''."""
    code = _resolve(*nats)
    if not code:
        return ''
    return static(f'results/img/flags/nat/{code}.svg')


def nat_display_code(*nats):
    """Premier code normalisé non vide (``str`` réel uniquement), sinon ''.

    Sert au texte affiché à côté du drapeau (fiche coureur) : ignore les
    valeurs non chaînes (mocks de tests) et ne dépend pas de l'existence
    du SVG — le drapeau reste géré par ``nat_flag_html``.
    """
    for nat in nats:
        if isinstance(nat, str) and nat.strip():
            return normalize_nat(nat)
    return ''


def nat_flag_html(*nats, decorative=False):
    """Balise ``<img class="nat-flag">`` du premier code connu, sinon ''.

    ``decorative=True`` omits ``alt``/``title`` (drapeau porté par un nom
    déjà explicite à côté). Tout le HTML interpolé est échappé — la valeur
    provient d'un XML distant (MOP), même si le code est borné par la
    vérification d'existence du fichier.

    L'image est **suivie d'une espace** : le drapeau reste détaché du nom
    qui le suit même si ``site.css`` n'est pas à jour côté client
    (``collectstatic`` non relancé, cache du navigateur) — l'écart
    drapeau/nom ne dépend d'aucune règle CSS. Les constructions manuelles
    de la balise (templates + JS) doivent en faire autant, contrôlé par
    ``test_nat_flags.TestEspaceApresLeDrapeau``.
    """
    code = _resolve(*nats)
    if not code:
        return ''
    url = static(f'results/img/flags/nat/{code}.svg')
    label = escape(code.upper())
    alt_attr = '' if decorative else f' alt="{label}" title="{label}"'
    img = (f'<img class="nat-flag" src="{escape(url)}"{alt_attr}'
           f' loading="lazy" width="20" height="14">')
    return mark_safe(img + ' ')
