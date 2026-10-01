from django import forms

RULE_CHOICES = [
    ('club_consecutif',   'R1 — Pas de club consécutif sur le même circuit'),
    ('entrelacement',     "R2 — Pas d'entrelacement de catégories"),
    ('premiers_postes',   'R3 — Pas de premier poste commun entre circuits'),
    ('plages_continues',  'R4 — Regroupement des catégories sur des plages continues'),
    ('coordonnees_postes','R5 — Coordonnées des postes (xpos / ypos)'),
    ('circuits_vides',    'R6 — Pas de circuits vides'),
    ('categories_vides',  'R7 — Pas de catégories vides'),
    ('completude_coureurs','R8 — Complétude des données coureurs'),
]
_ALL_RULES = [c[0] for c in RULE_CHOICES]


class MeosFileForm(forms.Form):
    meosfile = forms.FileField(label="Fichier MeOS (.xml)")
    gap_seconds = forms.IntegerField(
        label="Écart min. entre 2 coureurs du même club (secondes)",
        initial=120, min_value=1, required=False,
        help_text="Si deux coureurs du même club sont séparés par un écart inférieur ou égal "
                  "à cette valeur, ils sont considérés consécutifs.",
    )
    enabled_rules = forms.MultipleChoiceField(
        choices=RULE_CHOICES,
        initial=_ALL_RULES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Règles à vérifier",
    )


class VerifieMoiFileForm(forms.Form):
    meosfile = forms.FileField(label="Fichier MeOS (.xml)")


class RaceBaseForm(forms.Form):
    """Champs communs création/édition d'une course (cf. race_views)."""

    name = forms.CharField(label="Nom de la course", max_length=64)
    date = forms.DateField(
        label="Date",
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    organizer = forms.CharField(label="Organisateur / club", max_length=64)
    homepage = forms.URLField(
        label="Site web de l'organisateur",
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
        label="Site web (champ piège)",
        required=False,
        widget=forms.TextInput(attrs={'autocomplete': 'off', 'tabindex': '-1'}),
    )
    token = forms.CharField(required=False, widget=forms.HiddenInput)


class RaceEditForm(RaceBaseForm):
    """Formulaire d'édition d'une course via son lien privé de gestion."""