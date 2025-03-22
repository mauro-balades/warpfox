import os
import re
import subprocess
from itertools import chain

from . import preferred_path_base, Usage
from . import submodules as submod
from .. import types
from ..environment import get_pkg_config, subprocess_run
from ..freezedried import DictFreezeDryer, FreezeDried, ListFreezeDryer
from ..iterutils import ismapping, listify, uniques
from ..package_defaults import DefaultResolver
from ..path import file_outdated, isfile, Path
from ..pkg_config import generated_pkg_config_dir, write_pkg_config
from ..shell import ShellArguments, split_paths
from ..types import dependency_string, Unset


# XXX: Getting build configuration like this from the environment is a bit
# hacky. Maybe there's a better way?

def _system_include_path(env=os.environ):
    return [Path(i) for i in split_paths(env.get('MOPACK_INCLUDE_PATH'))]


def _system_lib_path(env=os.environ):
    return [Path(i) for i in split_paths(env.get('MOPACK_LIB_PATH'))]


def _system_lib_names(env=os.environ):
    return split_paths(env.get('MOPACK_LIB_NAMES'))


def _library(field, value):
    try:
        return types.string(field, value)
    except types.FieldError:
        value = types.dict_shape({
            'type': types.constant('library', 'framework'),
            'name': types.string
        }, desc='library')(field, value)
        if value['type'] == 'library':
            return value['name']
        return value


def _list_of_paths(base):
    return types.list_of(types.abs_or_inner_path(base), listify=True)


_version_def = types.one_of(
    types.maybe(types.string),
    types.dict_shape({
        'type': types.constant('regex'),
        'file': types.string,
        'regex': types.list_of(
            types.one_of(
                types.string,
                types.list_of_length(types.string, 2),
                desc='string or pair of strings'
            )
        ),
    }, desc='version finder'),
    desc='version definition'
)

_list_of_dependencies = types.list_of(types.dependency, listify=True)
_list_of_headers = types.list_of(types.string, listify=True)
_list_of_libraries = types.list_of(_library, listify=True)

_PathListFD = ListFreezeDryer(Path)


class _PathSubmoduleMapping(FreezeDried):
    def __init__(self, symbols, path_bases, *, dependencies=None,
                 include_path=None, library_path=None, headers=None,
                 libraries=None, compile_flags=None, link_flags=None):
        # Since we need to delay evaluating symbols until we know what the
        # selected submodule is, just store these values unevaluated. We'll
        # evaluate them later during `mopack usage` via the fill() function.
        self.dependencies = dependencies
        self.include_path = include_path
        self.library_path = library_path
        self.headers = headers
        self.libraries = libraries
        self.compile_flags = compile_flags
        self.link_flags = link_flags

        # Just check that we can fill submodule values correctly.
        self.fill(symbols, path_bases, 'SUBMODULE')

    def fill(self, symbols, path_bases, submodule_name):
        def P(other):
            return types.placeholder_fill(other, submod.placeholder,
                                          submodule_name)

        symbols = symbols.augment(symbols=submod.expr_symbols)

        result = type(self).__new__(type(self))
        T = types.TypeCheck(self.__dict__, symbols, dest=result)
        for field, check in self._fields(path_bases).items():
            T(field, P(check))
        return result

    def _fields(self, path_bases):
        srcbase = preferred_path_base('srcdir', path_bases)
        buildbase = preferred_path_base('builddir', path_bases)
        return {
            'dependencies':  _list_of_dependencies,
            'include_path':  _list_of_paths(srcbase),
            'library_path':  _list_of_paths(buildbase),
            'headers':       _list_of_headers,
            'libraries':     _list_of_libraries,
            'compile_flags': types.shell_args(none_ok=True),
            'link_flags':    types.shell_args(none_ok=True),
        }


@FreezeDried.fields(rehydrate={
    'include_path': _PathListFD, 'library_path': _PathListFD,
    'compile_flags': ShellArguments, 'link_flags': ShellArguments,
    'submodule_map': DictFreezeDryer(value_type=_PathSubmoduleMapping),
})
class PathUsage(Usage):
    type = 'path'
    _version = 1
    SubmoduleMapping = _PathSubmoduleMapping

    @staticmethod
    def upgrade(config, version):
        return config

    def __init__(self, pkg, *, auto_link=Unset, version=Unset,
                 dependencies=Unset, include_path=Unset, library_path=Unset,
                 headers=Unset, libraries=Unset, compile_flags=Unset,
                 link_flags=Unset, submodule_map=Unset,
                 inherit_defaults=False):
        super().__init__(pkg, inherit_defaults=inherit_defaults)

        path_bases = pkg.path_bases(builder=True)
        symbols = self._options.expr_symbols.augment(paths=path_bases)
        pkg_default = DefaultResolver(self, symbols, inherit_defaults,
                                      pkg.name)
        srcbase = preferred_path_base('srcdir', path_bases)
        buildbase = preferred_path_base('builddir', path_bases)

        T = types.TypeCheck(locals(), symbols)
        # XXX: Maybe have the compiler tell *us* if it supports auto-linking,
        # instead of us telling it?
        T.auto_link(pkg_default(types.boolean, default=False))

        T.version(pkg_default(_version_def), dest_field='explicit_version')
        T.dependencies(pkg_default(_list_of_dependencies))

        # XXX: These specify the *possible* paths to find headers/libraries.
        # Should there be a way of specifying paths that are *always* passed to
        # the compiler?
        T.include_path(pkg_default(_list_of_paths(srcbase)))
        T.library_path(pkg_default(_list_of_paths(buildbase)))

        T.headers(pkg_default(_list_of_headers))

        if self.auto_link or pkg.submodules and pkg.submodules['required']:
            # If auto-linking or if submodules are required, default to an
            # empty list of libraries, since we likely don't have a "base"
            # library that always needs linking to.
            libs_checker = types.maybe(_list_of_libraries, default=[])
        else:
            libs_checker = pkg_default(
                _list_of_libraries, default=pkg.name
            )
        T.libraries(libs_checker)
        T.compile_flags(pkg_default(types.shell_args(none_ok=True)))
        T.link_flags(pkg_default(types.shell_args(none_ok=True)))

        if pkg.submodules:
            T.submodule_map(pkg_default(
                types.maybe(self._submodule_map(symbols, path_bases)),
                default=pkg.name + '_$submodule',
                extra_symbols=submod.expr_symbols,
                evaluate=False
            ), evaluate=False)

    @classmethod
    def _submodule_map(cls, symbols, path_bases):
        def check_item(field, value):
            with types.wrap_field_error(field):
                return cls.SubmoduleMapping(symbols, path_bases, **value)

        def check(field, value):
            try:
                value = {'*': {
                    'libraries': types.placeholder_string(field, value)
                }}
            except types.FieldError:
                pass

            return types.dict_of(types.string, check_item)(field, value)

        return check

    def _get_submodule_mapping(self, symbols, path_bases, submodule):
        try:
            mapping = self.submodule_map[submodule]
        except KeyError:
            mapping = self.submodule_map['*']
        return mapping.fill(symbols, path_bases, submodule)

    @staticmethod
    def _link_library(lib):
        if isinstance(lib, str):
            return ['-l' + lib]

        assert lib['type'] == 'framework'
        return ['-framework', lib['name']]

    @staticmethod
    def _filter_path(fn, path, files, kind):
        filtered = {}
        for f in files:
            for p in path:
                if fn(p, f):
                    filtered[p] = True
                    break
            else:
                raise ValueError('unable to find {} {!r}'.format(kind, f))
        return list(filtered.keys())

    @classmethod
    def _include_dirs(cls, headers, include_path, path_vars):
        headers = listify(headers, scalar_ok=False)
        include_path = (listify(include_path, scalar_ok=False) or
                        _system_include_path())
        return cls._filter_path(
            lambda p, f: isfile(p.append(f), path_vars),
            include_path, headers, 'header'
        )

    @classmethod
    def _library_dirs(cls, auto_link, libraries, library_path, path_vars):
        library_path = (listify(library_path, scalar_ok=False)
                        or _system_lib_path())
        if auto_link:
            # When auto-linking, we can't determine the library dirs that are
            # actually used, so include them all.
            return library_path

        lib_names = _system_lib_names()
        return cls._filter_path(
            lambda p, f: any(isfile(p.append(i.format(f)), path_vars)
                             for i in lib_names),
            library_path, (i for i in libraries if isinstance(i, str)),
            'library'
        )

    @staticmethod
    def _match_line(ex, line):
        if isinstance(ex, str):
            m = re.search(ex, line)
            line = m.group(1) if m else None
            return line is not None, line
        else:
            return True, re.sub(ex[0], ex[1], line)

    def _get_version(self, metadata, pkg, include_dirs, path_vars):
        if ismapping(self.explicit_version):
            version = self.explicit_version
            for path in include_dirs:
                header = path.append(version['file'])
                try:
                    with open(header.string(**path_vars)) as f:
                        for line in f:
                            for ex in version['regex']:
                                found, line = self._match_line(ex, line)
                                if not found:
                                    break
                            else:
                                return line
                except FileNotFoundError:
                    pass
            return None
        elif self.explicit_version is not None:
            return self.explicit_version
        else:
            return pkg.guessed_version(metadata)

    def version(self, metadata, pkg):
        path_values = pkg.path_values(metadata, builder=True)
        try:
            include_dirs = self._include_dirs(
                self.headers, self.include_path, path_values
            )
        except ValueError:  # pragma: no cover
            # XXX: This is a hack to work around the fact that we currently
            # require the build system to pass include dirs during `usage` (and
            # really, during `list-packages` too). We should handle this in a
            # smarter way and then remove this.
            include_dirs = []

        return self._get_version(metadata, pkg, include_dirs, path_values)

    def _write_pkg_config(self, metadata, pkg, submodule=None, version=None,
                          requires=[], mappings=None, *, get_version=False):
        if mappings is None:
            mappings = [self]

        def chain_attr(key):
            for i in mappings:
                yield from getattr(i, key)

        path_values = pkg.path_values(metadata, builder=True)
        pkgconfdir = generated_pkg_config_dir(metadata.pkgdir)
        pcname = dependency_string(pkg.name, listify(submodule))
        pcpath = os.path.join(pkgconfdir, pcname + '.pc')

        # Ensure all dependencies are up-to-date and get their usages.
        auto_link = self.auto_link
        deps_requires = []
        deps_paths = [pkgconfdir]
        for dep_pkg, dep_sub in chain_attr('dependencies'):
            # XXX: Cache usage so we don't repeatedly process the same package.
            usage = metadata.get_package(dep_pkg).get_usage(metadata, dep_sub)

            auto_link |= usage.get('auto_link', False)
            deps_requires.extend(usage.get('pcnames', []))
            deps_paths.extend(usage.get('pkg_config_path', []))

        should_write = file_outdated(pcpath, metadata.path)

        if should_write or get_version:
            # Get the version so we can sync it across all submodules.
            include_dirs = self._include_dirs(
                chain_attr('headers'), chain_attr('include_path'), path_values
            )
            if get_version or version is None:
                version = self._get_version(metadata, pkg, include_dirs,
                                            path_values)

        if should_write:
            # Generate the pkg-config data...
            libraries = list(chain_attr('libraries'))
            library_dirs = self._library_dirs(
                self.auto_link, libraries, chain_attr('library_path'),
                path_values
            )

            cflags = (
                [('-I', i) for i in include_dirs] +
                ShellArguments(chain_attr('compile_flags'))
            )
            libs = (
                [('-L', i) for i in library_dirs] +
                ShellArguments(chain_attr('link_flags')) +
                chain.from_iterable(self._link_library(i) for i in libraries)
            )

            # ... and write it.
            os.makedirs(pkgconfdir, exist_ok=True)
            with open(pcpath, 'w') as f:
                write_pkg_config(f, pcname, version=version,
                                 requires=requires + deps_requires,
                                 cflags=cflags, libs=libs,
                                 variables=path_values)

        result = {'auto_link': auto_link, 'pcname': pcname,
                  'pkg_config_path': uniques(deps_paths)}
        if get_version:
            result['version'] = version
        return result

    def get_usage(self, metadata, pkg, submodules):
        if submodules and self.submodule_map:
            pkgconfpath, requires = [], []
            auto_link = False
            version = None

            if pkg.submodules['required']:
                # Don't make a base .pc file; just include the data from the
                # base in each submodule's .pc file.
                mappings = [self]
            else:
                mappings = []
                data = self._write_pkg_config(metadata, pkg, get_version=True)
                auto_link |= data['auto_link']
                requires.append(data['pcname'])
                pkgconfpath.extend(data['pkg_config_path'])
                version = data['version']

            path_bases = pkg.path_bases(builder=True)
            symbols = self._options.expr_symbols.augment(paths=path_bases)

            pcnames = []
            for i in submodules:
                mapping = self._get_submodule_mapping(symbols, path_bases, i)
                data = self._write_pkg_config(metadata, pkg, i, version,
                                              requires, mappings + [mapping])
                auto_link |= data['auto_link']
                pcnames.append(data['pcname'])
                pkgconfpath.extend(data['pkg_config_path'])
        else:
            data = self._write_pkg_config(metadata, pkg)
            auto_link = data['auto_link']
            pcnames = [data['pcname']]
            pkgconfpath = data['pkg_config_path']

        return self._usage(
            pkg, submodules, generated=True, auto_link=auto_link,
            pcnames=pcnames, pkg_config_path=uniques(pkgconfpath)
        )


class _SystemSubmoduleMapping(_PathSubmoduleMapping):
    def __init__(self, *args, pcname=None, **kwargs):
        self.pcname = pcname
        super().__init__(*args, **kwargs)

    def _fields(self, path_bases):
        result = super()._fields(path_bases)
        result.update({
            'pcname': types.maybe(types.string),
        })
        return result


@FreezeDried.fields(rehydrate={
    'submodule_map': DictFreezeDryer(value_type=_SystemSubmoduleMapping),
})
class SystemUsage(PathUsage):
    type = 'system'
    SubmoduleMapping = _SystemSubmoduleMapping

    def __init__(self, pkg, *, pcname=Unset, inherit_defaults=False, **kwargs):
        super().__init__(pkg, inherit_defaults=inherit_defaults, **kwargs)

        path_bases = pkg.path_bases(builder=True)
        symbols = self._options.expr_symbols.augment(paths=path_bases)
        pkg_default = DefaultResolver(self, symbols, inherit_defaults,
                                      pkg.name)

        T = types.TypeCheck(locals(), symbols)
        T.pcname(pkg_default(types.string, default=pkg.name))

    def version(self, metadata, pkg):
        pkg_config = get_pkg_config(self._common_options.env)
        try:
            # XXX: Make sure this works when submodules are required.
            return subprocess_run(
                pkg_config + [self.pcname, '--modversion'], check=True,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                universal_newlines=True,
                env=self._common_options.env
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return super().version(metadata, pkg)

    def get_usage(self, metadata, pkg, submodules):
        if submodules and self.submodule_map:
            pcnames = [] if pkg.submodules['required'] else [self.pcname]
            path_bases = pkg.path_bases(builder=True)
            symbols = self._options.expr_symbols.augment(paths=path_bases)
            for i in submodules:
                mapping = self._get_submodule_mapping(symbols, path_bases, i)
                if mapping.pcname:
                    pcnames.append(mapping.pcname)
        else:
            pcnames = [self.pcname]

        env = self._common_options.env
        pkg_config = get_pkg_config(env)
        try:
            subprocess_run(pkg_config + pcnames, check=True,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,
                           env=env)
            return self._usage(pkg, submodules, pcnames=pcnames,
                               pkg_config_path=[])
        except (OSError, subprocess.CalledProcessError):
            return super().get_usage(metadata, pkg, submodules)
