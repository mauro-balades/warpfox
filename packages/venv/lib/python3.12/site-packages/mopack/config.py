import os
import warnings
from collections import namedtuple
from itertools import chain
from yaml.error import MarkedYAMLError

from . import expression as expr
from .iterutils import isiterable
from .options import Options
from .origins import try_make_package
from .yaml_tools import (load_file, to_parse_error, MarkedDict,
                         MarkedYAMLOffsetError, MarkedYAMLWarning,
                         SafeLineLoader)

mopack_file = 'mopack.yml'
mopack_local_file = 'mopack-local.yml'

PendingPackage = namedtuple('PendingPackage', ['config_file', 'config'])


class _PlaceholderPackage:
    def __repr__(self):
        return '<PlaceholderPackage>'


PlaceholderPackage = _PlaceholderPackage()


class BaseConfig:
    def __init__(self):
        self._pending_options = {i: {} for i in Options.option_kinds}
        self._pending_packages = {}

    def __bool__(self):
        return bool(self.files)

    @staticmethod
    def _expand_filenames(filenames):
        def append_if_exists(collection, name):
            if os.path.exists(name):
                collection.append(name)

        regular, local = [], []
        for f in filenames:
            f = os.path.abspath(f)
            if os.path.isdir(f):
                append_if_exists(regular, os.path.join(f, mopack_file))
                append_if_exists(local, os.path.join(f, mopack_local_file))
            else:
                regular.append(f)
        return regular + local

    def _load_configs(self, filenames):
        self.files = self._expand_filenames(filenames)
        self.implicit_files = []
        for f in reversed(self.files):
            self._accumulate_config(f)

    def _accumulate_config(self, filename):
        filename = os.path.abspath(filename)
        with load_file(filename, Loader=SafeLineLoader) as next_config:
            if next_config:
                for k, v in next_config.items():
                    fn = '_process_{}'.format(k)
                    if hasattr(self, fn):
                        getattr(self, fn)(filename, v)

    def _process_packages(self, filename, data):
        if not data:
            return

        for name, cfgs in data.items():
            # If a parent package has already defined this package,
            # just store a placeholder to track it. Otherwise, make the
            # real package object.
            if self._in_parent(name):
                if name not in self._pending_packages:
                    self._pending_packages[name] = PlaceholderPackage
                continue

            if name not in self._pending_packages:
                self._pending_packages[name] = []

            if isiterable(cfgs):
                for i, cfg in enumerate(cfgs):
                    if i < len(cfgs) - 1 and 'if' not in cfg:
                        ctx = 'while constructing package {!r}'.format(name)
                        msg = ('package config has no `if` field, but is ' +
                               'not last entry of list')
                        raise MarkedYAMLError(ctx, cfgs.mark.start, msg,
                                              cfg.mark.start)
                    pkg = PendingPackage(filename, cfg)
                    self._pending_packages[name].append(pkg)
            else:
                pkg = PendingPackage(filename, cfgs)
                self._pending_packages[name].append(pkg)

    def _process_options(self, filename, data):
        if not data:
            return

        # TODO: Remove this after v0.1 is released.
        if 'sources' in data:  # pragma: no cover
            warnings.warn(MarkedYAMLWarning(
                'while reading options', data.mark.start,
                '`sources` is deprecated; use `origins` instead',
                data.marks['sources'].start
            ))
            data['origins'] = data.pop('sources')

        for kind in Options.option_kinds:
            if kind in data:
                for k, v in data[kind].items():
                    if v is None:
                        v = MarkedDict(data[kind].marks[k])
                    v.update(config_file=filename, _child_config=self.child)
                    self._pending_options[kind].setdefault(k, []).append(v)

    def _finalize_packages(self, options, parent_package=None):
        self.packages = {}
        for name, cfgs in self._pending_packages.items():
            if cfgs is PlaceholderPackage:
                self.packages[name] = cfgs
                continue

            for config_file, cfg in cfgs:
                with to_parse_error(config_file):
                    if self._if_evaluate(options.expr_symbols, cfg, 'if'):
                        self.packages[name] = try_make_package(
                            name, cfg, parent=parent_package, _options=options,
                            config_file=config_file
                        )
                        break
        del self._pending_packages

    @staticmethod
    def _if_evaluate(symbols, data, key):
        try:
            mark = data.value_marks.get(key)
            expression = data.pop(key, True)
            if isinstance(expression, bool):
                return expression
            return expr.evaluate(symbols, expression, if_context=True)
        except expr.ParseBaseException as e:
            raise MarkedYAMLOffsetError('while parsing expression', data.mark,
                                        e.msg, mark, offset=e.loc)

    def _in_parent(self, name):
        # We don't have a parent, so this is always false!
        return False

    def _validate_children(self, children):
        # Ensure that there are no conflicting package definitions in any of
        # the children.
        by_name = {}
        for i in children:
            for k, v in i.packages.items():
                by_name.setdefault(k, []).append(v)
        for k, v in by_name.items():
            for i in range(1, len(v)):
                if v[0] != v[i]:
                    raise ValueError('conflicting definitions for package {!r}'
                                     .format(k))

    def add_children(self, children):
        self._validate_children(children)

        new_packages = {}
        for i in children:
            self.implicit_files.extend(i.files)
            self.implicit_files.extend(i.implicit_files)

            for k, v in i.packages.items():
                # We have a package that's needed by another; put it in our
                # packages before the package that depends on it. If it's in
                # our list already, use that one; otherwise, use the child's
                # definition.
                new_packages[k] = self.packages.pop(k, v)

            for kind in i._pending_options:
                for k, v in i._pending_options[kind].items():
                    self._pending_options[kind].setdefault(k, []).extend(v)
        new_packages.update(self.packages)
        self.packages = new_packages

    def __repr__(self):
        return '<{}({!r})>'.format(type(self).__name__, self.files)


class Config(BaseConfig):
    child = False

    def __init__(self, filenames, options=None, deploy_dirs=None):
        super().__init__()
        self.options = Options(deploy_dirs)
        self._process_options('<command-line>', options or {})
        self._load_configs(filenames)

        self.options.common.finalize()
        self._finalize_packages(self.options)

    def _process_options(self, filename, data):
        super()._process_options(filename, data)

        if data:
            common = data.copy()
            for i in Options.option_kinds:
                common.pop(i, None)
            if common:
                self.options.common.accumulate(common)

    def finalize(self):
        origins = {pkg.origin: True for pkg in self.packages.values()}
        builders = {i: True for i in chain.from_iterable(
            pkg.builder_types for pkg in self.packages.values()
        )}

        for i in origins:
            self.options.add('origins', i)
        for i in builders:
            self.options.add('builders', i)

        for kind in self._pending_options:
            for name, cfgs in self._pending_options[kind].items():
                if name in getattr(self.options, kind):
                    for cfg in cfgs:
                        final = cfg.pop('final', False)
                        getattr(self.options, kind)[name].accumulate(
                            cfg, _symbols=self.options.expr_symbols
                        )
                        if final:
                            break
        del self._pending_options


class ChildConfig(BaseConfig):
    child = True

    class Export:
        def __init__(self, data, config_file):
            self.config_file = config_file
            self.data = data

        @property
        def submodules(self):
            return self.data.get('submodules')

        @property
        def build(self):
            return self.data.get('build')

        @property
        def usage(self):
            return self.data.get('usage')

    def __init__(self, filenames, parent_config, parent_package):
        super().__init__()
        self.parent = parent_config
        self.export = None
        self._load_configs(filenames)
        self._finalize_packages(self._root_config.options, parent_package)

    @property
    def _root_config(self):
        cfg = self.parent
        while hasattr(cfg, 'parent'):
            cfg = cfg.parent
        return cfg

    def _in_parent(self, name):
        return name in self.parent.packages or self.parent._in_parent(name)

    def _process_export(self, filename, data):
        self.export = self.Export(data, filename)
