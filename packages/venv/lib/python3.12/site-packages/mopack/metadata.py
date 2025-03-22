import json
import os

from .config import Options
from .freezedried import DictToListFreezeDryer
from .origins import Package
from .origins.system import fallback_system_package
from .yaml_tools import MarkedJSONEncoder


class MetadataVersionError(RuntimeError):
    pass


class Metadata:
    _PackagesFD = DictToListFreezeDryer(Package, lambda x: x.name)
    metadata_filename = 'mopack.json'
    version = 2

    def __init__(self, pkgdir, options=None, files=None, implicit_files=None):
        self.pkgdir = pkgdir
        self.options = options or Options.default()
        self.files = files or []
        self.implicit_files = implicit_files or []
        self.packages = {}

    @property
    def path(self):
        return os.path.join(self.pkgdir, self.metadata_filename)

    def add_package(self, package):
        self.packages[package.name] = package

    def get_package(self, name):
        if name in self.packages:
            package = self.packages[name]
        elif self.options.common.strict:
            raise KeyError('no definition for package {!r}'.format(name))
        else:
            package = fallback_system_package(name, self.options)

        if not package.resolved:
            raise ValueError('package {!r} has not been resolved successfully'
                             .format(name))
        return package

    def save(self):
        os.makedirs(self.pkgdir, exist_ok=True)
        with open(os.path.join(self.path), 'w') as f:
            json.dump({
                'version': self.version,
                'config_files': {
                    'explicit': self.files,
                    'implicit': self.implicit_files,
                },
                'metadata': {
                    'options': self.options.dehydrate(),
                    'packages': self._PackagesFD.dehydrate(self.packages),
                }
            }, f, cls=MarkedJSONEncoder)

    @classmethod
    def load(cls, pkgdir, strict=False):
        with open(os.path.join(pkgdir, cls.metadata_filename)) as f:
            state = json.load(f)
            version, data = state['version'], state['metadata']
        if version > cls.version:
            raise MetadataVersionError(
                'saved version {} exceeds expected version {}'
                .format(version, cls.version)
            )

        # v2 renames deploy_paths to deploy_dirs and source to origin.
        if version < 2:
            opts = data['options']
            opts['common']['deploy_dirs'] = opts['common'].pop('deploy_paths')
            opts['origins'] = opts.pop('sources')
            for orig in opts['origins']:
                orig['origin'] = orig.pop('source')
            for pkg in data['packages']:
                pkg['origin'] = pkg.pop('source')

        metadata = Metadata.__new__(Metadata)
        metadata.pkgdir = pkgdir
        metadata.files = state['config_files']['explicit']
        metadata.implicit_files = state['config_files']['implicit']

        metadata.options = Options.rehydrate(data['options'])
        if strict:
            metadata.options.common.strict = True

        metadata.packages = cls._PackagesFD.rehydrate(
            data['packages'], _options=metadata.options
        )

        return metadata

    @classmethod
    def try_load(cls, pkgdir, strict=False):
        try:
            return Metadata.load(pkgdir, strict)
        except FileNotFoundError:
            if strict:
                raise
            return Metadata(pkgdir)
