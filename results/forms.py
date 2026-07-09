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