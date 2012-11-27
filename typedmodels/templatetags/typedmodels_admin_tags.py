from django import template

register = template.Library()
@register.inclusion_tag("typedmodels/admin/_links_for_model_with_children.html")
def links_for_model_with_children(model):
    # See https://code.djangoproject.com/ticket/3544 for the reason why template recursion is not used here.
    return {'model': model}

@register.filter
def typedmodel_ancestors(model):
    parent = model.parent_typedmodel()
    if parent:
        return typedmodel_ancestors(parent) + [parent]
    else:
        return []
            
