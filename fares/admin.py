from django.contrib import admin
from django import forms
from django.db.models import Value
from django.db.models.aggregates import StringAgg

from busstops.models import Service

from .models import (
    DataSet,
    DistanceMatrixElement,
    FareTable,
    FareZone,
    Price,
    Ticket,
    TicketAcceptance,
    Tariff,
    UserProfile,
)


@admin.register(DataSet)
class DataSetAdmin(admin.ModelAdmin):
    list_display = ["__str__", "description", "noc", "datetime"]
    list_filter = ["published"]
    autocomplete_fields = ["operators"]
    search_fields = ["name", "description"]

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if "changelist" in request.resolver_match.view_name:
            queryset = queryset.annotate(
                noc=StringAgg("operators", Value(", "), distinct=True)
            )
        return queryset

    def noc(self, obj):
        return obj.noc


@admin.register(Tariff)
class TariffAdmin(admin.ModelAdmin):
    autocomplete_fields = ["operators", "services"]
    list_filter = [("operators", admin.RelatedOnlyFieldListFilter)]
    raw_id_fields = ["source", "user_profile", "access_zones"]


class TicketAdminForm(forms.ModelForm):
    accepted_services = forms.ModelMultipleChoiceField(
        label="Accepted services",
        queryset=Service.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Tick the operator services this ticket is accepted on.",
    )

    class Meta:
        model = Ticket
        fields = [
            "operator",
            "ticket_type",
            "name",
            "description",
            "zone",
            "adult_price",
            "child_price",
            "days_valid_for",
            "accepted_services",
        ]

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        operator_id = None
        if self.request is not None:
            operator_id = self.request.GET.get("operator")
        if operator_id and not self.is_bound and not self.instance.pk:
            self.initial.setdefault("operator", operator_id)
        self.fields["operator"].widget.attrs["onchange"] = (
            "window.location.search = this.value ? '?operator=' + "
            "encodeURIComponent(this.value) : '';"
        )
        operator = self._get_operator()
        if operator:
            queryset = Service.objects.filter(operator=operator).distinct().order_by(
                "line_name", "description", "id"
            )
            self.fields["accepted_services"].queryset = queryset
            if self.instance.pk:
                self.initial["accepted_services"] = [
                    acceptance.service_id
                    for acceptance in self.instance.ticketacceptance_set.filter(
                        accepted=True
                    )
                ]

    def _get_operator(self):
        operator = self.instance.operator if self.instance.pk else None
        operator_id = self.data.get("operator") if self.is_bound else None
        if not operator_id and self.request is not None:
            operator_id = self.request.GET.get("operator")
        if operator_id:
            operator = self.fields["operator"].queryset.filter(pk=operator_id).first()
        return operator

    def save(self, commit=True):
        ticket = super().save(commit=commit)
        if commit:
            self._save_ticket_acceptances(ticket)
        else:
            self.save_m2m = lambda: self._save_ticket_acceptances(ticket)
        return ticket

    def _save_ticket_acceptances(self, ticket):
        operator = ticket.operator
        if not operator:
            return

        operator_services = list(
            Service.objects.filter(operator=operator).distinct().order_by("id")
        )
        selected_ids = {
            service.id for service in self.cleaned_data.get("accepted_services", [])
        }

        TicketAcceptance.objects.filter(ticket=ticket).exclude(
            service__in=operator_services
        ).delete()

        existing = {
            acceptance.service_id: acceptance
            for acceptance in TicketAcceptance.objects.filter(
                ticket=ticket, service__in=operator_services
            )
        }

        for service in operator_services:
            accepted = service.id in selected_ids
            acceptance = existing.get(service.id)
            if acceptance:
                if acceptance.accepted != accepted:
                    acceptance.accepted = accepted
                    acceptance.save(update_fields=["accepted"])
            else:
                TicketAcceptance.objects.create(
                    ticket=ticket, service=service, accepted=accepted
                )


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    form = TicketAdminForm
    list_display = ["ticket_type", "name", "operator", "zone", "adult_price", "child_price", "days_valid_for"]
    list_filter = [("operator", admin.RelatedOnlyFieldListFilter)]
    search_fields = ["name", "description", "operator__name", "operator__noc"]

    def get_form(self, request, obj=None, change=False, **kwargs):
        base_form = super().get_form(request, obj, change=change, **kwargs)

        class RequestAwareTicketAdminForm(base_form):
            def __init__(self, *args, **inner_kwargs):
                inner_kwargs["request"] = request
                super().__init__(*args, **inner_kwargs)

        return RequestAwareTicketAdminForm


@admin.register(Price)
class PriceAdmin(admin.ModelAdmin):
    raw_id_fields = ["time_interval", "user_profile", "sales_offer_package", "tariff"]
    list_display = ["amount"]


@admin.register(FareTable)
class FareTableAdmin(admin.ModelAdmin):
    list_display = ["__str__", "description"]
    list_filter = ["tariff__source"]
    raw_id_fields = ["user_profile", "sales_offer_package", "tariff"]


@admin.register(DistanceMatrixElement)
class DistanceMatrixElementAdmin(admin.ModelAdmin):
    raw_id_fields = ["price", "start_zone", "end_zone", "tariff"]


@admin.register(FareZone)
class FareZoneAdmin(admin.ModelAdmin):
    autocomplete_fields = ["stops"]


admin.site.register(UserProfile)
