import os

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext, gettext_lazy as _

RULE_CHOICES = [
    ('club_consecutif',   _('R1 — Pas de club consécutif sur le même circuit')),
    ('entrelacement',     _("R2 — Pas d'entrelacement de catégories")),
    ('premiers_postes',   _('R3 — Pas de premier poste commun entre circuits')),
    ('plages_continues',  _('R4 — Regroupement des catégories sur des plages continues')),
    ('coordonnees_postes', _('R5 — Coordonnées des postes (xpos / ypos)')),
    ('circuits_vides',    _('R6 — Pas de circuits vides')),
    ('categories_vides',  _('R7 — Pas de catégories vides')),
    ('completude_coureurs', _('R8 — Complétude des données coureurs')),
]
_ALL_RULES = [c[0] for c in RULE_CHOICES]


class MeosFileForm(forms.Form):
    meosfile = forms.FileField(label=_("Fichier MeOS (.xml)"))
    gap_seconds = forms.IntegerField(
        label=_("Écart min. entre 2 coureurs du même club (secondes)"),
        initial=120, min_value=1, required=False,
        help_text=_("Si deux coureurs du même club sont séparés par un écart inférieur ou égal "
                    "à cette valeur, ils sont considérés consécutifs."),
    )
    enabled_rules = forms.MultipleChoiceField(
        choices=RULE_CHOICES,
        initial=_ALL_RULES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label=_("Règles à vérifier"),
    )


class VerifieMoiFileForm(forms.Form):
    meosfile = forms.FileField(label=_("Fichier MeOS (.xml)"))


# ─── Logo d'organisateur (upload à la création de course) ─────────────────────

LOGO_EXTENSIONS = ('.svg', '.png', '.jpg', '.jpeg')
LOGO_MAX_BYTES = 2 * 1024 * 1024          # 2 Mo

_PNG_MAGIC = b'\x89PNG\r\n\x1a\n'
_JPEG_MAGIC = b'\xff\xd8\xff'


def validate_org_logo(uploaded):
    """Valide un logo d'organisateur : extension, taille, contenu.

    Le sniffing des octets empêche un fichier exécutable déguisé en .png/.svg ;
    un SVG doit commencer par ``<svg`` / ``<?xml`` / ``<!DOCTYPE``.
    """
    ext = os.path.splitext((uploaded.name or '').lower())[1]
    if ext not in LOGO_EXTENSIONS:
        raise ValidationError(gettext("Format accepté : SVG, PNG ou JPEG."))
    if uploaded.size > LOGO_MAX_BYTES:
        raise ValidationError(gettext("Logo trop volumineux (2 Mo maximum)."))

    head = uploaded.read(512)
    uploaded.seek(0)
    if ext == '.png':
        ok = head.startswith(_PNG_MAGIC)
    elif ext in ('.jpg', '.jpeg'):
        ok = head.startswith(_JPEG_MAGIC)
    else:                                   # .svg
        text = head.decode('utf-8', errors='ignore')
        text = text.lstrip('\ufeff \t\r\n').lower()
        ok = text.startswith(('<svg', '<?xml', '<!doctype'))
    if not ok:
        raise ValidationError(gettext("Fichier illisible — SVG, PNG ou JPEG attendu."))


class RaceBaseForm(forms.Form):
    """Champs communs création/édition d'une course (cf. race_views)."""

    name = forms.CharField(label=_("Nom de la course"), max_length=64)
    date = forms.DateField(
        label=_("Date"),
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    organizer = forms.CharField(label=_("Organisateur / club"), max_length=64)
    homepage = forms.URLField(
        label=_("Site web de l'organisateur"),
        max_length=128,
        required=False,
        assume_scheme='https',
    )
    livelox = forms.URLField(
        label="Livelox",
        max_length=128,
        required=False,
        assume_scheme='https',
    )


class RaceCreateForm(RaceBaseForm):
    """Formulaire public de création de course (sans compte).

    Protections anti-spam :
    - ``website`` : honeypot, invisible pour un humain (cf. template) ;
    - ``token``   : jeton signé horodaté, imposant un remplissage d'au
      moins MIN_FILL_SECONDS (vérifié dans race_views).
    """

    website = forms.CharField(
        label=_("Site web (champ piège)"),
        required=False,
        widget=forms.TextInput(attrs={'autocomplete': 'off', 'tabindex': '-1'}),
    )
    token = forms.CharField(required=False, widget=forms.HiddenInput)
    logo = forms.FileField(
        label=_("Logo de l'organisateur"),
        required=False,
        validators=[validate_org_logo],
    )


class RaceEditForm(RaceBaseForm):
    """Formulaire d'édition d'une course via son lien privé de gestion."""