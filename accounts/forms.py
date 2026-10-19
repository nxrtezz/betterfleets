from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, UserCreationForm
from django.contrib.auth.models import Permission
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.db.models.functions import Now
from django.forms import (
    BooleanField,
    CharField,
    CheckboxSelectMultiple,
    EmailField,
    EmailInput,
    Form,
    ModelMultipleChoiceField,
)

User = get_user_model()


class RegistrationForm(UserCreationForm):
    email = EmailField(
        label="Email address",
        widget=EmailInput(attrs={"autofocus": True, "autocomplete": "email"}),
        help_text="Will be kept private"
    )
    first_name = CharField(label="First name", max_length=150)
    last_name = CharField(label="Last name", max_length=150)
    username = CharField(
        label="Username",
        max_length=150,
        required=False,
        validators=[UnicodeUsernameValidator()],
        help_text="Optional. Will be displayed publicly. Leave blank to be 'user [id]'"
    )

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "username", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True

    def save(self, request=None):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        
        username = self.cleaned_data.get("username")
        if username:
            user.username = username
        else:
            user.username = user.email
        
        user.is_active = True
        user.save()
        self.user = user
        return user


class LoginForm(AuthenticationForm):
    username = EmailField(
        widget=EmailInput(attrs={"autofocus": True, "autocomplete": "email"})
    )


class UserForm(Form):
    first_name = CharField(label="First name", max_length=150, required=False)
    last_name = CharField(label="Last name", max_length=150, required=False)
    name = CharField(
        required=False,
        label="Username",
        validators=[UnicodeUsernameValidator()],
        max_length=50,
    )

    def __init__(self, data, *args, user, **kwargs):
        super().__init__(data, *args, **kwargs)

        self.fields["first_name"].initial = user.first_name
        self.fields["last_name"].initial = user.last_name
        self.fields["name"].initial = (
            user.username if user.username != user.email else ""
        )
        self.fields["name"].help_text = f"""Will be displayed publicly.
Leave blank to be 'user {user.id}'"""
        self.fields["name"].widget.attrs["placeholder"] = f"user {user.id}"


class UserPermissionsForm(Form):
    permissions = ModelMultipleChoiceField(
        queryset=None, widget=CheckboxSelectMultiple, required=False
    )

    def __init__(self, data, *args, user, **kwargs):
        super().__init__(data, *args, **kwargs)

        self.fields["permissions"].initial = user.user_permissions.all()
        self.fields["permissions"].queryset = Permission.objects.filter(
            codename__in=(
                "add_vehiclerevision",
                "change_vehiclerevision",
                "change_vehicle",
            )
        ).select_related("content_type")


class DeleteForm(Form):
    confirm_delete = BooleanField(label="Please delete my account")
