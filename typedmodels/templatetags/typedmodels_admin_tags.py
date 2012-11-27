from django import template

register = template.Library()
@register.inclusion_tag("typedmodels/admin/_links_for_model_with_children.html", takes_context=True)
def links_for_model_with_children(context, model):
    # See https://code.djangoproject.com/ticket/3544 for the reason why template recursion is not used here.
    if "cl" in context:
        current_model = context["cl"].model
    else:
        current_model = context["current_model"]
    return {'model': model, 'current_model': current_model}

@register.filter
def typedmodel_ancestors(model):
    parent = model.parent_typedmodel()
    if parent:
        return typedmodel_ancestors(parent) + [parent]
    else:
        return []
            
