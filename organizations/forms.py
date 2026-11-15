import unicodedata

import plotcanon
from django import forms

# Characters that turn the text after them back to front, or embed or isolate
# a run of it. In a name they let one thing be shown and another be meant.
DIRECTION_OVERRIDES = set("‪‫‬‭‮⁦⁧⁨⁩")


class NameField(forms.CharField):
    """The name of an Organization or a World.

    Names appear in page headers, lists and email subjects, so a name must be
    one line, must have something in it a person can see, and must not carry
    characters that control how text is drawn.
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", 200)
        super().__init__(**kwargs)

    def to_python(self, value):
        # Line breaks, tabs and runs of spaces all become one space.
        return " ".join(super().to_python(value).split())

    def validate(self, value):
        super().validate(value)
        categories = [unicodedata.category(character) for character in value]
        if "Cc" in categories or DIRECTION_OVERRIDES & set(value):
            raise forms.ValidationError("Some characters in that cannot be used in a name.")
        # Control, format and separator characters draw nothing on their own.
        if not any(category[0] not in "CZ" for category in categories):
            raise forms.ValidationError("Enter a name people can see.")


class WorldForm(forms.Form):
    name = NameField(label="Name of the new World")


class NameForm(forms.Form):
    """A new name for an Organization or a World."""

    name = NameField(label="Name")


class InvitationForm(forms.Form):
    email = forms.EmailField(label="Email address to invite", max_length=254)


def dry_run_structures():
    """The settings a World's Dry Run structure may have, each with what it
    means, in plotcanon's words: the setting is plotcanon's (ADR-0004)."""
    meanings = plotcanon.vocabularies()["vocabularies"]["dry_run_structure"]
    return [(value, f"{value.capitalize()}: {meaning}") for value, meaning in meanings.items()]


class DryRunStructureForm(forms.Form):
    """How strictly Mods must be written so that a Dry Run can be built from
    them: for one World, or the default an Organization gives its new Worlds."""

    structure = forms.ChoiceField(label="Dry Run structure", choices=dry_run_structures,
                                  widget=forms.RadioSelect)
