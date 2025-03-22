import os
import functools
import json
import sys

from . import arguments, commands, config, log, yaml_tools
from .app_version import version
from .environment import nested_invoke
from .types import dependency

logger = log.getLogger(__name__)

description = """
mopack ("multiple-origin package manager") is a tool providing a unified means
of defining package dependencies across multiple package managers, including
using tarballs directly.
"""

resolve_desc = """
Fetch dependencies from their origins and prepare them for use by the current
project (e.g. by building them).
"""

usage_desc = """
Retrieve information about how to use a dependency. This returns metadata in
YAML format (or JSON if `--json` is passed) pointing to a pkg-config .pc file.
"""

deploy_desc = """
Copy the project's dependencies to an installation directory (e.g. as part of
running a command like `make install`).
"""

clean_desc = """
Clean the `mopack` package directory of all files.
"""

list_files_desc = """
List all the input files used by the current configuration.
"""

list_packages_desc = """
List all the package dependencies.
"""

generate_completion_desc = """
Generate shell-completion functions for mopack and write them to standard
output. This requires the Python package `shtab`.
"""


@functools.wraps(dependency)
def dependency_type(s):
    return dependency(None, s)


def resolve(parser, args):
    if os.environ.get(nested_invoke):
        return 3

    config_data = config.Config(args.file, args.options, args.deploy_dirs)
    os.environ[nested_invoke] = args.directory
    commands.resolve(config_data, commands.get_package_dir(args.directory))


def usage(parser, args):
    directory = os.environ.get(nested_invoke, args.directory)
    try:
        usage = commands.usage(commands.get_package_dir(directory),
                               *args.dependency, strict=args.strict)
    except Exception as e:
        if not args.json:
            raise
        print(json.dumps({'error': str(e)}))
        return 1

    if args.json:
        print(json.dumps(usage))
    else:
        print(yaml_tools.dump(usage))


def deploy(parser, args):
    assert nested_invoke not in os.environ
    commands.deploy(commands.get_package_dir(args.directory))


def clean(parser, args):
    assert nested_invoke not in os.environ
    commands.clean(commands.get_package_dir(args.directory))


def list_files(parser, args):
    assert nested_invoke not in os.environ
    files = commands.list_files(commands.get_package_dir(args.directory),
                                args.include_implicit, args.strict)

    if args.json:
        print(json.dumps(files))
    else:
        for i in files:
            print(i)


def list_packages(parser, args):
    pkg_fmt = ('\033[1;34m{package.name}\033[0m {version}' +
               '(\033[33m{package.origin}\033[0m)')
    try:
        # Try to encode a Unicode box drawing character; if we fail, use ASCII.
        '┼'.encode(sys.stdout.encoding)
        lines = ('│  ', '├─ ')
        lines_last = ('   ', '└─ ')
    except UnicodeEncodeError:
        lines = ('|  ', '+- ')
        lines_last = ('   ', '+- ')

    def get_version(p):
        return '\033[32m{}\033[0m '.format(p.version) if p.version else ''

    def list_level(pkgs, prefix=''):
        for i, p in enumerate(pkgs):
            next_prefix, hline = lines if i < len(pkgs) - 1 else lines_last
            print(('{prefix}{hline}' + pkg_fmt).format(
                prefix=prefix, hline=hline, package=p.package,
                version=get_version(p)
            ))

            list_level(p.children, prefix + next_prefix)

    packages = commands.list_packages(commands.get_package_dir(args.directory),
                                      args.flat)
    if args.flat:
        for p in packages:
            print(pkg_fmt.format(package=p.package, version=get_version(p)))
    else:
        list_level(packages)


def help(parser, args):
    parser.parse_args(args.subcommand + ['--help'])


def generate_completion(parser, args):
    try:
        import shtab
        print(shtab.complete(parser, shell=args.shell))
    except ImportError:  # pragma: no cover
        print('shtab not found; install via `pip install shtab`')
        return 1


def main():
    parser = arguments.ArgumentParser(prog='mopack', description=description)
    parser.add_argument('--version', action='version',
                        version='%(prog)s ' + version)
    parser.add_argument('--verbose', action='store_true',
                        help='show verbose output')
    parser.add_argument('--debug', action='store_true',
                        help=arguments.SUPPRESS)
    parser.add_argument('--color', metavar='WHEN',
                        choices=['always', 'never', 'auto'], default='auto',
                        help=('show colored output (one of: %(choices)s; ' +
                              'default: %(default)s)'))
    parser.add_argument('-c', action='store_const', const='always',
                        dest='color',
                        help=('show colored output (equivalent to ' +
                              '`--color=always`)'))
    parser.add_argument('--warn-once', action='store_true',
                        help='only emit a given warning once')

    subparsers = parser.add_subparsers(metavar='COMMAND')
    subparsers.required = True

    resolve_p = subparsers.add_parser(
        'resolve', description=resolve_desc,
        help='fetch and build package dependencies'
    )
    resolve_p.set_defaults(func=resolve)
    resolve_p.add_argument('--directory', default='.', type=os.path.abspath,
                           metavar='DIR', complete='directory',
                           help='directory to store local package data in')
    resolve_p.add_argument('-d', '--deploy-dir',
                           action=arguments.KeyValueAction,
                           dest='deploy_dirs', metavar='KIND=DIR',
                           help='directories to deploy packages to')
    resolve_p.add_argument('-o', '--option',
                           action=arguments.ConfigOptionAction,
                           dest='options', metavar='OPTION=VALUE',
                           help='additional common options')
    resolve_p.add_argument('-O', '--origin-option',
                           action=arguments.ConfigOptionAction,
                           key=['origins'], dest='options',
                           metavar='OPTION=VALUE',
                           help='additional origin options')
    resolve_p.add_argument('-B', '--builder-option',
                           action=arguments.ConfigOptionAction,
                           key=['builders'], dest='options',
                           metavar='OPTION=VALUE',
                           help='additional builder options')
    resolve_p.add_argument('--strict', action=arguments.ConfigOptionAction,
                           key=['strict'], const=True, dest='options',
                           help=('return an error during usage if package ' +
                                 'is not defined'))
    resolve_p.add_argument('file', nargs='+', metavar='FILE', complete='file',
                           help='the mopack configuration files')
    # TODO: Remove these after v0.1 is released.
    resolve_p.add_argument('-P', '--deploy-path',
                           action=arguments.KeyValueAction,
                           dest='deploy_dirs', help=arguments.SUPPRESS)
    resolve_p.add_argument('-S', '--source-option',
                           action=arguments.ConfigOptionAction,
                           key=['origins'], dest='options',
                           help=arguments.SUPPRESS)

    usage_p = subparsers.add_parser(
        'usage', description=usage_desc,
        help='retrieve usage info for a package'
    )
    usage_p.set_defaults(func=usage)
    usage_p.add_argument('--directory', default='.', type=os.path.abspath,
                         metavar='PATH', complete='directory',
                         help='directory storing local package data')
    usage_p.add_argument('--json', action='store_true',
                         help='display results as JSON')
    usage_p.add_argument('--strict', action='store_true',
                         help='return an error if package is not defined')
    usage_p.add_argument('dependency', type=dependency_type,
                         metavar='DEPENDENCY',
                         help='the name of the dependency to query')

    deploy_p = subparsers.add_parser(
        'deploy', description=deploy_desc, help='deploy packages'
    )
    deploy_p.set_defaults(func=deploy)
    deploy_p.add_argument('--directory', default='.', type=os.path.abspath,
                          metavar='PATH', complete='directory',
                          help='directory storing local package data')

    clean_p = subparsers.add_parser(
        'clean', description=clean_desc, help='clean package directory'
    )
    clean_p.set_defaults(func=clean)
    clean_p.add_argument('--directory', default='.', type=os.path.abspath,
                         metavar='PATH', complete='directory',
                         help='directory storing local package data')

    list_files_p = subparsers.add_parser(
        'list-files', description=list_files_desc, help='list input files'
    )
    list_files_p.set_defaults(func=list_files)
    list_files_p.add_argument('--directory', default='.', type=os.path.abspath,
                              metavar='PATH', complete='directory',
                              help='directory storing local package data')
    list_files_p.add_argument('-I', '--include-implicit', action='store_true',
                              help='include implicit input files')
    list_files_p.add_argument('--json', action='store_true',
                              help='display results as JSON')
    list_files_p.add_argument('--strict', action='store_true',
                              help=('return an error if package directory ' +
                                    'does not exist'))

    list_packages_p = subparsers.add_parser(
        'list-packages', aliases=['ls'], description=list_packages_desc,
        help='list packages'
    )
    list_packages_p.set_defaults(func=list_packages)
    list_packages_p.add_argument('--directory', default='.',
                                 type=os.path.abspath, metavar='PATH',
                                 complete='directory',
                                 help='directory storing local package data')
    list_packages_p.add_argument('--flat', action='store_true',
                                 help='list packages without hierarchy')

    help_p = subparsers.add_parser(
        'help', help='show this help message and exit', add_help=False
    )
    help_p.set_defaults(func=help)
    help_p.add_argument('subcommand', metavar='CMD', nargs=arguments.REMAINDER,
                        help='subcommand to request help for')

    completion_p = subparsers.add_parser(
        'generate-completion', description=generate_completion_desc,
        help='print shell completion script'
    )
    completion_p.set_defaults(func=generate_completion)
    shell = (os.path.basename(os.environ['SHELL'])
             if 'SHELL' in os.environ else None)
    completion_p.add_argument('-s', '--shell', metavar='SHELL', default=shell,
                              help='shell type (default: %(default)s)')

    args = parser.parse_args()
    log.init(args.color, debug=args.debug, verbose=args.verbose,
             warn_once=args.warn_once)

    try:
        return args.func(parser, args)
    except Exception as e:
        logger.exception(e)
        return 1
