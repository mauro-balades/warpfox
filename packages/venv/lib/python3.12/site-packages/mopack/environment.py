import os
import re
import subprocess
from collections import ChainMap

from .iterutils import isiterable, listify
from .platforms import platform_name
from .shell import split_native_str

# This environment variable is set to the top builddir when `mopack resolve` is
# executed so that nested invocations of `mopack` consistently point to the
# same mopack directory.
nested_invoke = 'MOPACK_NESTED_INVOCATION'


def split_paths(s, sep=os.pathsep):
    if not s:
        return []
    return s.split(sep)


def which(names, env=os.environ, resolve=False, kind='executable'):
    names = listify(names)
    if len(names) == 0:
        raise TypeError('must supply at least one name')

    paths = split_paths(env.get('PATH', os.defpath))
    exts = ['']
    # XXX: Improve this when we have richer platform info (see bfg9000).
    if platform_name() == 'windows':
        exts.extend(split_paths(env.get('PATHEXT', '')))

    for name in names:
        name = split_native_str(name) if not isiterable(name) else name
        if os.path.isabs(name[0]):
            fullpaths = [name[0]]
        else:
            search = ['.'] if os.path.dirname(name[0]) else paths
            fullpaths = [os.path.normpath(os.path.join(path, name[0]))
                         for path in search]

        for fullpath in fullpaths:
            for ext in exts:
                withext = fullpath + ext
                if os.path.exists(withext):
                    return [withext] + name[1:] if resolve else name

    raise IOError('unable to find {kind}{filler} {names}'.format(
        kind=kind, filler='; tried' if len(names) > 1 else '',
        names=', '.join('{!r}'.format(i) for i in names)
    ))


def get_cmd(env, cmdvar, default):
    return split_native_str(env.get(cmdvar, default))


def subprocess_run(args, *, env, **kwargs):
    if nested_invoke in os.environ:
        override_env = {nested_invoke: os.environ[nested_invoke]}
        env = ChainMap(override_env, env)
    return subprocess.run(args, env=env, **kwargs)


# Make a function to convert between command names for different languages in
# the same family (e.g. # `gcc` => `g++`). If no entry in the mapping matches
# the command, we return None to indicate that the conversion has failed.
# XXX: This is copied from bfg9000 and could probably go in a shared location
# once we have a better idea of what we need to share.
def _make_command_converter(mapping):
    def escape(i):
        if isinstance(i, str):
            return '({})'.format(re.escape(i))
        if i.groups:
            raise re.error('capturing groups not allowed')
        return '({})'.format(i.pattern)

    sub = '|'.join(escape(i[0]) for i in mapping)
    ex = re.compile(r'(?:^|(?<=\W))(?:{})(?:$|(?=\W))'.format(sub))

    def fn(cmd):
        s, n = ex.subn(lambda m: mapping[m.lastindex - 1][1], cmd)
        return s if n > 0 else None

    return fn


_cxx_to_c = _make_command_converter([
    # These are ordered from most- to least-specific; in particular, we want
    # `clang-cl` to stay that way when converted between C and C++ contexts.
    ('clang-cl', 'clang-cl'),
    ('c++', 'cc'),
    ('g++', 'gcc'),
    ('clang++', 'clang'),
    ('cl', 'cl'),
])

_c_to_pkgconf = _make_command_converter([
    (re.compile(r'gcc(?:-[\d.]+)?(?:-(?:posix|win32))?'), 'pkg-config'),
])


def get_c_compiler(env=os.environ):
    cmd = env.get('CC')
    if cmd:
        return split_native_str(cmd)

    candidates = []
    sibling = env.get('OBJC')
    if sibling:
        candidates.append(sibling)

    for i in ['CXX', 'OBJCXX']:
        sibling = env.get(i)
        if sibling:
            cmd = _cxx_to_c(sibling)
            if cmd is not None:
                candidates.append(cmd)

    if candidates:
        try:
            return which(candidates, env)
        except IOError:
            pass
    return None


def get_pkg_config(env=os.environ):
    cmd = env.get('PKG_CONFIG')
    if cmd:
        return split_native_str(cmd)

    sibling = get_c_compiler(env)
    for word in sibling or []:
        guessed_cmd = _c_to_pkgconf(word)
        if guessed_cmd is not None:
            break
    else:
        guessed_cmd = None

    if guessed_cmd is not None:
        try:
            return which(guessed_cmd, env)
        except IOError:
            pass

    # Return the default command candidate.
    return ['pkg-config']
