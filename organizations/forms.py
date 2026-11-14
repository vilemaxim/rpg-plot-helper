from django import forms


class WorldForm(forms.Form):
    name = forms.CharField(label="Name of the new World", max_length=200)


class InvitationForm(forms.Form):
    email = forms.EmailField(label="Email address to invite", max_length=254)
