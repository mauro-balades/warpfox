import os
import shutil

from . import log
from .config import PlaceholderPackage
from .exceptions import ConfigurationError
from .metadata import Metadata

mopack_dirname = 'mopack'


def get_package_dir(builddir):
    return os.path.abspath(os.path.join(builddir, mopack_dirname))


class PackageTreeItem:
    def __init__(self, package, version, children=None):
        self.package = package
        self.version = version
        self.children = children or []


def clean(pkgdir):
    shutil.rmtree(pkgdir)


def _do_fetch(config, old_metadata, pkgdir):
    child_configs = []
    for pkg in config.packages.values():
        # If we have a placeholder package, a parent config has a definition
        # for it, so skip it.
        if pkg is PlaceholderPackage:
            continue

        # Clean out the old package sources if needed.
        if pkg.name in old_metadata.packages:
            old_metadata.packages[pkg.name].clean_pre(old_metadata, pkg)

        # Fetch the new package and check for child mopack configs.
        try:
            # XXX: Since this is a new package, maybe it would be more sensible
            # to pass the *new* metadata object to it. However, in the current
            # implementation, the new metadata object hasn't been created yet.
            # Currently, this doesn't cause any real issues though, since the
            # pkgdir should be the same either way, and fetch() shouldn't need
            # any other info.
            child_config = pkg.fetch(old_metadata, config)
        except Exception:
            pkg.clean_pre(old_metadata, None, quiet=True)
            raise

        if child_config:
            child_configs.append(child_config)
            _do_fetch(child_config, old_metadata, pkgdir)
    config.add_children(child_configs)


def _fill_metadata(config, pkgdir):
    config.finalize()
    metadata = Metadata(pkgdir, config.options, config.files,
                        config.implicit_files)
    for pkg in config.packages.values():
        metadata.add_package(pkg)
    return metadata


def fetch(config, pkgdir):
    log.LogFile.clean_logs(pkgdir)

    old_metadata = Metadata.try_load(pkgdir)
    try:
        _do_fetch(config, old_metadata, pkgdir)
    except ConfigurationError:
        raise
    except Exception:
        _fill_metadata(config, pkgdir).save()
        raise

    metadata = _fill_metadata(config, pkgdir)

    # Clean out old package data if needed.
    for pkg in config.packages.values():
        old = old_metadata.packages.pop(pkg.name, None)
        if old:
            old.clean_post(old_metadata, pkg)

    # Clean removed packages.
    for pkg in old_metadata.packages.values():
        pkg.clean_all(old_metadata, None)

    return metadata


def resolve(config, pkgdir):
    if not config:
        log.info('no inputs')
        return

    metadata = fetch(config, pkgdir)

    packages, batch_packages = [], {}
    for pkg in metadata.packages.values():
        if hasattr(pkg, 'resolve_all'):
            batch_packages.setdefault(type(pkg), []).append(pkg)
        else:
            packages.append(pkg)

    for t, pkgs in batch_packages.items():
        try:
            t.resolve_all(metadata, pkgs)
        except Exception:
            for i in pkgs:
                i.clean_post(metadata, None, quiet=True)
            metadata.save()
            raise

    for pkg in packages:
        try:
            # Ensure metadata is up-to-date for packages that need it.
            if pkg.needs_dependencies:
                metadata.save()
            pkg.resolve(metadata)
        except Exception:
            pkg.clean_post(metadata, None, quiet=True)
            metadata.save()
            raise

    metadata.save()


def deploy(pkgdir):
    log.LogFile.clean_logs(pkgdir, kind='deploy')
    metadata = Metadata.load(pkgdir)

    packages, batch_packages = [], {}
    for pkg in metadata.packages.values():
        if not pkg.resolved:
            raise ValueError('package {!r} has not been resolved successfully'
                             .format(pkg.name))
        if hasattr(pkg, 'deploy_all'):
            batch_packages.setdefault(type(pkg), []).append(pkg)
        else:
            packages.append(pkg)

    for t, pkgs in batch_packages.items():
        t.deploy_all(metadata, pkgs)
    for pkg in packages:
        pkg.deploy(metadata)


def usage(pkgdir, name, submodules=None, strict=False):
    metadata = Metadata.try_load(pkgdir, strict)
    package = metadata.get_package(name)
    return package.get_usage(metadata, submodules)


def list_files(pkgdir, implicit=False, strict=False):
    metadata = Metadata.try_load(pkgdir, strict)
    if implicit:
        return metadata.files + metadata.implicit_files
    return metadata.files


def list_packages(pkgdir, flat=False):
    metadata = Metadata.load(pkgdir)

    if flat:
        return [PackageTreeItem(pkg, pkg.version(metadata)) for pkg in
                metadata.packages.values()]

    packages = []
    pending = {}
    for pkg in metadata.packages.values():
        item = PackageTreeItem(pkg, pkg.version(metadata),
                               pending.pop(pkg.name, None))
        if pkg.parent:
            pending.setdefault(pkg.parent, []).append(item)
        else:
            packages.append(item)
    return packages
