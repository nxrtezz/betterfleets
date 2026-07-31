from django import forms
from django.conf import settings
from django.contrib.admin.widgets import AutocompleteSelect
from django.core.exceptions import ValidationError
from decimal import Decimal

from busstops.models import Manufacturer, Operator, OperatorVehicleColumn
from bustimes.models import Garage

from .fields import validate_colours
from .form_fields import RegField, SummaryField
from .models import Livery, Vehicle, VehicleFeature, VehicleReview, VehicleType


class AutocompleteWidget(forms.Select):
    # optgroups method from the Django admin AutocompleteSelect widget
    optgroups = AutocompleteSelect.optgroups

    def __init__(self, field=None, attrs=None, choices=(), using=None):
        self.field = field
        self.attrs = {} if attrs is None else attrs.copy()
        self.choices = choices
        self.db = None


class OperatorVehicleColumnFieldsMixin:
    custom_column_field_prefix = "operator_column_"

    def add_operator_vehicle_column_fields(self, operator, values=None):
        self.operator_vehicle_columns = []
        self.operator_vehicle_column_fields = {}
        if not operator:
            return

        self.operator_vehicle_columns = list(
            OperatorVehicleColumn.objects.filter(operator=operator).order_by(
                "display_order", "name"
            )
        )
        values = values or {}
        for column in self.operator_vehicle_columns:
            field_name = f"{self.custom_column_field_prefix}{column.pk}"
            self.fields[field_name] = forms.CharField(
                label=column.name,
                help_text=column.help_text,
                max_length=255,
                required=False,
            )
            self.fields[field_name].initial = (
                values.get(column.slug) or values.get(column.name) or ""
            )
            self.operator_vehicle_column_fields[field_name] = column

    def get_operator_vehicle_column_updates(self):
        updates = {}
        for field_name, column in self.operator_vehicle_column_fields.items():
            if field_name not in self.changed_data:
                continue
            updates[column.slug] = (self.cleaned_data.get(field_name) or "").strip()
        return updates


class EditVehicleForm(OperatorVehicleColumnFieldsMixin, forms.Form):
    FLEET_SUPPORT_FEATURE_ID = "8"

    @property
    def media(self):
        return forms.Media(
            js=(
                "admin/js/vendor/jquery/jquery.min.js",
                "admin/js/vendor/select2/select2.full.min.js",
                "js/edit-vehicle.js",
            ),
            css={
                "screen": ("admin/css/vendor/select2/select2.min.css",),
            },
        )

    field_order = [
        "withdrawn",
        "preserved",
        "fleet_support_vehicle",
        "vor",
        "awaiting_delivery",
        "trainer_vehicle",
        "demonstrator",
        "spare_ticket_machine",
        "fleet_number",
        "reg",
        "operator",
        "operated_by",
        "garage",
        "vehicle_type",
        "colours",
        "other_colour",
        "branding",
        "rear_advert",
        "name",
        "previous_reg",
        "joined_fleet",
        "left_fleet",
        "previous_operators",
        "add_previous_operator",
        "add_previous_operator_joined_fleet",
        "features",
        "accessibility_features",
        "notes",
    ]
    spare_ticket_machine = forms.BooleanField(
        required=False,
        help_text="i.e. the ticket machine code is something like SPARE",
    )
    withdrawn = forms.BooleanField(
        label="Remove from list",
        required=False,
        help_text="Rarely necessary, unless you're sure this vehicle has definitely been permenantly withdrawn",
    )
    preserved = forms.BooleanField(
        required=False,
        help_text="For preserved vehicles kept as records outside the active fleet list.",
    )
    fleet_support_vehicle = forms.BooleanField(
        required=False,
        label="Fleet Support Vehicle",
        help_text="Use for fleet support vehicles. This stays in sync with the Fleet Support feature.",
    )
    vor = forms.BooleanField(
        required=False,
        label="VOR",
        help_text="Vehicle off road.",
    )
    awaiting_delivery = forms.BooleanField(
        required=False,
        help_text="Use for vehicles that are still awaiting delivery or entry into service.",
    )
    trainer_vehicle = forms.BooleanField(
        required=False,
        help_text="Use for vehicles primarily assigned to training duties.",
    )
    demonstrator = forms.BooleanField(
        required=False,
        help_text="Use for demonstrators so they appear in manufacturer demonstrator fleets.",
    )

    fleet_number = forms.CharField(required=False, max_length=24)
    reg = RegField(label="Number plate", required=False, max_length=24)

    operator = forms.ModelChoiceField(
        queryset=Operator.objects,
        widget=AutocompleteWidget(field=Vehicle.operator.field),
        required=False,
        empty_label="",
    )
    operated_by = forms.ModelChoiceField(
        queryset=Operator.objects,
        widget=AutocompleteWidget(field=Vehicle.operated_by.field),
        required=False,
        empty_label="",
        help_text="Operator that operates this vehicle (if different from the owner)",
    )
    garage = forms.ModelChoiceField(
        queryset=Garage.objects,
        required=False,
        empty_label="---------",
    )

    vehicle_type = forms.ModelChoiceField(
        widget=AutocompleteWidget(field=Vehicle.vehicle_type.field),
        queryset=VehicleType.objects,
        required=False,
        empty_label="",
    )

    colours = forms.ModelChoiceField(
        widget=AutocompleteWidget(field=Vehicle.livery.field),
        label="Current livery",
        queryset=Livery.objects,
        required=False,
        help_text="""Don't change this until the bus has *been painted*
(<em>not</em> just "in the paint shop" or "awaiting repaint")""",
    )
    other_colour = forms.CharField(
        label="Other colours",
        help_text="E.g. '#c0c0c0 #ff0000 #ff0000' (red with a silver front)",
        validators=[validate_colours],
        required=False,
        max_length=255,
    )

    branding = forms.CharField(
        label="Other branding",
        required=False,
        max_length=40,
        help_text="If it's interesting or unusual",
    )
    rear_advert = forms.CharField(
        label="Rear advert",
        required=False,
        max_length=255,
        help_text="Rear advert or campaign branding shown on the back of the vehicle.",
    )
    name = forms.CharField(
        label="Vehicle name",
        required=False,
        max_length=40,
    )
    previous_reg = RegField(
        required=False,
        help_text="Separate multiple regs with a comma (,)",
    )

    joined_fleet = forms.CharField(
        label="New to fleet",
        required=False,
        max_length=7,
        help_text="MM-YYYY format (e.g., 01-2024)",
    )
    left_fleet = forms.CharField(
        label="Left fleet",
        required=False,
        max_length=7,
        help_text="MM-YYYY format (e.g., 12-2024)",
    )

    previous_operators = forms.CharField(
        label="Previous operators",
        required=False,
        widget=forms.HiddenInput,
    )

    # Helper field for adding a new previous operator
    add_previous_operator = forms.ModelChoiceField(
        queryset=Operator.objects,
        widget=AutocompleteWidget(field=Vehicle.operator.field),
        required=False,
        empty_label="",
        label="Add previous operator",
    )
    add_previous_operator_joined_fleet = forms.CharField(
        required=False,
        max_length=7,
        label="Joined fleet",
        help_text="MM-YYYY format (e.g., 01-2024)",
    )

    features = forms.ModelMultipleChoiceField(
        queryset=VehicleFeature.objects.filter(category=VehicleFeature.Category.FEATURE),
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    accessibility_features = forms.ModelMultipleChoiceField(
        queryset=VehicleFeature.objects.filter(
            category=VehicleFeature.Category.ACCESSIBILITY
        ),
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    notes = forms.CharField(required=False, max_length=255)
    summary = SummaryField(
        max_length=255,
        help_text="""Explain your changes,
if they need explaining.
E.g. how you *know* a vehicle has *definitely been* withdrawn or repainted,
link to a picture to prove it. Be polite.""",
    )

    def clean_reg(self):
        reg = self.cleaned_data["reg"].replace(".", "")
        if self.cleaned_data.get("spare_ticket_machine") and reg:
            raise ValidationError(
                "A spare ticket machine can\u2019t have a number plate"
            )
        return reg

    def clean_previous_operators(self):
        import json
        value = self.cleaned_data.get("previous_operators", "").strip()
        if not value:
            return []
        try:
            data = json.loads(value)
            if not isinstance(data, list):
                raise ValidationError("Previous operators must be a list")
            for item in data:
                if not isinstance(item, dict):
                    raise ValidationError("Each previous operator must be an object")
                if "operator_id" not in item:
                    raise ValidationError("Each previous operator must have an operator_id")
            return data
        except json.JSONDecodeError:
            raise ValidationError("Invalid JSON format")

    def clean(self):
        cleaned_data = super().clean()
        # Handle adding a new previous operator from the helper fields
        add_operator = cleaned_data.get("add_previous_operator")
        add_joined_fleet = cleaned_data.get("add_previous_operator_joined_fleet", "").strip()
        
        if add_operator and add_joined_fleet:
            # Get existing previous operators
            import json
            existing = cleaned_data.get("previous_operators", "[]")
            if existing:
                try:
                    existing_list = json.loads(existing) if isinstance(existing, str) else existing
                except json.JSONDecodeError:
                    existing_list = []
            else:
                existing_list = []
            
            # Add the new operator
            existing_list.append({
                "operator_id": add_operator.id,
                "operator_name": str(add_operator),
                "joined_fleet": add_joined_fleet
            })
            
            # Update the hidden field
            cleaned_data["previous_operators"] = json.dumps(existing_list)
        
        # Clear the helper fields so they don't interfere
        cleaned_data["add_previous_operator"] = None
        cleaned_data["add_previous_operator_joined_fleet"] = ""
        
        return cleaned_data

    @classmethod
    def _normalize_bound_data(cls, data):
        if not data:
            return data

        data = data.copy()
        feature_ids = data.getlist("features")
        has_status = bool(data.get("fleet_support_vehicle"))
        has_feature = cls.FLEET_SUPPORT_FEATURE_ID in feature_ids

        if has_status or has_feature:
            data["fleet_support_vehicle"] = "on"
            if not has_feature:
                data.setlist(
                    "features",
                    feature_ids + [cls.FLEET_SUPPORT_FEATURE_ID],
                )
        else:
            data.pop("fleet_support_vehicle", None)

        return data

    def __init__(self, data, *args, user, vehicle, sibling_vehicles, **kwargs):
        super().__init__(self._normalize_bound_data(data), *args, **kwargs)

        self.fields["operator"].initial = vehicle.operator
        self.fields["operated_by"].initial = vehicle.operated_by
        self.fields["garage"].initial = vehicle.garage
        
        # Filter garage queryset by operator like Django admin
        if "operator" in self.fields and "garage" in self.fields:
            operator = vehicle.operator
            if operator:
                self.fields["garage"].queryset = self.fields["garage"].queryset.filter(operators=operator)
            else:
                self.fields["garage"].queryset = self.fields["garage"].queryset.none()
        
        self.fields["reg"].initial = vehicle.reg
        self.fields["vehicle_type"].initial = vehicle.vehicle_type
        self.fields["colours"].initial = vehicle.livery_id

        if not vehicle.vehicle_type_id:
            self.fields["vehicle_type"].widget.attrs["data-suggested"] = ",".join(
                str(v.vehicle_type_id)
                for v in sibling_vehicles
                if v and v.vehicle_type_id
            )
        if not vehicle.livery_id:
            self.fields["colours"].widget.attrs["data-suggested"] = ",".join(
                str(v.livery_id) for v in sibling_vehicles if v and v.livery_id
            )

        self.fields["other_colour"].initial = vehicle.colours or ""
        self.fields["accessibility_features"].initial = vehicle.features.filter(
            category=VehicleFeature.Category.ACCESSIBILITY
        )
        self.fields["features"].initial = vehicle.features.filter(
            category=VehicleFeature.Category.FEATURE
        )
        self.fields["branding"].initial = vehicle.branding
        self.fields["rear_advert"].initial = vehicle.rear_advert
        self.fields["name"].initial = vehicle.name
        self.fields["previous_reg"].initial = vehicle.prev_registration or (
            vehicle.data and vehicle.data.get("Previous reg") or None
        )
        self.fields["joined_fleet"].initial = vehicle.joined_fleet or ""
        self.fields["left_fleet"].initial = vehicle.left_fleet or ""
        if vehicle.previous_operators:
            import json
            self.fields["previous_operators"].initial = json.dumps(vehicle.previous_operators)
        # Don't initialize helper fields - they're for adding new entries only
        self.fields["notes"].initial = vehicle.notes
        self.fields["withdrawn"].initial = vehicle.withdrawn
        self.fields["preserved"].initial = vehicle.preserved
        self.fields["fleet_support_vehicle"].initial = vehicle.fleet_support_vehicle
        self.fields["vor"].initial = vehicle.vor
        self.fields["awaiting_delivery"].initial = vehicle.awaiting_delivery
        self.fields["trainer_vehicle"].initial = vehicle.trainer_vehicle
        self.fields["demonstrator"].initial = vehicle.demonstrator
        self.fields["spare_ticket_machine"].initial = vehicle.is_spare_ticket_machine()
        self.add_operator_vehicle_column_fields(vehicle.operator, vehicle.data)

        if self.fields["fleet_support_vehicle"].initial:
            feature_ids = {feature.id for feature in self.fields["features"].initial}
            feature_ids.add(8)
            self.fields["features"].initial = VehicleFeature.objects.filter(id__in=feature_ids)

        if vehicle.fleet_code:
            self.fields["fleet_number"].initial = vehicle.fleet_code
        elif vehicle.fleet_number is not None:
            self.fields["fleet_number"].intial = str(vehicle.fleet_number)

        if vehicle.vehicle_type_id and not vehicle.is_spare_ticket_machine():
            del self.fields["spare_ticket_machine"]

        if not (vehicle.livery_id and vehicle.vehicle_type_id and vehicle.reg):
            self.fields["summary"].required = False
            self.fields["summary"].label = "Summary (optional)"

        if not user.is_superuser:
            if not (
                vehicle.notes
                or vehicle.operator_id in settings.ALLOW_VEHICLE_NOTES_OPERATORS
            ):
                del self.fields["notes"]

        if vehicle.is_spare_ticket_machine():
            del self.fields["notes"]
            if not vehicle.fleet_code:
                del self.fields["fleet_number"]
            if not vehicle.reg:
                del self.fields["reg"]
            if not vehicle.vehicle_type_id:
                del self.fields["vehicle_type"]
            if not vehicle.name:
                del self.fields["name"]
            if not vehicle.prev_registration and not vehicle.data:
                del self.fields["previous_reg"]
            if (
                not vehicle.colours
                and not vehicle.livery_id
                and "colours" in self.fields
            ):
                del self.fields["colours"]
                del self.fields["other_colour"]
            if not vehicle.branding:
                del self.fields["branding"]
            if not vehicle.rear_advert:
                del self.fields["rear_advert"]
            if not vehicle.features.all():
                del self.fields["features"]
            if not vehicle.features.filter(
                category=VehicleFeature.Category.ACCESSIBILITY
            ).exists():
                del self.fields["accessibility_features"]

        if self.operator_vehicle_column_fields:
            ordered_fields = [name for name in self.field_order if name in self.fields]
            custom_field_names = list(self.operator_vehicle_column_fields)
            if "summary" in ordered_fields:
                ordered_fields.remove("summary")
                ordered_fields.extend(custom_field_names)
                ordered_fields.append("summary")
            else:
                ordered_fields.extend(custom_field_names)
            self.order_fields(ordered_fields)


class DebuggerForm(forms.Form):
    data = forms.CharField(widget=forms.Textarea(attrs={"rows": 6}))


class DateForm(forms.Form):
    date = forms.DateField()


class RulesForm(forms.Form):
    rules = forms.BooleanField(label="I've read the rules", required=True)


class NewVehicleRequestForm(OperatorVehicleColumnFieldsMixin, forms.Form):
    FLEET_SUPPORT_FEATURE_ID = EditVehicleForm.FLEET_SUPPORT_FEATURE_ID

    @property
    def media(self):
        return EditVehicleForm.media.fget(self)

    field_order = [
        "operator",
        "code",
        "fleet_number",
        "reg",
        "vehicle_type",
        "colours",
        "other_colour",
        "branding",
        "rear_advert",
        "name",
        "previous_reg",
        "withdrawn",
        "preserved",
        "fleet_support_vehicle",
        "vor",
        "awaiting_delivery",
        "trainer_vehicle",
        "demonstrator",
        "spare_ticket_machine",
        "features",
        "accessibility_features",
        "notes",
        "summary",
    ]

    operator = forms.ModelChoiceField(
        queryset=Operator.objects,
        widget=AutocompleteWidget(field=Vehicle.operator.field),
        required=True,
        empty_label="",
    )
    code = forms.CharField(
        label="Ticket machine code",
        max_length=255,
        help_text="The machine or vehicle code used by this operator.",
    )
    fleet_number = forms.CharField(required=False, max_length=24)
    reg = RegField(label="Number plate", required=False, max_length=24)
    vehicle_type = forms.ModelChoiceField(
        widget=AutocompleteWidget(field=Vehicle.vehicle_type.field),
        queryset=VehicleType.objects,
        required=False,
        empty_label="",
    )
    colours = forms.ModelChoiceField(
        widget=AutocompleteWidget(field=Vehicle.livery.field),
        label="Current livery",
        queryset=Livery.objects,
        required=False,
        help_text="""Only use this if the vehicle is definitely in that livery already.""",
    )
    other_colour = forms.CharField(
        label="Other colours",
        help_text="E.g. '#c0c0c0 #ff0000 #ff0000' (red with a silver front)",
        validators=[validate_colours],
        required=False,
        max_length=255,
    )
    branding = forms.CharField(
        label="Other branding",
        required=False,
        max_length=40,
    )
    rear_advert = forms.CharField(
        label="Rear advert",
        required=False,
        max_length=255,
    )
    name = forms.CharField(
        label="Vehicle name",
        required=False,
        max_length=40,
    )
    previous_reg = RegField(
        required=False,
        help_text="Separate multiple regs with a comma (,)",
    )
    withdrawn = forms.BooleanField(
        label="Remove from list",
        required=False,
    )
    preserved = forms.BooleanField(required=False)
    fleet_support_vehicle = forms.BooleanField(
        required=False,
        label="Fleet Support Vehicle",
    )
    vor = forms.BooleanField(
        required=False,
        label="VOR",
    )
    awaiting_delivery = forms.BooleanField(required=False)
    trainer_vehicle = forms.BooleanField(required=False)
    demonstrator = forms.BooleanField(required=False)
    spare_ticket_machine = forms.BooleanField(
        required=False,
        help_text="Use this if the code is for a spare ticket machine rather than a bus.",
    )
    features = forms.ModelMultipleChoiceField(
        queryset=VehicleFeature.objects.filter(category=VehicleFeature.Category.FEATURE),
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    accessibility_features = forms.ModelMultipleChoiceField(
        queryset=VehicleFeature.objects.filter(
            category=VehicleFeature.Category.ACCESSIBILITY
        ),
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    notes = forms.CharField(required=False, max_length=255)
    summary = SummaryField(
        max_length=255,
        help_text="Explain how you know this vehicle belongs in the fleet.",
    )

    @classmethod
    def _normalize_bound_data(cls, data):
        return EditVehicleForm._normalize_bound_data(data)

    def __init__(self, data=None, *args, operator, **kwargs):
        super().__init__(self._normalize_bound_data(data), *args, **kwargs)
        self.operator = operator
        if operator:
            self.fields["operator"].initial = operator
            del self.fields["operator"]
        self.add_operator_vehicle_column_fields(operator)
        if self.operator_vehicle_column_fields:
            ordered_fields = [name for name in self.field_order if name in self.fields]
            custom_field_names = list(self.operator_vehicle_column_fields)
            if "summary" in ordered_fields:
                ordered_fields.remove("summary")
                ordered_fields.extend(custom_field_names)
                ordered_fields.append("summary")
            else:
                ordered_fields.extend(custom_field_names)
            self.order_fields(ordered_fields)

    def get_operator(self):
        return self.operator or self.cleaned_data["operator"]

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        if Vehicle.objects.filter(
            operator=self.get_operator(),
            code__iexact=code,
            preserved=False,
            historical_fleet__isnull=True,
        ).exists():
            raise ValidationError(
                f"{self.operator} already has a vehicle with the code {code}"
            )
        return code

    def clean_reg(self):
        reg = self.cleaned_data["reg"].replace(".", "")
        if self.cleaned_data.get("spare_ticket_machine") and reg:
            raise ValidationError(
                "A spare ticket machine can\u2019t have a number plate"
            )
        return reg


class VehicleReviewForm(forms.ModelForm):
    rating = forms.DecimalField(
        min_value=Decimal("0.5"),
        max_value=Decimal("5.0"),
        decimal_places=1,
        max_digits=2,
        widget=forms.HiddenInput(),
    )

    class Meta:
        model = VehicleReview
        fields = ["rating", "message"]
        widgets = {
            "message": forms.Textarea(attrs={"rows": 4}),
        }

    def clean_rating(self):
        rating = self.cleaned_data["rating"]
        if (rating * 2) % 1 != 0:
            raise ValidationError("Choose a rating in 0.5 star steps.")
        return rating


class VehicleReviewReportForm(forms.Form):
    reason = forms.CharField(
        required=False,
        max_length=1000,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "Optional: tell us why this review should be checked.",
            }
        ),
    )


class LiveryInlineForm(forms.ModelForm):
    class Meta:
        model = Livery
        fields = [
            "name",
            "livery_type",
            "svg",
            "published",
            "show_name",
            "colour",
            "colours",
            "horizontal",
            "joined_fleet",
            "left_fleet",
        ]


class NewServiceRequestForm(forms.Form):
    operator = forms.ModelChoiceField(
        queryset=Operator.objects.order_by("name"),
        required=True,
    )
    line_name = forms.CharField(max_length=64, label="Route number or line name")
    description = forms.CharField(required=False, max_length=255)
    service_code = forms.CharField(required=False, max_length=64)
    summary = SummaryField(
        max_length=255,
        help_text="Explain what should be added and how you know it exists.",
    )


class NewOperatorRequestForm(forms.Form):
    noc = forms.CharField(label="Operator code (NOC)", max_length=10)
    name = forms.CharField(max_length=100, label="Operator name")
    summary = SummaryField(
        max_length=255,
        help_text="Explain what should be added and provide any useful evidence.",
    )

    def clean_noc(self):
        noc = self.cleaned_data["noc"].strip().upper()
        if Operator.objects.filter(pk=noc).exists():
            raise ValidationError(f"{noc} already exists")
        return noc


class NewVehicleModelRequestForm(forms.Form):
    name = forms.CharField(max_length=255, label="Vehicle model")
    manufacturer = forms.ModelChoiceField(
        queryset=Manufacturer.objects.order_by("name"),
        required=False,
        empty_label="Unknown / not listed",
    )
    summary = SummaryField(
        max_length=255,
        help_text="Explain the model that should be added and any supporting details.",
    )




class SornVehicleFilterForm(forms.Form):
    q = forms.CharField(
        label="Search",
        required=False,
        widget=forms.TextInput(
            attrs={"placeholder": "Fleet number, reg, code, name..."}
        ),
    )
    operator = forms.CharField(
        label="Operator",
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "NOC, slug or name"}),
    )
    vehicle = forms.IntegerField(
        label="Vehicle ID",
        required=False,
        widget=forms.NumberInput(attrs={"placeholder": "e.g. 28287"}),
    )
    vehicle_type = forms.ModelChoiceField(
        label="Vehicle type",
        queryset=VehicleType.objects.order_by("name"),
        required=False,
        empty_label="Any type",
    )
    include_preserved = forms.BooleanField(label="Include preserved", required=False)
    include_withdrawn = forms.BooleanField(label="Include withdrawn", required=False)
    include_vor = forms.BooleanField(label="Include VOR", required=False)
    trainer_only = forms.BooleanField(label="Trainer only", required=False)
    fleet_support_only = forms.BooleanField(
        label="Fleet support only", required=False
    )
    awaiting_delivery_only = forms.BooleanField(
        label="Awaiting delivery only", required=False
    )
    demonstrator_only = forms.BooleanField(label="Demonstrator only", required=False)
