import os

from . import types
from .base_options import BaseOptions
from .builders import BuilderOptions, make_builder_options
from .freezedried import DictToListFreezeDryer, FreezeDried
from .objutils import memoize_method
from .path import Path
from .placeholder import placeholder
from .platforms import platform_name
from .origins import make_package_options, PackageOptions


class ExprSymbols(dict):
    def augment(self, *, paths=[], symbols={}):
        if not paths and not symbols:
            return self
        return ExprSymbols(
            **self,
            **({i: placeholder(Path('', i)) for i in paths}),
            **symbols
        )


class CommonOptions(FreezeDried, BaseOptions):
    _context = 'while adding common options'
    type = 'common'
    _version = 1

    @staticmethod
    def upgrade(config, version):
        return config

    def __init__(self, deploy_dirs=None):
        self.strict = types.Unset
        self.target_platform = types.Unset
        self.env = {}
        self.deploy_dirs = deploy_dirs or {}

    @staticmethod
    def _fill_env(env, new_env):
        if new_env:
            for k, v in new_env.items():
                if k not in env:
                    env[k] = v
        return env

    def __call__(self, *, strict=None, target_platform=types.Unset, env=None):
        T = types.TypeCheck(locals())
        if self.strict is types.Unset and strict is not None:
            T.strict(types.boolean)
        if self.target_platform is types.Unset:
            T.target_platform(types.maybe(types.string))
        T.env(types.maybe(types.dict_of(types.string, types.string)),
              reducer=self._fill_env)

    def finalize(self):
        if self.strict is types.Unset:
            self.strict = False
        if not self.target_platform:
            self.target_platform = platform_name()
        self._fill_env(self.env, os.environ)

    @property
    @memoize_method
    def expr_symbols(self):
        deploy_vars = {k: placeholder(Path(v)) for k, v in
                       self.deploy_dirs.items()}

        return ExprSymbols(
            host_platform=platform_name(),
            target_platform=self.target_platform,
            env=self.env,
            deploy_dirs=deploy_vars,
        )

    def __eq__(self, rhs):
        return (self.target_platform == rhs.target_platform and
                self.env == rhs.env)


@FreezeDried.fields(rehydrate={
    'common': CommonOptions,
    'origins': DictToListFreezeDryer(PackageOptions, lambda x: x.origin),
    'builders': DictToListFreezeDryer(BuilderOptions, lambda x: x.type),
})
class Options(FreezeDried):
    _option_makers = {'origins': make_package_options,
                      'builders': make_builder_options}
    option_kinds = list(_option_makers.keys())

    def __init__(self, deploy_dirs=None):
        self.common = CommonOptions(deploy_dirs)
        for i in self.option_kinds:
            setattr(self, i, {})

    def add(self, kind, name):
        opts = self._option_makers[kind](name)
        if opts is not None:
            getattr(self, kind)[name] = opts

    @property
    def expr_symbols(self):
        return self.common.expr_symbols

    @classmethod
    def default(cls):
        opts = cls()
        opts.common.finalize()
        return opts
