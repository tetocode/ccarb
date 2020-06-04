from django import template

register = template.Library()


@register.filter(name='lookup')
def lookup(value: dict, k, default=""):
    if k in value:
        return value[k]
    else:
        return default
