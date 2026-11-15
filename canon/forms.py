from django import forms


class ImportForm(forms.Form):
    archive = forms.FileField(label="The World's .zip file")
