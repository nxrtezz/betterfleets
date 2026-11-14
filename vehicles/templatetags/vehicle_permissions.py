from django import template
from vehicles.permissions import can_review_revision

register = template.Library()
register.simple_tag(can_review_revision)
