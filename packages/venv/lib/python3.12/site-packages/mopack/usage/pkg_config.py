import subprocess
from collections import ChainMap

from . import preferred_path_base, Usage
from . import submodules as submod
from .. import types
from ..environment import get_pkg_config, subprocess_run
from ..freezedried import DictFreezeDryer, FreezeDried, ListFreezeDryer
from ..iterutils import listify
from ..package_defaults import DefaultResolver
from ..path import Path
from ..shell import join_paths


class _SubmoduleMapping(FreezeDried):
    def __init__(self, *, pcname=None):
        # Just check that we can fill submodule values correctly.
        self._fill(locals())

        # Since we need to delay evaluating symbols until we know what the
        # selected submodule is, just store these values unevaluated. We'll
        # evaluate them later during `mopack usage` via the fill() function.
        self.pcname = pcname

    def _fill(self, context, submodule_name='SUBMODULE'):
        def P(other):
            return types.placeholder_fill(other, submod.placeholder,
                                          submodule_name)

        result = type(self).__new__(type(self))
        T = types.TypeCheck(context, submod.expr_symbols, dest=result)
        T.pcname(P(types.maybe(types.string)))
        return result

    def fill(self, submodule_name):
        return self._fill(self.__dict__, submodule_name)


def _submodule_map(field, value):
    def check_item(field, value):
        with types.wrap_field_error(field):
            return _SubmoduleMapping(**value)

    try:
        value = {'*': {'pcname': types.placeholder_string(field, value)}}
    except types.FieldError:
        pass

    return types.dict_of(types.string, check_item)(field, value)


@FreezeDried.fields(rehydrate={
    'pkg_config_path': ListFreezeDryer(Path),
    'submodule_map': DictFreezeDryer(value_type=_SubmoduleMapping),
})
class PkgConfigUsage(Usage):
    type = 'pkg_config'
    _version = 1

    @staticmethod
    def upgrade(config, version):
        return config

    def __init__(self, pkg, *, pcname=types.Unset, pkg_config_path='pkgconfig',
                 submodule_map=types.Unset, inherit_defaults=False):
        super().__init__(pkg, inherit_defaults=inherit_defaults)

        path_bases = pkg.path_bases(builder=True)
        symbols = self._options.expr_symbols.augment(paths=path_bases)
        pkg_default = DefaultResolver(self, symbols, inherit_defaults,
                                      pkg.name)
        buildbase = preferred_path_base('builddir', path_bases)
        if pkg.submodules and pkg.submodules['required']:
            # If submodules are required, default to an empty .pc file, since
            # we should usually have .pc files for the submodules that handle
            # everything for us.
            default_pcname = None
        else:
            default_pcname = pkg.name

        T = types.TypeCheck(locals(), symbols)
        T.pcname(types.maybe(types.string, default=default_pcname))
        T.pkg_config_path(types.list_of(types.abs_or_inner_path(buildbase),
                                        listify=True))

        if pkg.submodules:
            T.submodule_map(pkg_default(
                types.maybe(_submodule_map),
                default=pkg.name + '_$submodule',
                extra_symbols=submod.expr_symbols,
                evaluate=False
            ), evaluate=False)

    def version(self, metadata, pkg):
        pkg_config = get_pkg_config(self._common_options.env)
        path_values = pkg.path_values(metadata, builder=True)
        pkgconfpath = [i.string(**path_values) for i in self.pkg_config_path]
        env = ChainMap({'PKG_CONFIG_PATH': join_paths(pkgconfpath)},
                       self._common_options.env)

        return subprocess_run(
            pkg_config + [self.pcname, '--modversion'], check=True,
            stdout=subprocess.PIPE, universal_newlines=True, env=env
        ).stdout.strip()

    def _get_submodule_mapping(self, submodule):
        try:
            return self.submodule_map[submodule].fill(submodule)
        except KeyError:
            return self.submodule_map['*'].fill(submodule)

    def get_usage(self, metadata, pkg, submodules):
        path_values = pkg.path_values(metadata, builder=True)
        pkgconfpath = [i.string(**path_values) for i in self.pkg_config_path]

        if submodules and self.submodule_map:
            mappings = [self._get_submodule_mapping(i) for i in submodules]
        else:
            mappings = []

        pcnames = listify(self.pcname)
        for i in mappings:
            if i.pcname:
                pcnames.append(i.pcname)

        return self._usage(pkg, submodules, pcnames=pcnames,
                           pkg_config_path=pkgconfpath)
