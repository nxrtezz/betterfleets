"""TOC code -> Operator resolution."""

import logging

from busstops.models import DataSource, Operator, OperatorCode

logger = logging.getLogger(__name__)

# Darwin TOC names that don't map cleanly onto an Operator.name
NAME_OVERRIDES = {
    "LNR & WMR": None,  # two operators share this TOC - ambiguous
    "Lumo Stirling": None,  # Lumo sub-brand
    "Network Rail": None,
    "Private Charter": None,
    "Bus Station": None,
    "Ferry Terminal": None,
    "Unknown": None,
}


def get_operator(toc: str | None, toc_name: str | None, source: DataSource,
                 cache: dict) -> Operator | None:
    if not toc:
        return None
    if toc in cache:
        return cache[toc]

    operator = None

    # explicit OperatorCode mapping wins
    if code := OperatorCode.objects.filter(
        source=source, code__iexact=toc
    ).select_related("operator").first():
        operator = code.operator

    # most TOC codes are the same as the operator's NOC
    if operator is None:
        operator = (
            Operator.objects.filter(noc__iexact=toc, vehicle_mode="rail").first()
        )

    if operator is None and toc_name and toc_name not in NAME_OVERRIDES:
        operator = (
            Operator.objects.filter(name__iexact=toc_name, vehicle_mode="rail")
            .exclude(name__icontains="charter")
            .first()
        )

    cache[toc] = operator
    return operator


def get_toc_name(toc: str | None, reference: dict | None) -> str | None:
    if not toc or not reference:
        return None
    return reference.get("tocs", {}).get(toc)
