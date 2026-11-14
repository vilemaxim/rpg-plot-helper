from django import forms


class SignInForm(forms.Form):
    email = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
    )
    next = forms.CharField(required=False, max_length=2000, widget=forms.HiddenInput)
