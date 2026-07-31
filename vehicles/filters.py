from django.db.models import Q
from django.forms.widgets import NumberInput, Select, TextInput
from django_filters import CharFilter, ChoiceFilter, FilterSet, NumberFilter


ENTRY_TYPE_CHOICES = [
    ("all", "Everything"),
    ("edits", "Edits only"),
    ("requests", "Requests only"),
    ("vehicle_request", "Vehicle requests"),
    ("service_request", "Service requests"),
    ("operator_request", "Operator requests"),
    ("vehicle_type_request", "Vehicle model requests"),
    ("livery_request", "Livery requests"),
]


class VehicleRevisionFilter(FilterSet):
    show = ChoiceFilter(
        label="Show",
        choices=ENTRY_TYPE_CHOICES,
        required=True,
        empty_label=None,
        method="show_filter",
        widget=Select,
    )
    q = CharFilter(
        label="Search",
        method="search_filter",
        widget=TextInput(attrs={"placeholder": "Vehicle, reg, route, summary..."}),
    )
    operator = CharFilter(
        label="Operator",
        method="operator_filter",
        widget=TextInput(attrs={"placeholder": "NOC, slug or name"}),
    )
    vehicle = NumberFilter(
        label="Vehicle ID",
        method="vehicle_filter",
        widget=NumberInput(attrs={"placeholder": "e.g. 28287"}),
    )
    user = NumberFilter(
        label="User ID",
        method="user_filter",
        widget=NumberInput(attrs={"placeholder": "e.g. 4"}),
    )
    status = ChoiceFilter(
        label="Status",
        choices=[
            ("pending", "pending"),
            ("approved", "approved"),
            ("disapproved", "disapproved"),
        ],
        method="status_filter",
        required=True,
        empty_label=None,
        widget=Select,
    )

    def operator_filter(self, queryset, _, value):
        value = (value or "").strip()
        if not value:
            return queryset
        return queryset.filter(
            Q(vehicle__operator__pk__iexact=value)
            | Q(vehicle__operator__slug__iexact=value)
            | Q(vehicle__operator__name__icontains=value)
            | Q(from_operator__pk__iexact=value)
            | Q(from_operator__slug__iexact=value)
            | Q(from_operator__name__icontains=value)
            | Q(to_operator__pk__iexact=value)
            | Q(to_operator__slug__iexact=value)
            | Q(to_operator__name__icontains=value)
        )

    def show_filter(self, queryset, _, value):
        return queryset

    def vehicle_filter(self, queryset, _, value):
        if value in ("", None):
            return queryset
        return queryset.filter(vehicle_id=value)

    def user_filter(self, queryset, _, value):
        if value in ("", None):
            return queryset
        return queryset.filter(user_id=value)

    def search_filter(self, queryset, _, value):
        value = (value or "").strip()
        if not value:
            return queryset
        return queryset.filter(
            Q(vehicle__code__icontains=value)
            | Q(vehicle__reg__icontains=value)
            | Q(vehicle__fleet_code__icontains=value)
            | Q(vehicle__fleet_number__icontains=value)
            | Q(vehicle__operator__name__icontains=value)
            | Q(vehicle__operator__pk__icontains=value)
            | Q(vehicle__vehicle_type__name__icontains=value)
            | Q(summary__icontains=value)
            | Q(notes__icontains=value)
        )

    def status_filter(self, queryset, _, value):
        match value:
            case "pending":
                return queryset.filter(pending=True, disapproved=False)
            case "disapproved":
                return queryset.filter(pending=False, disapproved=True)
            case "approved":
                return queryset.filter(pending=False, disapproved=False)
        return queryset
