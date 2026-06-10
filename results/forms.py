from django import forms


class MeosFileForm(forms.Form):
    meosfile = forms.FileField(label="Fichier MeOS (.xml)")


class VerifieMoiFileForm(forms.Form):
    meosfile = forms.FileField(label="Fichier MeOS (.xml)")