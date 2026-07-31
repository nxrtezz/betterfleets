from django.forms import Form, URLField, ImageField


class PhotoForm(Form):
    url = URLField(label="Image URL", required=False)
    image = ImageField(label="Upload image", required=False)
