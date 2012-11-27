from django import template
from django.contrib.admin.templatetags.admin_urls import admin_urlname

register = template.Library()

@register.filter
def model_admin_urlname(value, arg):
    return admin_urlname(value._meta, arg)
