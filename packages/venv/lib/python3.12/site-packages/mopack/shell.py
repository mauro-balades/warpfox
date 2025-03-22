import os
import re
from collections.abc import MutableSequence
from enum import Enum
from itertools import chain
from shlex import shlex

from .freezedried import auto_dehydrate
from .iterutils import isiterable, ismapping
from .path import Path
from .placeholder import PlaceholderString
from .platforms import platform_name


_Token = Enum('Token', ['char', 'quote', 'space'])
_State = Enum('State', ['between', 'char', 'word', 'quoted'])

_bad_posix_chars = re.compile(r'[^\w@%+=:,./-]')
# XXX: We need a way to escape cmd.exe-specific characters.
_bad_windows_chars = re.compile(r'(\s|["&<>|]|\\$)')
_windows_replace = re.compile(r'(\\*)("|$)')


def split_paths(s, sep=os.pathsep):
    if s is None:
        return []
    return [i for i in s.split(sep) if i]


def join_paths(paths, sep=os.pathsep):
    return sep.join(paths)


def quote_posix(s, force=False):
    if not isinstance(s, str):
        raise TypeError(type(s))

    if s == '':
        return "''"
    elif _bad_posix_chars.search(s):
        def q(has_quote):
            return '' if has_quote else "'"
        s = s.replace("'", r"'\''")

        # Any string less than 3 characters long can't have escaped quotes.
        if len(s) < 3:
            return "'" + s + "'"

        start = 1 if s[0] == "'" else None
        # We can guarantee that any single-quotes at the end are unescaped, so
        # we can deduplicate them if so.
        end = -1 if s[-1] == "'" else None
        return q(start) + s[start:end] + q(end)
    elif force:
        return "'" + s + "'"
    else:
        return s


def quote_windows(s, force=False, escape_percent=False):
    if not isinstance(s, str):
        raise TypeError(type(s))

    if s == '':
        return '""'

    # In some contexts (mainly certain uses of the Windows shell), we want to
    # escape percent signs. This doesn't count as "escaping" for the purposes
    # of quoting the result though.
    if escape_percent:
        s = s.replace('%', '%%')

    if _bad_windows_chars.search(s):
        def repl(m):
            quote = '\\' + m.group(2) if len(m.group(2)) else ''
            return m.group(1) * 2 + quote
        # We can guarantee that any double-quotes are escaped, so we don't need
        # to worry about duplicates if they're at the end.
        return '"' + _windows_replace.sub(repl, s) + '"'
    elif force:
        return '"' + s + '"'
    else:
        return s


def quote_native(s, force=False):
    if platform_name() == 'windows':
        return quote_windows(s, force)
    return quote_posix(s, force)


def split_posix_str(s, type=list, escapes=False):
    if not isinstance(s, str):
        raise TypeError('expected a string')
    lexer = shlex(s, posix=True)
    lexer.commenters = ''
    if not escapes:
        lexer.escape = ''
    lexer.whitespace_split = True
    return type(lexer)


def _tokenize_windows(s):
    escapes = 0
    for c in s:
        if c == '\\':
            escapes += 1
        elif c == '"':
            for i in range(escapes // 2):
                yield (_Token.char, type(s)('\\'))
            yield (_Token.char, '"') if escapes % 2 else (_Token.quote, None)
            escapes = 0
        else:
            for i in range(escapes):
                yield (_Token.char, type(s)('\\'))
            yield ((_Token.space if c in ' \t' else _Token.char), c)
            escapes = 0


def split_windows_str(s, type=list):
    if not isinstance(s, str):
        raise TypeError('expected a string')

    mutable = isinstance(type, MutableSequence)
    state = _State.between
    args = (type if mutable else list)()

    for tok, value in _tokenize_windows(s):
        if state == _State.between:
            if tok == _Token.char:
                args.append(value)
                state = _State.word
            elif tok == _Token.quote:
                args.append('')
                state = _State.quoted
        elif state == _State.word:
            if tok == _Token.quote:
                state = _State.quoted
            elif tok == _Token.char:
                args[-1] += value
            else:  # tok == _Token.space
                state = _State.between
        else:  # state == _State.quoted
            if tok == _Token.quote:
                state = _State.word
            else:
                args[-1] += value

    return args if mutable else type(args)


def split_native_str(s, type=list):
    if platform_name() == 'windows':
        return split_windows_str(s, type)
    return split_posix_str(s, type)


class ShellArguments(MutableSequence):
    def __init__(self, args=[]):
        self._args = list(args)

    def __getitem__(self, i):
        return self._args[i]

    def __setitem__(self, i, value):
        self._args[i] = value

    def __delitem__(self, i):
        del self._args[i]

    def __len__(self):
        return len(self._args)

    def insert(self, i, value):
        return self._args.insert(i, value)

    @staticmethod
    def _fill_identity(s, orig):
        return s

    def fill(self, _fn=None, **kwargs):
        if _fn is None:
            _fn = self._fill_identity

        result = []
        for i in self._args:
            if isinstance(i, Path):
                result.append(_fn(i.string(**kwargs), i))
            elif isiterable(i):
                arg = ''
                for j in i:
                    s = j.string(**kwargs) if isinstance(j, Path) else j
                    arg += _fn(s, j)
                result.append(arg)
            else:
                result.append(_fn(i, i))
        return result

    def dehydrate(self):
        def dehydrate_each(value):
            if isiterable(value):
                return [auto_dehydrate(i) for i in value]
            return auto_dehydrate(value)

        return [dehydrate_each(i) for i in self]

    @classmethod
    def rehydrate(self, value, **kwargs):
        def rehydrate_each(value):
            if ismapping(value):
                return Path.rehydrate(value, **kwargs)
            elif isiterable(value):
                return tuple(rehydrate_each(i) for i in value)
            return value

        return ShellArguments(rehydrate_each(i) for i in value)

    def __eq__(self, rhs):
        if not isinstance(rhs, ShellArguments):
            return NotImplemented
        return self._args == rhs._args

    def __add__(self, rhs):
        if not isiterable(rhs):
            return NotImplemented
        return ShellArguments(chain(self._args, iter(rhs)))

    def __radd__(self, lhs):
        if not isiterable(lhs):
            return NotImplemented
        return ShellArguments(chain(iter(lhs), self._args))

    def __repr__(self):
        return '<ShellArguments({})>'.format(repr(self._args)[1:-1])


def _wrap_placeholder(split_fn):
    def wrapped(value, *args, **kwargs):
        if isinstance(value, PlaceholderString):
            stashed, placeholders = value.stash()
            args = split_fn(stashed, *args, **kwargs)
            return ShellArguments(
                PlaceholderString.unstash(i, placeholders).unbox(simplify=True)
                for i in args
            )
        return ShellArguments(split_fn(value, *args, **kwargs))

    return wrapped


split_posix = _wrap_placeholder(split_posix_str)
split_windows = _wrap_placeholder(split_windows_str)
split_native = _wrap_placeholder(split_native_str)
