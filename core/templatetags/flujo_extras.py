import re
from django import template

register = template.Library()


@register.filter
def digits(value):
    """Strip everything except digits — for wa.me links."""
    return re.sub(r"\D", "", str(value or ""))
