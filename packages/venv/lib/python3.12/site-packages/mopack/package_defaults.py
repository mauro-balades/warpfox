import os
import re
from copy import deepcopy
from pkg_resources import resource_filename
from yaml.error import MarkedYAMLError

from . import expression as expr, iterutils, types
from .objutils import memoize
from .yaml_tools import load_file, SafeLineLoader


class DefaultConfig:
    _known_genera = {'origin', 'usage'}

    def __init__(self, filename):
        with load_file(filename, Loader=SafeLineLoader) as cfg:
            # Store both a raw and parsed copy of the configuration data.
            # Parsing first helps catch syntax errors and should be faster in
            # some cases, but we still want the raw data for some cases, like
            # `submodule_map`.
            self._raw_data = cfg

            cfg = deepcopy(cfg)
            for genus, genus_cfg in cfg.items():
                if genus not in self._known_genera:
                    msg = 'unknown genus {!r}'.format(genus)
                    raise MarkedYAMLError(None, None, msg,
                                          cfg.marks[genus].start)
                self._process_genus(genus_cfg)
            self._data = cfg

    def _process_genus(self, data):
        for species, cfgs in data.items():
            if iterutils.isiterable(cfgs):
                for i, cfg in enumerate(cfgs):
                    if i < len(cfgs) - 1 and 'if' not in cfg:
                        ctx = 'while parsing default for {!r}'.format(species)
                        msg = ('default config has no `if` field, but is ' +
                               'not last entry of list')
                        raise MarkedYAMLError(ctx, cfgs.mark.start, msg,
                                              cfg.mark.start)
                    cfgs[i] = self._parse_default_fields(cfg)
            else:
                data[species] = self._parse_default_fields(cfgs)

    def _parse_default_fields(self, data):
        def parse_recursive(data):
            if isinstance(data, str):
                return expr.parse(data)
            elif (iterutils.issequence(data) or
                  iterutils.ismapping(data)):
                for k, v in iterutils.iteritems(data):
                    data[k] = parse_recursive(v)
                return data
            return data

        for k, v in data.items():
            if k == 'if':
                if isinstance(v, str):
                    data[k] = expr.parse(v, if_context=True)
            else:
                data[k] = parse_recursive(v)
        return data

    @staticmethod
    def _if_evaluate(symbols, expression):
        if isinstance(expression, bool):
            return expression
        return expression(symbols)

    @classmethod
    def _evaluate_recursive(cls, symbols, data):
        if isinstance(data, expr.Token):
            return data(symbols)
        elif iterutils.issequence(data):
            return [cls._evaluate_recursive(symbols, i) for i in data]
        elif iterutils.ismapping(data):
            return {k: cls._evaluate_recursive(symbols, v)
                    for k, v in data.items()}
        return data

    @classmethod
    def _select_from_list(cls, symbols, input_data, output_data=None):
        args = [input_data] + ([] if output_data is None else [output_data])
        if iterutils.issequence(input_data):
            for i in zip(*args):
                if cls._if_evaluate(symbols, i[0].get('if', True)):
                    return i[-1]
        return args[-1]

    def get(self, symbols, genus, species, field, default=None, *,
            evaluate=True):
        if genus not in self._known_genera:
            raise ValueError('unknown genus {!r}'.format(genus))

        defaults = self._data.get(genus, {})
        if evaluate:
            if species in defaults:
                fields = self._select_from_list(symbols, defaults[species])
                if field in fields:
                    return self._evaluate_recursive(symbols, fields[field])

            fields = self._select_from_list(symbols, defaults.get('*', {}))
            return self._evaluate_recursive(symbols,
                                            fields.get(field, default))
        else:
            raw_defaults = self._raw_data.get(genus, {})
            if species in defaults:
                fields = self._select_from_list(symbols, defaults[species],
                                                raw_defaults[species])
                if field in fields:
                    return fields[field]

            fields = self._select_from_list(symbols, defaults.get('*', {}),
                                            raw_defaults.get('*', {}))
            return fields.get(field, default)


@memoize
def _get_default_config(package_name):
    if re.search(r'\W', package_name):
        return None

    path = resource_filename('mopack', 'defaults/{}.yml'.format(package_name))
    if os.path.exists(path):
        return DefaultConfig(path)
    return None


def get_default(symbols, package_name, genus, species, field, default=None,
                **kwargs):
    default_cfg = _get_default_config(package_name)
    if default_cfg is None:
        return default
    return default_cfg.get(symbols, genus, species, field, default, **kwargs)


class DefaultResolver:
    def __init__(self, obj, symbols, get_defaults=True, name=None):
        self.package_name = name or obj.name
        self.genus = obj._default_genus
        self.species = getattr(obj, obj._type_field)
        self.symbols = symbols
        self.get_defaults = get_defaults

    def __call__(self, other, field=None, default=None, *, extra_symbols={},
                 **kwargs):
        forced_field = field
        symbols = self.symbols.augment(symbols=extra_symbols)

        def check(field, value):
            if value is types.Unset:
                if self.get_defaults:
                    value = get_default(
                        symbols, self.package_name, self.genus, self.species,
                        forced_field or field, default, **kwargs
                    )
                else:
                    value = default
            return other(field, value)

        return check
