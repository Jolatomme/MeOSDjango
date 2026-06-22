from django import forms


class MeosFileForm(forms.Form):
    meosfile = forms.FileField(label="Fichier MeOS (.xml)")
    gap_seconds = forms.IntegerField(
        label="Écart min. entre 2 coureurs du même club (secondes)",
        initial=120, min_value=1, required=False,
        help_text="Si deux coureurs du même club sont séparés par un écart inférieur ou égal "
                  "à cette valeur, ils sont considérés consécutifs.",
    )
    check_entrelacement = forms.BooleanField(
        label="Vérifier l'entrelacement des catégories",
        initial=True, required=False,
        help_text="Décocher pour ignorer la règle d'entrelacement des catégories sur un même circuit.",
    )


class VerifieMoiFileForm(forms.Form):
    meosfile = forms.FileField(label="Fichier MeOS (.xml)")