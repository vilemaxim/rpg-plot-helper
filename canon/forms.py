import re

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


class FileForm(forms.Form):
    """One file, pasted or uploaded: one or the other. `cleaned_data["contents"]`
    is its text. `noun` is what the file is, for the labels and messages."""

    noun = "file"

    text = forms.CharField(
        required=False, strip=False,
        widget=forms.Textarea(attrs={"rows": 18, "spellcheck": "false"}))
    file = forms.FileField(label="Or choose its file", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["text"].label = f"Paste the {self.noun}"

    def clean(self):
        cleaned = super().clean()
        pasted = (cleaned.get("text") or "").strip()
        uploaded = cleaned.get("file")
        if pasted and uploaded:
            raise forms.ValidationError(f"Paste the {self.noun} or choose its file, not both.")
        if not pasted and not uploaded:
            raise forms.ValidationError(f"Paste the {self.noun} or choose its file.")
        if uploaded and uploaded.size > settings.IMPORT_MAX_FILE_BYTES:
            megabytes = settings.IMPORT_MAX_FILE_BYTES / (1024 * 1024)
            raise forms.ValidationError(
                f"{uploaded.name} is too large. The limit is {megabytes:g} MB.")
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
