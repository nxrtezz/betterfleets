from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Q

from bustimes.models import Garage
from busstops.models import Operator


@dataclass(slots=True)
class MatchPreview:
    action: str
    label: str
    object_id: str = ""

    @property
    def is_match(self) -> bool:
        return self.action == "match"


def match_operator(operator_code: str) -> MatchPreview:
    code = (operator_code or "").strip()
    if not code:
        return MatchPreview("create", "Create operator from import")

    operator = (
        Operator.objects.filter(
            Q(noc__iexact=code)
            | Q(slug__iexact=code)
            | Q(operatorcode__code__iexact=code)
        )
        .distinct()
        .first()
    )
    if operator:
        return MatchPreview(
            "match",
            f"Match {operator.noc} - {operator.name}",
            operator.noc,
        )
    return MatchPreview("create", f"Create operator {code}")


def match_operator_for_row(row) -> MatchPreview:
    return match_operator(getattr(row, "operator_code", ""))


def match_garage(garage_name: str, operator_code: str) -> MatchPreview:
    cleaned_name = (garage_name or "").strip()
    if not cleaned_name:
        return MatchPreview("create", "No depot supplied")

    operator_preview = match_operator(operator_code)
    if operator_preview.is_match:
        garages = Garage.objects.filter(operator_id=operator_preview.object_id)
        garage = (
            garages.filter(
                Q(name__iexact=cleaned_name)
                | Q(code__iexact=cleaned_name)
                | Q(name__iexact=_trim_gsc_prefix(cleaned_name))
                | Q(code__iexact=_trim_gsc_prefix(cleaned_name))
            )
            .distinct()
            .first()
        )
        if garage:
            descriptor = garage.name or garage.code or str(garage.pk)
            return MatchPreview(
                "match",
                f"Match depot {descriptor} for {garage.operator_id}",
                str(garage.pk),
            )
        return MatchPreview(
            "create",
            f"Create depot {cleaned_name} for {operator_preview.object_id}",
        )

    return MatchPreview(
        "create",
        f"Create depot {cleaned_name} after operator is resolved",
    )


def match_garage_for_row(row) -> MatchPreview:
    return match_garage(
        getattr(row, "garage", ""),
        getattr(row, "operator_code", ""),
    )


def _trim_gsc_prefix(value: str) -> str:
    if value.upper().startswith("GSC "):
        return value[4:].strip()
    return value
