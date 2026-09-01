from django.core.exceptions import ValidationError
from django.forms import CharField, Form, TextInput, URLField


class PhotoForm(Form):
    flickr_url = URLField(
        label="Flickr URL",
        required=True,
        help_text="Only Flickr photo URLs are supported.",
    )
    credit = CharField(
        label="Credit",
        required=False,
        max_length=255,
        widget=TextInput(attrs={"placeholder": "Optional"}),
    )
    caption = CharField(
        label="Caption",
        required=False,
        max_length=255,
        widget=TextInput(attrs={"placeholder": "Optional"}),
    )

    def clean_flickr_url(self):
        url = self.cleaned_data.get("flickr_url", "")
        if url and "flickr.com" not in url.lower():
            raise ValidationError("Only Flickr URLs are allowed.")
        return url
