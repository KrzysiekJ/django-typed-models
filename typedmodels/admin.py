from django.http import HttpResponseRedirect
from django.contrib import admin
from django.contrib.admin.util import unquote
from django.core.urlresolvers import reverse

class TypedModelAdmin(admin.ModelAdmin):
    change_list_template = 'typedmodels/admin/change_list.html'
    add_form_template = 'typedmodels/admin/change_form.html'
    change_form_template = 'typedmodels/admin/change_form.html'
    
    def change_view(self, request, object_id, *args, **kwargs):
        if self.model.children_typedmodels():
            obj = self.get_object(request, unquote(object_id))
            object_type = obj.type
            return HttpResponseRedirect(reverse('admin:{}_change'.format('_'.join(object_type.split('.'))), args=(object_id,)))
        else:
            return super(TypedModelAdmin, self).change_view(request, object_id, *args, **kwargs)

