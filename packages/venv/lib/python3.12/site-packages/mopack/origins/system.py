from . import BinaryPackage
from .. import log
from ..types import FieldKeyError, Unset
from ..iterutils import slice_dict


class SystemPackage(BinaryPackage):
    origin = 'system'
    _version = 1

    @staticmethod
    def upgrade(config, version):
        return config

    def __init__(self, name, *, usage=Unset, inherit_defaults=False, **kwargs):
        if usage is not Unset:
            raise FieldKeyError((
                "'system' package doesn't accept 'usage' attribute; " +
                'pass usage options directly'
            ), 'usage')

        usage_kwargs = slice_dict(kwargs, {
            'auto_link', 'version', 'pcname', 'dependencies', 'include_path',
            'library_path', 'headers', 'libraries', 'compile_flags',
            'link_flags', 'submodule_map',
        })
        usage_kwargs.update({'type': 'system',
                             'inherit_defaults': inherit_defaults})

        super().__init__(
            name, usage=usage_kwargs, inherit_defaults=inherit_defaults,
            _usage_field=None, **kwargs
        )

    def resolve(self, metadata):
        log.pkg_resolve(self.name, 'from {}'.format(self.origin))
        self.resolved = True

    def deploy(self, metadata):
        pass


def fallback_system_package(name, options):
    pkg = SystemPackage(name, inherit_defaults=True, config_file=None,
                        _options=options)
    pkg.resolved = True
    return pkg
