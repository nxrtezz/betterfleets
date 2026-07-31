"""
Statistics utilities for generating breakdowns and charts for various entities.
"""
from django.db.models import Count, Q
from django.db.models.functions import Cast
from django.db.models import FloatField
from vehicles.models import Vehicle, VehicleType, Livery
from bustimes.models import Garage


def get_operator_statistics(operator):
    """
    Generate statistics for an operator including vehicle types, liveries, and garage breakdowns.
    """
    vehicles = Vehicle.objects.filter(operator=operator).select_related(
        'vehicle_type', 'livery', 'garage'
    ).exclude(withdrawn=True, preserved=True)
    
    total_vehicles = vehicles.count()
    
    # Vehicle type breakdown
    vehicle_types = vehicles.values('vehicle_type__name').annotate(
        count=Count('id')
    ).order_by('-count')
    
    vehicle_type_stats = []
    for vt in vehicle_types:
        if vt['vehicle_type__name']:
            percentage = (vt['count'] / total_vehicles * 100) if total_vehicles > 0 else 0
            vehicle_type_stats.append({
                'name': vt['vehicle_type__name'],
                'count': vt['count'],
                'percentage': round(percentage, 1)
            })
    
    # Livery breakdown
    liveries = vehicles.values('livery__name', 'livery__id', 'livery__colour', 'livery__left_css').annotate(
        count=Count('id')
    ).order_by('-count')
    
    livery_stats = []
    for liv in liveries:
        if liv['livery__name']:
            percentage = (liv['count'] / total_vehicles * 100) if total_vehicles > 0 else 0
            livery_stats.append({
                'id': liv['livery__id'],
                'name': liv['livery__name'],
                'count': liv['count'],
                'percentage': round(percentage, 1),
                'colour': liv['livery__colour'],
                'css': liv['livery__left_css']
            })
    
    # Garage breakdown (only if 2+ garages)
    garage_stats = []
    garages = vehicles.values('garage__name').annotate(
        count=Count('id')
    ).order_by('-count')
    
    if garages.count() >= 2:
        for garage in garages:
            if garage['garage__name']:
                percentage = (garage['count'] / total_vehicles * 100) if total_vehicles > 0 else 0
                garage_stats.append({
                    'name': garage['garage__name'],
                    'count': garage['count'],
                    'percentage': round(percentage, 1)
                })
    
    return {
        'total_vehicles': total_vehicles,
        'vehicle_types': vehicle_type_stats,
        'liveries': livery_stats,
        'garages': garage_stats
    }


def get_organisation_statistics(organisation):
    """
    Generate statistics for an organisation (aggregates across all operators).
    """
    operators = organisation.operator_set.all()
    operator_ids = operators.values_list('id', flat=True)
    
    vehicles = Vehicle.objects.filter(operator_id__in=operator_ids).select_related(
        'vehicle_type', 'livery'
    ).exclude(withdrawn=True, preserved=True)
    
    total_vehicles = vehicles.count()
    
    # Vehicle type breakdown
    vehicle_types = vehicles.values('vehicle_type__name').annotate(
        count=Count('id')
    ).order_by('-count')
    
    vehicle_type_stats = []
    for vt in vehicle_types:
        if vt['vehicle_type__name']:
            percentage = (vt['count'] / total_vehicles * 100) if total_vehicles > 0 else 0
            vehicle_type_stats.append({
                'name': vt['vehicle_type__name'],
                'count': vt['count'],
                'percentage': round(percentage, 1)
            })
    
    # Livery breakdown
    liveries = vehicles.values('livery__name', 'livery__id', 'livery__colour', 'livery__left_css').annotate(
        count=Count('id')
    ).order_by('-count')
    
    livery_stats = []
    for liv in liveries:
        if liv['livery__name']:
            percentage = (liv['count'] / total_vehicles * 100) if total_vehicles > 0 else 0
            livery_stats.append({
                'id': liv['livery__id'],
                'name': liv['livery__name'],
                'count': liv['count'],
                'percentage': round(percentage, 1),
                'colour': liv['livery__colour'],
                'css': liv['livery__left_css']
            })
    
    return {
        'total_vehicles': total_vehicles,
        'total_operators': operators.count(),
        'vehicle_types': vehicle_type_stats,
        'liveries': livery_stats
    }


def get_government_authority_statistics(authority):
    """
    Generate statistics for a government authority.
    """
    operators = authority.operator_set.all()
    operator_ids = operators.values_list('id', flat=True)
    
    vehicles = Vehicle.objects.filter(operator_id__in=operator_ids).select_related(
        'vehicle_type', 'livery'
    ).exclude(withdrawn=True, preserved=True)
    
    total_vehicles = vehicles.count()
    
    # Vehicle type breakdown
    vehicle_types = vehicles.values('vehicle_type__name').annotate(
        count=Count('id')
    ).order_by('-count')
    
    vehicle_type_stats = []
    for vt in vehicle_types:
        if vt['vehicle_type__name']:
            percentage = (vt['count'] / total_vehicles * 100) if total_vehicles > 0 else 0
            vehicle_type_stats.append({
                'name': vt['vehicle_type__name'],
                'count': vt['count'],
                'percentage': round(percentage, 1)
            })
    
    # Livery breakdown
    liveries = vehicles.values('livery__name', 'livery__id', 'livery__colour', 'livery__left_css').annotate(
        count=Count('id')
    ).order_by('-count')
    
    livery_stats = []
    for liv in liveries:
        if liv['livery__name']:
            percentage = (liv['count'] / total_vehicles * 100) if total_vehicles > 0 else 0
            livery_stats.append({
                'id': liv['livery__id'],
                'name': liv['livery__name'],
                'count': liv['count'],
                'percentage': round(percentage, 1),
                'colour': liv['livery__colour'],
                'css': liv['livery__left_css']
            })
    
    return {
        'total_vehicles': total_vehicles,
        'total_operators': operators.count(),
        'vehicle_types': vehicle_type_stats,
        'liveries': livery_stats
    }


def get_manufacturer_statistics(manufacturer):
    """
    Generate statistics for a manufacturer (division).
    """
    vehicle_types = VehicleType.objects.filter(manufacturer=manufacturer)
    vehicle_type_ids = vehicle_types.values_list('id', flat=True)
    
    vehicles = Vehicle.objects.filter(vehicle_type_id__in=vehicle_type_ids).select_related(
        'vehicle_type', 'livery', 'operator'
    ).exclude(withdrawn=True, preserved=True)
    
    total_vehicles = vehicles.count()
    
    # Vehicle type breakdown
    vehicle_type_stats = []
    for vt in vehicle_types:
        count = vehicles.filter(vehicle_type=vt).count()
        if count > 0:
            percentage = (count / total_vehicles * 100) if total_vehicles > 0 else 0
            vehicle_type_stats.append({
                'name': vt.name,
                'count': count,
                'percentage': round(percentage, 1)
            })
    
    vehicle_type_stats.sort(key=lambda x: x['count'], reverse=True)
    
    # Livery breakdown
    liveries = vehicles.values('livery__name', 'livery__id', 'livery__colour', 'livery__left_css').annotate(
        count=Count('id')
    ).order_by('-count')
    
    livery_stats = []
    for liv in liveries:
        if liv['livery__name']:
            percentage = (liv['count'] / total_vehicles * 100) if total_vehicles > 0 else 0
            livery_stats.append({
                'id': liv['livery__id'],
                'name': liv['livery__name'],
                'count': liv['count'],
                'percentage': round(percentage, 1),
                'colour': liv['livery__colour'],
                'css': liv['livery__left_css']
            })
    
    # Operator breakdown
    operators = vehicles.values('operator__name', 'operator__slug').annotate(
        count=Count('id')
    ).order_by('-count')
    
    operator_stats = []
    for op in operators:
        if op['operator__name']:
            percentage = (op['count'] / total_vehicles * 100) if total_vehicles > 0 else 0
            operator_stats.append({
                'name': op['operator__name'],
                'slug': op['operator__slug'],
                'count': op['count'],
                'percentage': round(percentage, 1)
            })
    
    return {
        'total_vehicles': total_vehicles,
        'total_vehicle_types': vehicle_types.count(),
        'vehicle_types': vehicle_type_stats,
        'liveries': livery_stats,
        'operators': operator_stats
    }
