from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal, InvalidOperation
from typing import BinaryIO
import xml.etree.ElementTree as ET


NETEX_NAMESPACE = {"n": "http://www.netex.org.uk/netex"}


def parse_netex_preview(uploaded_file: BinaryIO) -> dict:
    uploaded_file.seek(0)
    root = ET.parse(uploaded_file).getroot()

    operators = {
        operator.attrib.get("id"): {
            "id": operator.attrib.get("id", ""),
            "name": _findtext(operator, "Name"),
            "trading_name": _findtext(operator, "TradingName"),
            "code": _findtext(operator, "PublicCode"),
        }
        for operator in root.findall(".//n:Operator", NETEX_NAMESPACE)
    }
    lines = {
        line.attrib.get("id"): {
            "id": line.attrib.get("id", ""),
            "name": _findtext(line, "Name"),
            "public_code": _findtext(line, "PublicCode"),
        }
        for line in root.findall(".//n:Line", NETEX_NAMESPACE)
    }
    sales_packages = {
        package.attrib.get("id"): {
            "id": package.attrib.get("id", ""),
            "name": _findtext(package, "Name"),
            "channels": _texts(package, ".//n:DistributionChannelType"),
            "payment_methods": _payment_methods(package),
        }
        for package in root.findall(".//n:SalesOfferPackage", NETEX_NAMESPACE)
    }
    fare_products = {
        product.attrib.get("id"): {
            "id": product.attrib.get("id", ""),
            "name": _findtext(product, "Name"),
            "description": _findtext(product, "Description"),
            "charging_moment": _findtext(product, "ChargingMomentType"),
        }
        for product in root.findall(".//n:PreassignedFareProduct", NETEX_NAMESPACE)
    }
    user_profiles = {
        profile.attrib.get("id"): {
            "id": profile.attrib.get("id", ""),
            "name": _findtext(profile, "Name"),
            "min_age": _findtext(profile, "MinimumAge"),
            "max_age": _findtext(profile, "MaximumAge"),
        }
        for profile in root.findall(".//n:UserProfile", NETEX_NAMESPACE)
    }
    fare_zones = {
        zone.attrib.get("id"): {
            "id": zone.attrib.get("id", ""),
            "name": _findtext(zone, "Name"),
            "members": _texts(zone, "./n:members/*"),
        }
        for zone in root.findall(".//n:FareZone", NETEX_NAMESPACE)
    }
    distance_matrix_elements = {
        element.attrib.get("id"): {
            "id": element.attrib.get("id", ""),
            "name": _findtext(element, "Name"),
            "start_zone_ref": _attrib(element, "StartTariffZoneRef", "ref"),
            "end_zone_ref": _attrib(element, "EndTariffZoneRef", "ref"),
        }
        for element in root.findall(".//n:DistanceMatrixElement", NETEX_NAMESPACE)
    }

    tariffs = []
    for tariff in root.findall(".//n:Tariff", NETEX_NAMESPACE):
        operator_ref = _attrib(tariff, "OperatorRef", "ref")
        line_ref = _attrib(tariff, "LineRef", "ref")
        tariffs.append(
            {
                "id": tariff.attrib.get("id", ""),
                "name": _findtext(tariff, "Name"),
                "type": _ref_name(_attrib(tariff, "TypeOfTariffRef", "ref")),
                "basis": _findtext(tariff, "TariffBasis"),
                "operator": operators.get(operator_ref),
                "line": lines.get(line_ref),
                "valid_from": _findtext(
                    tariff, "./n:validityConditions/n:ValidBetween/n:FromDate"
                ),
                "valid_to": _findtext(
                    tariff, "./n:validityConditions/n:ValidBetween/n:ToDate"
                ),
                "time_intervals": [
                    {
                        "name": _findtext(interval, "Name"),
                        "duration": _findtext(interval, "Duration"),
                        "end_time": _findtext(interval, "EndTime"),
                        "day_offset": _findtext(interval, "DayOffset"),
                    }
                    for interval in tariff.findall(
                        "./n:timeIntervals/n:TimeInterval", NETEX_NAMESPACE
                    )
                ],
            }
        )

    preview_tables = [
        _build_preview_table(
            fare_table,
            fare_products,
            sales_packages,
            user_profiles,
            lines,
            fare_zones,
            distance_matrix_elements,
        )
        for fare_table in root.findall(".//n:FareTable", NETEX_NAMESPACE)
    ]

    included_lines = list(
        OrderedDict(
            (line["id"], line)
            for line in lines.values()
            if line["name"] or line["public_code"]
        ).values()
    )

    return {
        "filename": getattr(uploaded_file, "name", ""),
        "publication_timestamp": _findtext(root, "PublicationTimestamp"),
        "participant_ref": _findtext(root, "ParticipantRef"),
        "description": _findtext(root, "Description"),
        "frame_name": _findtext(root, ".//n:CompositeFrame/n:Name"),
        "frame_description": _findtext(root, ".//n:CompositeFrame/n:Description"),
        "operators": list(operators.values()),
        "fare_products": list(fare_products.values()),
        "sales_packages": list(sales_packages.values()),
        "user_profiles": list(user_profiles.values()),
        "tariffs": tariffs,
        "preview_tables": preview_tables,
        "included_lines": included_lines,
        "fare_zones": list(fare_zones.values()),
    }


def _build_preview_table(
    fare_table,
    fare_products,
    sales_packages,
    user_profiles,
    lines,
    fare_zones,
    distance_matrix_elements,
):
    refs = fare_table.find("n:pricesFor", NETEX_NAMESPACE)
    product_ref = (
        _attrib(refs, "PreassignedFareProductRef", "ref") if refs is not None else ""
    )
    user_profile_ref = _attrib(refs, "UserProfileRef", "ref") if refs is not None else ""
    sales_refs = [
        element.attrib.get("ref", "")
        for element in fare_table.findall(
            "./n:pricesFor/n:SalesOfferPackageRef", NETEX_NAMESPACE
        )
    ]
    line_ref = _attrib(fare_table, "./n:specifics/n:LineRef", "ref")

    flat_prices = []
    row_order = []
    column_order = []
    matrix = {}

    for price in fare_table.findall("./n:prices/*", NETEX_NAMESPACE):
        amount = _findtext(price, "Amount")
        display_amount = _currency(amount)
        distance_ref = _attrib(price, "DistanceMatrixElementRef", "ref")
        if not distance_ref:
            flat_prices.append(
                {
                    "amount": amount,
                    "display_amount": display_amount,
                }
            )
            continue

        element = distance_matrix_elements.get(distance_ref, {})
        start_zone = fare_zones.get(element.get("start_zone_ref", ""), {})
        end_zone = fare_zones.get(element.get("end_zone_ref", ""), {})
        start_name = start_zone.get("name") or element.get("start_zone_ref", "")
        end_name = end_zone.get("name") or element.get("end_zone_ref", "")

        matrix[(start_name, end_name)] = display_amount
        if start_name and start_name not in row_order:
            row_order.append(start_name)
        if end_name and end_name not in column_order:
            column_order.append(end_name)

    return {
        "id": fare_table.attrib.get("id", ""),
        "name": _findtext(fare_table, "Name"),
        "product": fare_products.get(product_ref),
        "sales_packages": [
            sales_packages[ref] for ref in sales_refs if ref in sales_packages
        ],
        "user_profile": user_profiles.get(user_profile_ref),
        "line": lines.get(line_ref),
        "flat_prices": flat_prices,
        "matrix_rows": [
            {
                "name": row_name,
                "cells": [
                    matrix.get((row_name, column_name), "") for column_name in column_order
                ],
            }
            for row_name in row_order
        ],
        "matrix_columns": column_order,
    }


def _attrib(element, tag, attribute):
    if element is None:
        return ""
    child = element.find(tag if tag.startswith(".") else f"n:{tag}", NETEX_NAMESPACE)
    if child is None:
        return ""
    return child.attrib.get(attribute, "")


def _findtext(element, path, default=""):
    if element is None:
        return default
    if path.startswith(".") or "/" in path:
        return (element.findtext(path, default, NETEX_NAMESPACE) or default).strip()
    return (element.findtext(f"n:{path}", default, NETEX_NAMESPACE) or default).strip()


def _texts(element, path):
    return [
        item.text.strip()
        for item in element.findall(path, NETEX_NAMESPACE)
        if item.text and item.text.strip()
    ]


def _payment_methods(element):
    methods = []
    for node in element.findall(".//n:PaymentMethods", NETEX_NAMESPACE):
        methods.extend(part for part in node.text.split() if part)
    return methods


def _ref_name(value):
    if not value:
        return ""
    return value.rsplit(":", 1)[-1].replace("_", " ")


def _currency(amount):
    if amount == "":
        return ""
    try:
        value = Decimal(amount)
    except InvalidOperation:
        return amount
    if value == value.quantize(Decimal("1")):
        return f"£{int(value)}"
    return f"£{value.normalize()}"
