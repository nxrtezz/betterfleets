from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError
from django.db.models.functions import Now
from django.forms import (
    BooleanField,
    CharField,
    CheckboxSelectMultiple,
    EmailField,
    EmailInput,
    Form,
    ModelForm,
    ModelMultipleChoiceField,
)

from .models import ProfileTag, User
User = get_user_model()


class UserForm(ModelForm):
    username = CharField(
        required=False,
        label="Username",
        validators=[UnicodeUsernameValidator()],
        max_length=50,
    )

    class Meta:
        model = User
        fields = [
            "username",
            "display_name",
            "first_name",
            "last_name",
            "flickr_username",
            "discord_username",
            "discord_user_id",
            "fleet_logging_public",
            "profile_picture",
            "profile_banner",
            "view_advanced",
        ]

    def __init__(self, data=None, files=None, *args, user, **kwargs):
        if data and "name" in data and "username" not in data:
            data = data.copy()
            data["username"] = data.get("name")
        super().__init__(data=data, files=files, *args, **kwargs)
        self.user = user
        self.fields["username"].initial = (
            user.username if user.username != user.email else ""
        )
        self.fields["username"].help_text = (
            f"Shown publicly as @{user.get_username_display()}. "
            f"Leave blank to use 'user{user.id}'."
        )
        self.fields["username"].widget.attrs["placeholder"] = f"user{user.id}"
        self.fields["display_name"].help_text = (
            "If set, this is shown on edits and reviews instead of your username."
        )
        self.fields["flickr_username"].help_text = "Optional Flickr username for your profile."
        self.fields["discord_username"].help_text = "Optional Discord username for your profile."
        self.fields["discord_user_id"].help_text = (
            "Optional numeric Discord user ID for the live Discord profile card."
        )
        self.fields["fleet_logging_public"].help_text = (
            "Allow ride logging totals to appear on your public profile."
        )

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if not username:
            return self.instance.email
        return username

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data["username"]
        if commit:
            user.save()
        return user


class UserPermissionsForm(Form):
    permissions = ModelMultipleChoiceField(
        queryset=None, widget=CheckboxSelectMultiple, required=False
    )
    blocked_from_reviews = BooleanField(
        required=False,
        label="Block from reviews",
    )
    manual_tags = ModelMultipleChoiceField(
        queryset=ProfileTag.objects.none(),
        widget=CheckboxSelectMultiple,
        required=False,
        label="Profile tags",
    )

    def __init__(self, data, *args, user, **kwargs):
        super().__init__(data, *args, **kwargs)

        self.fields["permissions"].initial = user.user_permissions.all()
        self.fields["permissions"].queryset = Permission.objects.filter(
            codename__in=(
                "add_blogpost",
                "change_blogpost",
                "add_vehiclerevision",
                "change_vehiclerevision",
                "change_vehicle",
                "use_beta_features",
            )
        ).select_related("content_type")
        self.fields["blocked_from_reviews"].initial = user.blocked_from_reviews
        self.fields["manual_tags"].initial = user.manual_tags.all()
        self.fields["manual_tags"].queryset = ProfileTag.objects.all()


class DeleteForm(Form):
    confirm_delete = BooleanField(label="Please delete my account")
