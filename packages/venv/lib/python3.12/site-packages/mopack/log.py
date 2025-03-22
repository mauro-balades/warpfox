import colorama
import logging
import os
import shlex
import subprocess
import textwrap
import warnings
from contextlib import contextmanager
from logging import (getLogger, info, debug,  # noqa: F401
                     CRITICAL, ERROR, WARNING, INFO, DEBUG)

from .iterutils import listify
from .environment import subprocess_run

_next_level = INFO + 1


def _make_log_level(name, color):
    global _next_level
    _next_level += 1
    assert _next_level < WARNING
    n = _next_level
    logging.addLevelName(n, name)
    ColoredStreamHandler._format_codes[n] = (color, True)
    return n, lambda package, message=None: log_package(n, package, message)


class ColoredStreamHandler(logging.StreamHandler):
    _width = 9
    _format_codes = {
        DEBUG: ('1;35', False),
        INFO: ('1;34', False),
        WARNING: ('1;33', False),
        ERROR: ('1;31', False),
        CRITICAL: ('1;41;37', False),
    }

    def __init__(self, *args, debug=False, **kwargs):  # noqa: F811
        self.debug = debug
        super().__init__(*args, **kwargs)

    def format(self, record):
        name = record.levelname.lower()
        fmt, indent = self._format_codes.get(record.levelno, ('1', False))
        record.coloredlevel = '{space}\033[{format}m{name}\033[0m'.format(
            space=' ' * (self._width - len(name)) if indent else '',
            format=fmt, name=record.levelname.lower()
        )
        return super().format(record)

    def emit(self, record):
        if not self.debug and record.exc_info:
            record.exc_info = None
        return super().emit(record)


PKG_CLEAN,   pkg_clean   = _make_log_level('clean',   '1;34')
PKG_FETCH,   pkg_fetch   = _make_log_level('fetch',   '1;36')
PKG_PATCH,   pkg_patch   = _make_log_level('patch',   '1;34')
PKG_RESOLVE, pkg_resolve = _make_log_level('resolve', '1;32')
PKG_DEPLOY,  pkg_deploy  = _make_log_level('deploy',  '1;32')


def _clicolor(environ):
    if environ.get('CLICOLOR_FORCE', '0') != '0':
        return 'always'
    if 'CLICOLOR' in environ:
        return 'never' if environ['CLICOLOR'] == '0' else 'auto'
    return None


def _init_logging(logger, debug, stream=None):  # noqa: F811
    logger.setLevel(DEBUG if debug else INFO)

    handler = ColoredStreamHandler(stream, debug=debug)
    fmt = '%(coloredlevel)s: %(message)s'
    handler.setFormatter(logging.Formatter(fmt))
    logger.addHandler(handler)


def init(color='auto', debug=False, verbose=False,  # noqa: F811
         warn_once=False, environ=os.environ):
    color = _clicolor(environ) or color
    if color == 'always':
        colorama.init(strip=False)
    elif color == 'never':
        colorama.init(strip=True, convert=False)
    else:  # color == 'auto'
        colorama.init()

    warnings.filterwarnings('default')
    if warn_once:
        warnings.filterwarnings('once')

    _init_logging(logging.root, debug)
    LogFile.verbose = verbose


def log_package(level, package, message=None):
    final_message = '\033[33m{}\033[0m'.format(package)
    if message:
        final_message += ' ' + message
    logging.log(level, final_message)


def _showwarning(message, category, filename, lineno, file=None, line=None):
    logging.log(WARNING, message)


warnings.showwarning = _showwarning


class LogFile:
    verbose = False

    def __init__(self, file):
        self.file = file

    @staticmethod
    def _logdir(pkgdir, kind=None):
        return os.path.join(pkgdir, 'logs', *listify(kind))

    def _print_verbose(self, message, **kwargs):
        print(message, file=self.file, **kwargs)
        if self.verbose:
            print(textwrap.indent(message, ' ' * 4), **kwargs)

    @classmethod
    def clean_logs(cls, pkgdir, kind=None):
        logdir = cls._logdir(pkgdir, kind)
        if not os.path.exists(logdir):
            return
        for i in os.listdir(logdir):
            if i.endswith('.log'):
                try:
                    os.remove(os.path.join(logdir, i))
                except Exception:  # pragma: no cover
                    pass

    @classmethod
    def open(cls, pkgdir, name, kind=None, mode='a'):
        logdir = cls._logdir(pkgdir, kind)
        os.makedirs(logdir, exist_ok=True)
        logname = os.path.join(logdir, '{}.log'.format(name))
        return cls(open(logname, mode))

    def close(self):
        self.file.close()

    def check_call(self, args, *, env, **kwargs):
        command = ' '.join(shlex.quote(i) for i in args)
        self._print_verbose('$ ' + command, flush=True)
        try:
            result = subprocess_run(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True, check=True, env=env, **kwargs
            )
            self._print_verbose(result.stdout)
        except subprocess.CalledProcessError as e:
            print(e.stdout, file=self.file)
            msg = "Command '{}' returned non-zero exit status {}".format(
                command, e.returncode
            )
            if e.stdout:
                msg += ':\n' + textwrap.indent(e.stdout.rstrip(), '  ')
            raise subprocess.SubprocessError(msg)
        except Exception as e:
            print(str(e), file=self.file)
            raise type(e)("Command '{}' failed:\n{}".format(
                command, textwrap.indent(str(e), '  ')
            ))

    @contextmanager
    def synthetic_command(self, args):
        command = ' '.join(shlex.quote(i) for i in args)
        self._print_verbose('$ ' + command)
        try:
            yield
            self._print_verbose('')
        except Exception as e:
            print(str(e), file=self.file)
            raise type(e)("Command '{}' failed:\n{}".format(
                command, textwrap.indent(str(e), '  ')
            ))

    def __enter__(self):
        self.file.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return self.file.__exit__(exc_type, exc_value, traceback)
