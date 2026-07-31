import xml.etree.ElementTree as ET

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic.detail import DetailView

from busstops.models import Service

from .forms import FaresForm, NetexPreviewForm
from .importing import import_netex_file_object
from .models import DataSet, FareRule, FareTable, Tariff, Ticket
from .netex_preview import parse_netex_preview


def format_price(amount):
    text = f"{amount:.2f}"
    if text.endswith(".00"):
        text = text[:-3]
    elif text.endswith("0"):
        text = text[:-1]
    return f"\N{POUND SIGN}{text}"


def format_fixed_price(amount):
    return f"\N{POUND SIGN}{amount:.2f}"


def clean_ticket_name(name):
    return (
        (name or "")
        .removeprefix("Tariff for ")
        .removesuffix(" fares")
        .replace("_", " ")
        .strip()
    )


def get_tariff_title(tariff):
    for table in tariff.faretable_set.all():
        product = table.preassigned_fare_product
        if product and product.name:
            return clean_ticket_name(product.name)
    return clean_ticket_name(tariff.name)


def get_tariff_description(tariff):
    for table in tariff.faretable_set.all():
        if table.description:
            return table.description
        user_profile = table.user_profile
        if user_profile and user_profile.description:
            return user_profile.description
    return ""


def get_tariff_price_rows(tariff):
    rows = []
    seen = set()
    for price in tariff.price_set.all():
        label_parts = []
        if price.sales_offer_package and price.sales_offer_package.name:
            label_parts.append(price.sales_offer_package.name)
        if price.time_interval and price.time_interval.name:
            label_parts.append(price.time_interval.name)
        label = " - ".join(label_parts) or "Price"
        key = (label, price.amount)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"label": label, "amount": format_price(price.amount)})
    return rows


def get_tariff_products(tariff):
    products = []
    seen = set()
    for table in tariff.faretable_set.all():
        label = ""
        if table.preassigned_fare_product and table.preassigned_fare_product.name:
            label = clean_ticket_name(table.preassigned_fare_product.name)
        elif table.user_profile and table.sales_offer_package:
            label = f"{table.user_profile} - {table.sales_offer_package}"
        elif table.sales_offer_package:
            label = str(table.sales_offer_package)
        elif table.user_profile:
            label = str(table.user_profile)
        if label and label not in seen:
            seen.add(label)
            products.append(label)
    return products


def get_tariff_services(tariff):
    services = list(tariff.services.all())
    return sorted(
        services,
        key=lambda service: (service.line_name or "", service.description or ""),
    )


def get_ticket_services(ticket):
    return ticket.get_accepted_services()


def index(request):
    datasets = DataSet.objects.order_by("-datetime")

    return render(
        request,
        "fares_index.html",
        {
            "datasets": datasets,
        },
    )


class DataSetDetailView(DetailView):
    model = DataSet

    def get_context_data(self, *args, **kwargs):
        context_data = super().get_context_data(*args, **kwargs)
        context_data["breadcrumb"] = self.object.operators.all()

        if self.request.GET:
            form = FaresForm(self.object.tariff_set.all(), self.request.GET)
            if form.is_valid():
                context_data["results"] = form.get_results()
        else:
            form = FaresForm(self.object.tariff_set.all())

        context_data["form"] = form
        return context_data


class TariffDetailView(DetailView):
    model = Tariff
    queryset = model.objects.prefetch_related(
        "operators",
        "services",
        "faretable_set__row_set__cell_set__price",
        "faretable_set__column_set",
        "faretable_set__preassigned_fare_product",
        "faretable_set__user_profile",
        "faretable_set__sales_offer_package",
        "price_set__time_interval",
        "price_set__sales_offer_package",
    )

    def get_context_data(self, *args, **kwargs):
        context_data = super().get_context_data(*args, **kwargs)
        context_data["breadcrumb"] = list(self.object.operators.all()) or [
            self.object.source
        ]

        if self.request.GET:
            form = FaresForm([self.object], self.request.GET)
            if form.is_valid():
                context_data["results"] = form.get_results()
        else:
            form = FaresForm([self.object])

        context_data["form"] = form
        context_data["ticket_title"] = get_tariff_title(self.object)
        context_data["ticket_description"] = get_tariff_description(self.object)
        context_data["price_rows"] = get_tariff_price_rows(self.object)
        context_data["product_rows"] = get_tariff_products(self.object)
        context_data["linked_services"] = get_tariff_services(self.object)

        return context_data


class TicketDetailView(DetailView):
    model = Ticket
    queryset = model.objects.select_related("operator").prefetch_related(
        "ticketacceptance_set__service"
    )

    def get_context_data(self, *args, **kwargs):
        context_data = super().get_context_data(*args, **kwargs)
        context_data["breadcrumb"] = [self.object.operator]
        if self.object.ticket_type:
            tickets = list(
                Ticket.objects.filter(
                    operator=self.object.operator,
                    ticket_type=self.object.ticket_type,
                )
                .prefetch_related("ticketacceptance_set__service")
                .order_by("name", "id")
            )
            title = self.object.ticket_type
        else:
            tickets = [self.object]
            title = self.object.name

        service_map = {}
        for ticket in tickets:
            ticket.accepted_services = ticket.get_accepted_services()
            ticket.adult_price_display = (
                format_fixed_price(ticket.adult_price)
                if ticket.adult_price is not None
                else None
            )
            ticket.child_price_display = (
                format_fixed_price(ticket.child_price)
                if ticket.child_price is not None
                else None
            )
            for service in ticket.accepted_services:
                service_map[service.id] = service

        context_data["ticket_title"] = title
        context_data["tickets"] = tickets
        context_data["linked_services"] = sorted(
            service_map.values(),
            key=lambda service: (
                service.line_name or "",
                service.description or "",
                service.pk,
            ),
        )
        return context_data


class FareTableDetailView(DetailView):
    model = FareTable
    queryset = model.objects.prefetch_related(
        "row_set__cell_set__price",
        "column_set",
    )


def service_fares(request, slug):
    service = get_object_or_404(Service, slug=slug)

    fare_rules = FareRule.objects.filter(service=service).select_related(
        "fare", "origin", "destination"
    )

    tariffs = Tariff.objects.filter(services=service).order_by("name", "valid_between")

    tariffs = tariffs.prefetch_related(
        "faretable_set__row_set__cell_set__price",
        "faretable_set__column_set",
        "faretable_set__user_profile",
        "faretable_set__sales_offer_package",
        "faretable_set__preassigned_fare_product",
    )

    if not (fare_rules or tariffs):
        raise Http404

    return render(
        request,
        "service_fares.html",
        {
            "breadcrumb": [service],
            "service": service,
            "fare_rules": fare_rules,
            "tariffs": tariffs,
        },
    )


def netex_preview(request):
    preview = None
    import_result = None
    form = NetexPreviewForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        try:
            uploaded_file = form.cleaned_data["file"]
            preview = parse_netex_preview(uploaded_file)
            if request.POST.get("action") == "import":
                if not request.user.is_authenticated:
                    return redirect(f"/accounts/login/?next={request.path}")
                if not request.user.is_staff:
                    raise PermissionDenied
                dataset, _ = import_netex_file_object(uploaded_file)
                return redirect(dataset.get_absolute_url())
        except ET.ParseError:
            form.add_error("file", "This file could not be read as NeTEx XML.")

    return render(
        request,
        "fares/preview.html",
        {
            "form": form,
            "preview": preview,
            "import_result": import_result,
        },
    )
