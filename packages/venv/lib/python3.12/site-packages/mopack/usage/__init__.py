from pkg_resources import load_entry_point

from ..base_options import OptionsHolder
from ..types import FieldValueError, dependency_string, wrap_field_error


def _get_usage_type(type, field='type'):
    try:
        return load_entry_point('mopack', 'mopack.usage', type)
    except ImportError:
        raise FieldValueError('unknown usage {!r}'.format(type), field)


def preferred_path_base(preferred, path_bases):
    if preferred in path_bases:
        return preferred
    elif len(path_bases) > 0:
        return path_bases[0]
    else:
        return None


class Usage(OptionsHolder):
    _default_genus = 'usage'
    _type_field = 'type'
    _get_type = _get_usage_type

    def __init__(self, pkg, *, inherit_defaults=False):
        super().__init__(pkg._options)

    def version(self, metadata, pkg):
        raise NotImplementedError('Usage.version not implemented')

    def _usage(self, pkg, submodules, **kwargs):
        return {'name': dependency_string(pkg.name, submodules),
                'type': self.type, **kwargs}

    def get_usage(self, metadata, pkg, submodules):
        raise NotImplementedError('Usage.get_usage not implemented')

    def __repr__(self):
        return '<{}, {}>'.format(type(self).__name__, self.__dict__)


def make_usage(pkg, config, *, field='usage', **kwargs):
    if config is None:
        raise TypeError('usage not specified')

    if isinstance(config, str):
        type_field = ()
        type = config
        config = {}
    else:
        type_field = 'type'
        config = config.copy()
        type = config.pop('type')

    if not config:
        config = {'inherit_defaults': True}

    with wrap_field_error(field, type):
        return _get_usage_type(type, type_field)(pkg, **config, **kwargs)
