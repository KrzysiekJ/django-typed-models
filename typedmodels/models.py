import types

from django.db import models
from django.db.models.base import ModelBase
from django.db.models.fields import Field

class TypedModelManager(models.Manager):
    def get_query_set(self):
        qs = super(TypedModelManager, self).get_query_set()
        if hasattr(self.model, '_typedmodels_type'):
            if len(self.model._typedmodels_subtypes) > 1:
                qs = qs.filter(type__in=self.model._typedmodels_subtypes)
            else:
                qs = qs.filter(type=self.model._typedmodels_type)
        return qs


class TypedModelMetaclass(ModelBase):
    """
    This metaclass enables a model for auto-downcasting using a ``type`` attribute.
    """
    def __new__(meta, classname, bases, classdict):
        try:
            TypedModel
        except NameError:
            # don't do anything for TypedModel class itself
            #
            # ...except updating Meta class to instantiate fields_from_subclasses attribute
            typed_model = super(TypedModelMetaclass, meta).__new__(meta, classname, bases, classdict)
            # We have to set this attribute after _meta has been created, otherwise an
            # exception would be thrown by Options class constructor.
            typed_model._meta.fields_from_subclasses = {}
            return typed_model

        # look for a non-proxy base class that is a subclass of TypedModel
        mro = list(bases)
        while mro:
            base_class = mro.pop(-1)
            if issubclass(base_class, TypedModel) and base_class is not TypedModel:
                if base_class._meta.proxy:
                    # continue up the mro looking for non-proxy base classes
                    mro.extend(base_class.__bases__)
                else:
                    break
        else:
            base_class = None

        if base_class:
            if not hasattr(base_class, 'original'):
                class original_meta:
                    proxy = True
                Original = super(TypedModelMetaclass, meta).__new__(meta, base_class.__name__+'Original', (base_class,), {'Meta': original_meta, '__module__': base_class.__module__})
                base_class._meta.original = Original
            
            # Enforce that subclasses are proxy models.
            # Update an existing metaclass, or define an empty one
            # then set proxy=True
            class Meta:
                pass
            Meta = classdict.get('Meta', Meta)
            if getattr(Meta, 'proxy', False):
                # If user has specified proxy=True explicitly, we assume that he wants it to be treated like ordinary
                # proxy class, without TypedModel logic.
                return super(TypedModelMetaclass, meta).__new__(meta, classname, bases, classdict)
            Meta.proxy = True

            declared_fields = dict((name, element) for name, element in classdict.items() if isinstance(element, Field))

            for field_name, field in declared_fields.items():
                field.null = True
                if isinstance(field, models.fields.related.RelatedField):
                    # Monkey patching field instance to make do_related_class use created class instead of base_class.
                    # Actually that class doesn't exist yet, so we just monkey patch base_class for a while,
                    # changing _meta.object_name, so accessor names are generated properly.
                    # We'll do more stuff when the class is created.
                    old_do_related_class = field.do_related_class
                    def do_related_class(self, other, cls):
                        base_class_name = base_class.__name__
                        cls._meta.object_name = classname
                        old_do_related_class(other, cls)
                        cls._meta.object_name = base_class_name
                    field.do_related_class = types.MethodType(do_related_class, field, field.__class__)
                if isinstance(field, models.fields.related.RelatedField) and isinstance(field.rel.to, TypedModel) and field.rel.to.base_class:
                    field.rel.limit_choices_to['type__in'] = field.rel.to._typedmodels_subtypes
                    field.rel.to = field.rel.to.base_class
                field.contribute_to_class(base_class, field_name)
                classdict.pop(field_name)
            base_class._meta.fields_from_subclasses.update(declared_fields)

            # set app_label to the same as the base class, unless explicitly defined otherwise
            if not hasattr(Meta, 'app_label'):
                if hasattr(getattr(base_class, '_meta', None), 'app_label'):
                    Meta.app_label = base_class._meta.app_label

            classdict.update({
                'Meta': Meta,
            })

        classdict['base_class'] = base_class

        cls = super(TypedModelMetaclass, meta).__new__(meta, classname, bases, classdict)

        cls._meta.fields_from_subclasses = {}

        if base_class:
            opts = cls._meta
            typ = "%s.%s" % (opts.app_label, opts.object_name.lower())
            cls._typedmodels_type = typ
            cls._typedmodels_subtypes = [typ]
            if typ in base_class._typedmodels_registry:
                raise ValueError("Can't register %s type %r to %r (already registered to %r )" % (typ, classname, base_class._typedmodels_registry))
            base_class._typedmodels_registry[typ] = cls

            parent_class = filter(lambda class_: issubclass(class_, TypedModel), bases)[0]
            if parent_class in base_class._typedmodels_children_registry:
                base_class._typedmodels_children_registry[parent_class].append(cls)
            base_class._typedmodels_children_registry[cls] = []
            
            type_name = getattr(cls._meta, 'verbose_name', cls.__name__)
            type_field = base_class._meta.get_field('type')
            type_field._choices = tuple(list(type_field.choices) + [(typ, type_name)])

            cls._meta.declared_fields = declared_fields

            # Update related fields in base_class so they refer to cls.
            for field_name, related_field in filter(lambda (field_name, field): isinstance(field, models.fields.related.RelatedField), declared_fields.items()):
                # Unfortunately RelatedObject is recreated in ./manage.py validate, so false positives for name clashes
                # may be reported until #19399 is fixed - see https://code.djangoproject.com/ticket/19399
                related_field.related.opts = cls._meta

            # look for any other proxy superclasses, they'll need to know
            # about this subclass
            for superclass in cls.mro():
                if (issubclass(superclass, base_class)
                        and superclass not in (cls, base_class)
                        and hasattr(superclass, '_typedmodels_type')):
                    superclass._typedmodels_subtypes.append(typ)

            # Overriding _fill_fields_cache function in Meta.
            # This is done by overriding method for specific instance of
            # django.db.models.options.Options class, which generally should
            # be avoided, but in this case it may be better than monkey patching
            # Options or copy-pasting large parts of Django code.
            def _fill_fields_cache(self):
                cache = []
                for parent in self.parents:
                    for field, model in parent._meta.get_fields_with_model():
                        if field in base_class._meta.original._meta.fields or any(field in ancestor._meta.declared_fields.values() for ancestor in cls.mro() if issubclass(ancestor, base_class) and not ancestor==base_class):
                            if model:
                                cache.append((field, model))
                            else:
                                cache.append((field, parent))
                self._field_cache = tuple(cache)
                self._field_name_cache = [x for x, _ in cache]
            cls._meta._fill_fields_cache = types.MethodType(_fill_fields_cache, cls._meta, cls._meta.__class__)
            if hasattr(cls._meta, '_field_name_cache'):
                del cls._meta._field_name_cache
            if hasattr(cls._meta, '_field_cache'):
                del cls._meta._field_cache
            cls._meta._fill_fields_cache()


            # No, no, no. This is wrong as it duplicates fields in _meta.fields:
            # # need to populate local_fields, otherwise no fields get serialized in fixtures
            # cls._meta.local_fields = base_class._meta.local_fields[:]
        else:
            # this is the base class
            cls._typedmodels_registry = {}

            # Dictionary containing lists of immediate children for each class.
            cls._typedmodels_children_registry = {cls: []}

            # Since fields may be added by subclasses, save original fields.
            cls._meta.original_fields = cls._meta.fields

            # set default manager. this will be inherited by subclasses, since they are proxy models
            manager = None
            if not cls._default_manager:
                manager = TypedModelManager()
            elif not isinstance(cls._default_manager, TypedModelManager):
                class Manager(TypedModelManager, cls._default_manager.__class__):
                    pass
                cls._default_manager.__class__ = Manager
                manager = cls._default_manager
            if manager is not None:
                cls.add_to_class('objects', manager)
                cls._default_manager = cls.objects

            # add a get_type_classes classmethod to allow fetching of all the subclasses (useful for admin)

            def get_type_classes(subcls):
                # This is a bit inconsistent since there is _typedmodels_subtypes
                # attribute on subclasses. Perhaps it should be unified to achieve
                # similar behavior on both root class and it's subclasses.
                if subcls is not cls:
                    raise ValueError("get_type_classes() is not accessible from subclasses of %s (was called from %s)" % (cls.__name__, subcls.__name__))
                return cls._typedmodels_registry.values()[:]
            cls.get_type_classes = classmethod(get_type_classes)
        return cls


class TypedModel(models.Model):
    '''
    This class contains the functionality required to auto-downcast a model based
    on its ``type`` attribute.

    To use, simply subclass TypedModel for your base type, and then subclass
    that for your concrete types.

    Example usage::

        from django.db import models
        from typedmodels import TypedModel

        class Animal(TypedModel):
            """
            Abstract model
            """
            name = models.CharField(max_length=255)

            def say_something(self):
                raise NotImplemented

            def __repr__(self):
                return u'<%s: %s>' % (self.__class__.__name__, self.name)

        class Canine(Animal):
            def say_something(self):
                return "woof"

        class Feline(Animal):
            def say_something(self):
                return "meoww"
    '''

    __metaclass__ = TypedModelMetaclass

    type = models.CharField(choices=(), max_length=255, null=False, blank=False, db_index=True)

    # Class variable indicating if model should be automatically recasted after initialization
    _auto_recast = True

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        # Calling __init__ on base class because some functions (e.g. save()) need access to field values from base
        # class.

        # Move args to kwargs since base_class may have more fields defined with different ordering
        args = list(args)
        if len(args) > len(self._meta.fields):
            # Daft, but matches old exception sans the err msg.
            raise IndexError("Number of args exceeds number of fields")
        for field_value, field in zip(args, self._meta.fields):
            kwargs[field.attname] = field_value
            args.pop(0)
            
        if self.base_class:
            before_class = self.__class__
            self.__class__ = self.base_class
        else:
            before_class = None
        super(TypedModel, self).__init__(*args, **kwargs)
        if before_class:
            self.__class__ = before_class
        if self._auto_recast:
            self.recast()

    def recast(self):
        if not self.type:
            if not hasattr(self, '_typedmodels_type'):
                # Ideally we'd raise an error here, but the django admin likes to call
                # model() and doesn't expect an error.
                # Instead, we raise an error when the object is saved.
                return
            self.type = self._typedmodels_type

        for base in self.__class__.mro():
            if issubclass(base, TypedModel) and hasattr(base, '_typedmodels_registry'):
                break
        else:
            raise ValueError("No suitable base class found to recast!")

        try:
            correct_cls = base._typedmodels_registry[self.type]
        except KeyError:
            raise ValueError("Invalid %s identifier : %r" % (base.__name__, self.type))

        if self.__class__ != correct_cls:
            self.__class__ = correct_cls

    @classmethod
    def children_typedmodels(cls):
        return (cls.base_class or cls)._typedmodels_children_registry[cls]

    @classmethod
    def parent_typedmodel(cls):
        try:
            return filter(lambda class_: issubclass(class_, TypedModel) and not class_==TypedModel, cls.__bases__)[0]
        except IndexError:
            return None

    def save(self, *args, **kwargs):
        if not getattr(self, '_typedmodels_type', None):
            raise RuntimeError("Untyped %s cannot be saved." % self.__class__.__name__)
        return super(TypedModel, self).save(*args, **kwargs)
