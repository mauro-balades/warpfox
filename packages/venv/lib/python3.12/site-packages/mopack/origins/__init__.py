import os
import warnings
from pkg_resources import load_entry_point

from .. import types
from ..base_options import BaseOptions, OptionsHolder
from ..freezedried import FreezeDried
from ..iterutils import ismapping, listify
from ..package_defaults import DefaultResolver
from ..types import FieldKeyError, FieldValueError, try_load_config
from ..usage import Usage, make_usage
from ..yaml_tools import MarkedYAMLWarning


def _get_origin_type(origin, field='origin'):
    try:
        return load_entry_point('mopack', 'mopack.origins', origin)
    except ImportError:
        raise FieldValueError('unknown origin {!r}'.format(origin), field)


_submodule_dict = types.dict_shape({
    'names': types.one_of(types.list_of(types.string), types.constant('*'),
                          desc='a list of submodules'),
    'required': types.boolean,
}, desc='a list of submodules')


def submodules_type(field, value):
    if value is None:
        return None
    elif not ismapping(value):
        value = {
            'names': value,
            'required': True,
        }
    return _submodule_dict(field, value)


@FreezeDried.fields(skip_compare={'parent', 'config_file', 'resolved'})
class Package(OptionsHolder):
    _options_type = 'origins'
    _default_genus = 'origin'
    _type_field = 'origin'
    _get_type = _get_origin_type

    Options = None

    def __init__(self, name, *, deploy=True, parent=None,
                 inherit_defaults=False, _options, config_file):
        super().__init__(_options)
        self.name = name
        self.config_file = config_file
        self.resolved = False
        self.parent = parent.name if parent else None

        T = types.TypeCheck(locals(), self._expr_symbols)
        T.deploy(types.boolean, dest_field='should_deploy')

    @property
    def _expr_symbols(self):
        return self._options.expr_symbols.augment(paths=['cfgdir'])

    @property
    def config_dir(self):
        return os.path.dirname(self.config_file)

    @property
    def needs_dependencies(self):
        return False

    def guessed_version(self, metadata):
        return None

    def version(self, metadata):
        return self.usage.version(metadata, self)

    def _check_submodules(self, wanted_submodules):
        if self.submodules:
            if self.submodules['required'] and not wanted_submodules:
                raise ValueError('package {!r} requires submodules'
                                 .format(self.name))

            wanted_submodules = listify(wanted_submodules)
            if self.submodules['names'] != '*':
                for i in wanted_submodules:
                    if i not in self.submodules['names']:
                        raise ValueError(
                            'unrecognized submodule {!r} for package {!r}'
                            .format(i, self.name)
                        )
            return wanted_submodules
        elif wanted_submodules:
            raise ValueError('package {!r} has no submodules'
                             .format(self.name))
        return None

    @property
    def builder_types(self):
        return []

    def clean_pre(self, metadata, new_package, quiet=False):
        return False

    def clean_post(self, metadata, new_package, quiet=False):
        return False

    def clean_all(self, metadata, new_package, quiet=False):
        return (self.clean_pre(metadata, new_package, quiet),
                self.clean_post(metadata, new_package, quiet))

    def fetch(self, metadata, parent_config):
        pass  # pragma: no cover

    def get_usage(self, metadata, submodules):
        return self.usage.get_usage(
            metadata, self, self._check_submodules(submodules)
        )

    def __repr__(self):
        return '<{}({!r})>'.format(type(self).__name__, self.name)


@FreezeDried.fields(rehydrate={'usage': Usage})
class BinaryPackage(Package):
    def __init__(self, name, *, submodules=types.Unset, usage,
                 inherit_defaults=False, _options, _usage_field='usage',
                 **kwargs):
        super().__init__(name, inherit_defaults=inherit_defaults,
                         _options=_options, **kwargs)

        symbols = self._expr_symbols
        pkg_default = DefaultResolver(self, symbols, inherit_defaults, name)
        T = types.TypeCheck(locals(), symbols)
        T.submodules(pkg_default(submodules_type))

        self.usage = make_usage(self, usage, field=_usage_field)

    def path_bases(self, *, builder=None):
        return ()

    def path_values(self, metadata, *, builder=None):
        return {}


class PackageOptions(FreezeDried, BaseOptions):
    _type_field = 'origin'

    @property
    def _context(self):
        return 'while adding options for {!r} origin'.format(self.origin)

    @staticmethod
    def _get_type(origin):
        return _get_origin_type(origin).Options


def make_package(name, config, **kwargs):
    if config is None:
        raise TypeError('usage not specified')
    # config_file should always be specified in kwargs.
    if 'config_file' in config:
        raise FieldKeyError('config_file is reserved', 'config_file')

    config = config.copy()
    try:
        origin = config.pop('origin')
    except KeyError as e:  # pragma: no cover
        # TODO: Remove this after v0.1 is released.
        try:
            context = 'while constructing package {!r}'.format(name)
            warning = MarkedYAMLWarning(
                context, config.mark.start,
                '`source` is deprecated; use `origin` instead',
                config.marks['source'].start
            )

            origin = config.pop('source')
            warnings.warn(warning)
        except KeyError:
            raise e

    if not config:
        config = {'inherit_defaults': True}

    return _get_origin_type(origin)(name, **config, **kwargs)


def try_make_package(name, config, **kwargs):
    context = 'while constructing package {!r}'.format(name)
    try:
        origin = config['origin']
    except KeyError:  # pragma: no cover
        # TODO: Remove this after v0.1 is released.
        origin = config.get('source')

    with try_load_config(config, context, origin):
        return make_package(name, config, **kwargs)


def make_package_options(origin):
    opts = _get_origin_type(origin).Options
    return opts() if opts else None
