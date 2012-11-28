from django import template

register = template.Library()

@register.filter
def meta(value, arg):
    return getattr(value._meta, arg, '')
