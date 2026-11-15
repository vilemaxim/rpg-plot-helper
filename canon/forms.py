import re

import plotcanon
from django import forms
from django.conf import settings

# An LLM asked for a file often answers with the file inside a code fence, and
# sometimes a line of its own before it. A person pasting the answer should not
# have to know to take those off.
FENCED = re.compile(r"\A.*?^(```|~~~)[\w-]*[ \t]*\n(.*?\n)\1[ \t]*\n?\Z", re.S | re.M)


def unfenced(text):
    """The text inside a code fence, if the text ends in one and the fenced
    part is a file with frontmatter; otherwise the text as it was."""
    match = FENCED.match(text.rstrip() + "\n")
    if match and match.group(2).lstrip("\ufeff").startswith("---"):
        return match.group(2)
    return text


class ImportForm(forms.Form):
    archive = forms.FileField(label="The World's .zip file")


TWINE_SUFFIXES = (".twee", ".tw", ".html", ".htm")


def is_twine(name):
    """Whether an uploaded file's name says it is a Twine file: Twee, or a
    Twine 2 story saved or published as HTML."""
    return (name or "").lower().endswith(TWINE_SUFFIXES)


class FileForm(forms.Form):
    """One file, pasted or uploaded: one or the other. `cleaned_data["contents"]`
    is its text. `noun` is what the file is, for the labels and messages.

    A form that `takes_twine` also takes an uploaded Twine file, converted to
    markdown by plotcanon (ADR-0007); its `cleaned_data["twine_warnings"]`
    are what the conversion warned about, to show beside the validator's
    messages."""

    noun = "file"
    takes_twine = False

    text = forms.CharField(
        required=False, strip=False,
        widget=forms.Textarea(attrs={"rows": 18, "spellcheck": "false"}))
    file = forms.FileField(label="Or choose its file", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["text"].label = f"Paste the {self.noun}"

    def clean(self):
        cleaned = super().clean()
        cleaned["twine_warnings"] = ()
        pasted = (cleaned.get("text") or "").strip()
        uploaded = cleaned.get("file")
        if pasted and uploaded:
            raise forms.ValidationError(f"Paste the {self.noun} or choose its file, not both.")
        if not pasted and not uploaded:
            raise forms.ValidationError(f"Paste the {self.noun} or choose its file.")
        twine = uploaded and self.takes_twine and is_twine(uploaded.name)
        limit = settings.TWINE_MAX_FILE_BYTES if twine else settings.IMPORT_MAX_FILE_BYTES
        if uploaded and uploaded.size > limit:
            megabytes = limit / (1024 * 1024)
            raise forms.ValidationError(
                f"{uploaded.name} is too large. The limit is {megabytes:g} MB.")
        if twine:
            converted = plotcanon.from_twine(uploaded.read())
            if not converted.ok:
                raise forms.ValidationError(
                    f"{uploaded.name} cannot be read as a Twine file. "
                    + " ".join(converted.problems))
            cleaned["contents"] = converted.markdown
            cleaned["twine_warnings"] = converted.warnings
            return cleaned
        if uploaded:
            try:
                text = uploaded.read().decode("utf-8")
            except UnicodeDecodeError:
                raise forms.ValidationError(
                    f"{uploaded.name} is not UTF-8 text, so it cannot be read.") from None
        else:
            text = cleaned["text"]
        # A browser sends a pasted line break as two characters, and a file
        # saved on Windows has them too. A file is stored with one.
        cleaned["contents"] = unfenced(text.replace("\r\n", "\n"))
        return cleaned


class ReportForm(FileForm):
    noun = "report"


class ModForm(FileForm):
    noun = "Mod"
    takes_twine = True


class RecordForm(FileForm):
    noun = "record"


class InterludeForm(forms.Form):
    """A new Interlude: what to call it, which Campaign it belongs to and which
    Event it follows. `events` and `campaigns` are `(id, name)` pairs, the
    Events in order."""

    name = forms.CharField(max_length=200, label="What to call it")
    campaign = forms.ChoiceField(label="Campaign")
    after = forms.ChoiceField(label="It comes after")
    in_world = forms.CharField(max_length=500, label="When it is in the World",
                               help_text="A phrase, such as “the weeks after the storm”.")
    real_date = forms.DateField(label="Real-world date it begins",
                                widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, events=(), campaigns=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["after"].choices = list(events)
        self.fields["campaign"].choices = list(campaigns)
        if events:
            self.fields["after"].initial = list(events)[-1][0]

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        if not name:
            raise forms.ValidationError("Give the Interlude a name.")
        return name


class ChangeForm(forms.Form):
    """One Canon Change made during an Interlude. `entities` are `(id, name)`
    pairs and `kinds` the kinds of change plotcanon knows."""

    entity = forms.ChoiceField(label="What changes")
    kind = forms.ChoiceField(label="Kind of change")
    before = forms.CharField(required=False, max_length=200, label="From",
                             help_text="For a status, location or affiliation. Left empty "
                                       "for a status or location, it is what Canon "
                                       "says at this Interlude.")
    after = forms.CharField(required=False, max_length=200, label="To",
                            help_text="For a status, location or affiliation: the new "
                                      "value, as an id.")
    summary = forms.CharField(max_length=500, label="What happened, in one line")

    def __init__(self, *args, entities=(), kinds=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["entity"].choices = list(entities)
        self.fields["kind"].choices = list(kinds)
