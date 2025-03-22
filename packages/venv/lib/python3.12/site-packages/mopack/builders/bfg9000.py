import os

from . import Builder, BuilderOptions
from .. import types
from ..environment import get_cmd
from ..freezedried import FreezeDried
from ..log import LogFile
from ..path import pushd
from ..shell import ShellArguments

_known_install_types = ('prefix', 'exec-prefix', 'bindir', 'libdir',
                        'includedir')


@FreezeDried.fields(rehydrate={'extra_args': ShellArguments})
class Bfg9000Builder(Builder):
    type = 'bfg9000'
    _version = 1

    class Options(BuilderOptions):
        type = 'bfg9000'
        _version = 1

        @staticmethod
        def upgrade(config, version):
            return config

        def __init__(self):
            self.toolchain = types.Unset

        def __call__(self, *, toolchain=types.Unset, config_file,
                     _symbols, _child_config=False):
            if not _child_config and self.toolchain is types.Unset:
                T = types.TypeCheck(locals(), _symbols)
                config_dir = os.path.dirname(config_file)
                T.toolchain(types.maybe_raw(types.path_string(config_dir)))

    @staticmethod
    def upgrade(config, version):
        return config

    def __init__(self, pkg, *, extra_args=None, **kwargs):
        super().__init__(pkg, **kwargs)

        path_bases = pkg.path_bases(builder=self)
        symbols = self._options.expr_symbols.augment(paths=path_bases)
        T = types.TypeCheck(locals(), symbols)
        T.extra_args(types.shell_args(none_ok=True))

    def filter_usage(self, usage):
        if usage is None:
            return 'pkg_config'
        return usage

    def _toolchain_args(self, toolchain):
        return ['--toolchain', toolchain] if toolchain else []

    def _install_args(self, deploy_dirs):
        args = []
        for k, v in deploy_dirs.items():
            if k in _known_install_types:
                args.extend(['--' + k, v])
        return args

    def build(self, metadata, pkg):
        path_values = pkg.path_values(metadata, builder=self)

        env = self._common_options.env
        bfg9000 = get_cmd(env, 'BFG9000', 'bfg9000')
        ninja = get_cmd(env, 'NINJA', 'ninja')
        with LogFile.open(metadata.pkgdir, self.name) as logfile:
            with pushd(path_values['srcdir']):
                logfile.check_call(
                    bfg9000 + ['configure', path_values['builddir']] +
                    self._toolchain_args(self._this_options.toolchain) +
                    self._install_args(self._common_options.deploy_dirs) +
                    self.extra_args.fill(**path_values),
                    env=env
                )
            with pushd(path_values['builddir']):
                logfile.check_call(ninja, env=env)

    def deploy(self, metadata, pkg):
        path_values = pkg.path_values(metadata, builder=self)

        env = self._common_options.env
        ninja = get_cmd(env, 'NINJA', 'ninja')
        with LogFile.open(metadata.pkgdir, self.name,
                          kind='deploy') as logfile:
            with pushd(path_values['builddir']):
                logfile.check_call(ninja + ['install'], env=env)
