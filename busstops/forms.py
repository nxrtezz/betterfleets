from django import forms
from turnstile.fields import TurnstileField

from vehicles.form_fields import SummaryField

from .models import BlogPost, BlogTag, Operator, StopFeature, StopPoint


class ContactForm(forms.Form):
    name = forms.CharField(label="Name")
    email = forms.EmailField(label="Email address")
    message = forms.CharField(label="Message", widget=forms.Textarea)
    referrer = forms.CharField(
        label="Referrer", required=False, widget=forms.HiddenInput
    )
    turnstile = TurnstileField(label="Confirm that you’re a human (not a robot)")

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)


class SearchForm(forms.Form):
    q = forms.CharField(widget=forms.TextInput(attrs={"type": "search"}))


class TimetableForm(forms.Form):
    date = forms.DateField(required=False)
    day_of_week = forms.ChoiceField(
        required=False,
        choices=[
            ('', 'Select a date'),
            ('Monday', 'Monday'),
            ('Tuesday', 'Tuesday'),
            ('Wednesday', 'Wednesday'),
            ('Thursday', 'Thursday'),
            ('Friday', 'Friday'),
            ('Saturday', 'Saturday'),
            ('Sunday', 'Sunday'),
        ]
    )
    calendar = forms.IntegerField(required=False)
    detailed = forms.BooleanField(required=False)
    vehicles = forms.BooleanField(required=False)
    service = forms.MultipleChoiceField(
        required=False, widget=forms.CheckboxSelectMultiple
    )

    def __init__(self, *args, **kwargs):
        service = kwargs.pop("service")
        self.related = kwargs.pop("related")
        super().__init__(*args, **kwargs)

        line_names = service.get_line_names()
        self.fields["service"].choices = [
            (f"{service.id}:{line_name}", line_name) for line_name in line_names
        ]
        self.fields["service"].initial = [
            choice[0] for choice in self.fields["service"].choices
        ]

        if self.related:
            for s in self.related:
                self.fields["service"].choices += [
                    (f"{s.id}:{line_name}", line_name)
                    for line_name in s.get_line_names()
                ]
        if len(self.fields["service"].choices) > 1:
            self.fields["service"].choices = sorted(
                self.fields["service"].choices,
                key=lambda choice: service.get_line_name_order(choice[1]),
            )
        else:
            del self.fields["service"]

    def get_timetable(self, service):
        if self.is_valid():
            date = self.cleaned_data["date"]
            day_of_week = self.cleaned_data["day_of_week"]
            calendar_id = self.cleaned_data["calendar"]
            line_names = self.cleaned_data.get("service")
            detailed = self.cleaned_data["detailed"]
        else:
            date = None
            day_of_week = None
            calendar_id = None
            line_names = None
            detailed = False

        return service.get_timetable(
            day=date,
            day_of_week=day_of_week,
            calendar_id=calendar_id,
            also_services=self.related,
            line_names=line_names,
            detailed=detailed,
        )


class DeparturesForm(forms.Form):
    date = forms.DateField()
    time = forms.TimeField(required=False)


class FleetImportForm(forms.Form):
    operator = forms.ModelChoiceField(
        queryset=Operator.objects.order_by("name"),
        required=False,
        help_text="Optional default operator for the import. Imported operator codes can still override this per row.",
    )
    historical_fleet = forms.ModelChoiceField(
        queryset=Operator.objects.order_by("name"),
        required=False,
        help_text="Optional live operator to attach imported preserved vehicles to as a historical fleet.",
    )
    historical_year = forms.IntegerField(
        min_value=1800,
        max_value=2200,
        required=False,
        help_text="Optional default year for historical vehicle imports. Row data can still override this with a year column.",
    )
    manual_livery_selection = forms.BooleanField(
        required=False,
        help_text="Show each imported livery name and let me map it manually before commit.",
    )
    rows_text = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 18, "cols": 120}),
        help_text="Paste CSV or TSV with headers, or upload a PDF/XLSX/CSV file.",
    )
    upload = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(
            attrs={"accept": ".pdf,.xlsx,.csv,text/csv,application/vnd.ms-excel,application/pdf"}
        ),
        help_text="Upload a fleet PDF, completed .xlsx, or .csv file instead of pasting rows.",
    )


class BlogPostEditorForm(forms.ModelForm):
    tags_text = forms.CharField(
        required=False,
        label="Tags",
        help_text="Comma-separated tags. New tags will be created automatically.",
    )

    class Meta:
        model = BlogPost
        fields = ("title", "slug", "excerpt", "body")
        widgets = {
            "title": forms.TextInput(
                attrs={"placeholder": "Give the post a clear headline"}
            ),
            "slug": forms.TextInput(
                attrs={"placeholder": "Optional. Leave blank to generate from the title"}
            ),
            "excerpt": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Short standfirst or summary shown in the blog listing",
                }
            ),
            "body": forms.Textarea(
                attrs={
                    "rows": 20,
                    "placeholder": (
                        "Write the post here.\n\n"
                        "Use lines starting with ## for section headings,\n"
                        "### for smaller headings, and - for bullet lists."
                    ),
                }
            ),
        }
        help_texts = {
            "body": (
                "Plain text is fine. The public page will turn paragraphs into article sections "
                "and supports `## Heading`, `### Subheading`, and `- bullet` lines."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["tags_text"].initial = ", ".join(
                self.instance.tags.order_by("name").values_list("name", flat=True)
            )
        self.fields["slug"].required = False

    def clean_tags_text(self):
        value = self.cleaned_data.get("tags_text", "")
        tags = []
        seen = set()
        for item in value.split(","):
            name = item.strip()
            if not name:
                continue
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            tags.append(name)
        return tags

    def save(self, *, publish=None, commit=True):
        instance = super().save(commit=False)
        if publish is not None:
            instance.published = publish
        if instance.published and not instance.published_at:
            from django.utils import timezone

            instance.published_at = timezone.now()
        if not instance.published and publish is False:
            instance.published_at = None
        if commit:
            instance.save()
            tags = []
            for name in self.cleaned_data.get("tags_text", []):
                tag, _created = BlogTag.objects.get_or_create(name=name)
                tags.append(tag)
            instance.tags.set(tags)
        return instance


class EditStopForm(forms.Form):
    field_order = [
        "common_name",
        "indicator",
        "landmark",
        "street",
        "crossing",
        "description",
        "notes",
        "features",
        "accessibility_features",
        "summary",
    ]

    common_name = forms.CharField(max_length=48, required=False, label="Stop name")
    indicator = forms.CharField(max_length=48, required=False)
    landmark = forms.CharField(max_length=48, required=False)
    street = forms.CharField(max_length=48, required=False)
    crossing = forms.CharField(max_length=48, required=False)
    description = forms.CharField(max_length=255, required=False)
    notes = forms.CharField(max_length=255, required=False)
    features = forms.ModelMultipleChoiceField(
        queryset=StopFeature.objects.filter(category=StopFeature.Category.FEATURE),
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    accessibility_features = forms.ModelMultipleChoiceField(
        queryset=StopFeature.objects.filter(category=StopFeature.Category.ACCESSIBILITY),
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    summary = SummaryField(
        max_length=255,
        help_text="Explain your changes and how you know they are correct.",
    )

    def __init__(self, data=None, *args, stop: StopPoint, **kwargs):
        super().__init__(data, *args, **kwargs)
        self.fields["common_name"].initial = stop.common_name
        self.fields["indicator"].initial = stop.indicator
        self.fields["landmark"].initial = stop.landmark
        self.fields["street"].initial = stop.street
        self.fields["crossing"].initial = stop.crossing
        self.fields["description"].initial = stop.description or ""
        self.fields["notes"].initial = stop.notes or ""
        self.fields["features"].initial = stop.features.filter(
            category=StopFeature.Category.FEATURE
        )
        self.fields["accessibility_features"].initial = stop.features.filter(
            category=StopFeature.Category.ACCESSIBILITY
        )
