import copy
import os
import re
from contextlib import contextmanager

from . import expression as expr, iterutils
from .exceptions import ConfigurationError
from .path import Path
from .placeholder import map_placeholder, PlaceholderString
from .shell import ShellArguments, split_posix
from .yaml_tools import MarkedDict, MarkedYAMLOffsetError


_unexpected_kwarg_ex = re.compile(
    r"got an unexpected keyword argument '(\w+)'$"
)

_ssh_ex = re.compile(
    r'^'
    r'(?:[^@:]+?@)?'  # username (optional)
    r'[^:]+:'         # host
    r'.+'             # path
    r'$'
)

_url_ex = re.compile(
    r'^'
    r'[A-Za-z0-9+.-]+://'        # scheme
    r'(?:[^@:]+(?::[^@:]+)?@)?'  # userinfo (optional)
    r'[^:]+'                     # host
    r'(?::\d{1,5})?'             # port (optional)
    r'(?:[/?#].*)?'              # path
    r'$'
)

_dependency_ex = re.compile(
    r'^'
    r'([^,[\]]+)'      # package name
    r'(?:\[('
    r'[^,[\]]+'        # first submodule
    r'(?:,[^,[\]]+)*'  # extra submodules
    r')\])?'
    r'$'
)

_bad_dependency_ex = re.compile(r'[,[\]]')


class FieldError(TypeError, ConfigurationError):
    def __init__(self, message, field, offset=0):
        super().__init__(message)
        self.field = iterutils.listify(field, type=tuple)
        self.offset = offset


class FieldKeyError(FieldError):
    pass


class FieldValueError(FieldError):
    pass


def kwarg_error_to_field_error(e, kind):
    if type(e) == TypeError:
        m = _unexpected_kwarg_ex.search(str(e))
        if m:
            msg = ('{} got an unexpected keyword argument {!r}'
                   .format(kind, m.group(1)))
            return FieldKeyError(msg, m.group(1))
    return e


@contextmanager
def wrap_field_error(field, kind=None):
    try:
        yield
    except TypeError as e:
        e = kwarg_error_to_field_error(e, kind) if kind else e
        if not isinstance(e, FieldError):
            raise e
        new_field = iterutils.listify(field, type=tuple) + e.field
        raise type(e)(str(e), new_field, e.offset)


@contextmanager
def ensure_field_error(field):
    try:
        yield
    except Exception as e:
        if isinstance(e, FieldError):
            raise
        raise FieldValueError(str(e), field)


class _UnsetType:
    def __bool__(self):
        return False

    def __eq__(self, rhs):
        return isinstance(rhs, _UnsetType) or rhs is None

    def dehydrate(self):
        return None

    @classmethod
    def rehydrate(self, value, **kwargs):
        if value is not None:
            raise ValueError('expected None')
        return Unset

    def __repr__(self):
        return '<Unset>'


Unset = _UnsetType()


@contextmanager
def try_load_config(config, context, kind):
    try:
        yield
    except TypeError as e:
        if not isinstance(config, MarkedDict):
            raise

        e = kwarg_error_to_field_error(e, kind)
        msg = str(e)
        mark = config.mark
        offset = 0
        if isinstance(e, FieldError):
            x = config
            for f in e.field[:-1]:
                x = x[f]
            marks = (x.value_marks if isinstance(e, FieldValueError)
                     else x.marks)
            mark = marks[e.field[-1]]
            offset = e.offset

        raise MarkedYAMLOffsetError(context, config.mark, msg, mark,
                                    offset=offset)


class TypeCheck:
    def __init__(self, context, symbols=None, *, dest=None):
        self.__context = context
        self.__symbols = symbols
        self.__dest = context['self'] if dest is None else dest

    def __evaluate(self, field, data, symbols):
        if symbols is None:
            return data

        try:
            with wrap_field_error(field):
                if isinstance(data, str):
                    return expr.evaluate(symbols, data)
                elif (iterutils.issequence(data) or
                      iterutils.ismapping(data)):
                    result = copy.copy(data)
                    for k, v in iterutils.iteritems(result):
                        result[k] = self.__evaluate(k, v, symbols)
                    return result
                return data
        except expr.ParseBaseException as e:
            raise FieldValueError(e.msg, field, e.loc)

    def __call__(self, field, check, *, dest=None, dest_field=None,
                 reducer=None, extra_symbols=None, evaluate=True):
        if dest is None:
            dest = self.__dest
        if dest_field is None:
            dest_field = field

        if extra_symbols is None:
            symbols = self.__symbols
        elif self.__symbols is None:
            symbols = extra_symbols
        else:
            symbols = {**self.__symbols, **extra_symbols}

        value = self.__context[field]
        if evaluate:
            value = self.__evaluate(field, value, symbols)
        value = check(field, value)

        if iterutils.ismapping(dest):
            if reducer:
                value = reducer(dest[dest_field], value)
            dest[dest_field] = value
        else:
            if reducer:
                value = reducer(getattr(dest, dest_field), value)
            setattr(dest, dest_field, value)

    def __getattr__(self, field):
        return lambda *args, **kwargs: self(field, *args, **kwargs)


def maybe(other, default=None, empty=(None, Unset)):
    def check(field, value):
        if any(value is i for i in iterutils.iterate(empty)):
            return default
        return other(field, value)

    return check


def maybe_raw(other, empty=(None, Unset)):
    def check(field, value):
        if any(value is i for i in iterutils.iterate(empty)):
            return value
        return other(field, value)

    return check


def one_of(*args, desc):
    def check(field, value):
        for i in args:
            try:
                return i(field, value)
            except FieldValueError:
                pass
        else:
            raise FieldValueError('expected {}'.format(desc), field)

    return check


def constant(*args):
    def check(field, value):
        if value in args:
            return value
        raise FieldValueError('expected one of {}'.format(
            ', '.join(repr(i) for i in args)
        ), field)

    return check


def list_of(other, listify=False, allow_empty=True):
    def check(field, value):
        if iterutils.isiterable(value):
            with wrap_field_error(field):
                result = [other(i, v) for i, v in enumerate(value)]
        elif listify:
            result = [other(field, value)] if value is not None else []
        else:
            raise FieldValueError('expected a list', field)

        if not allow_empty and len(result) == 0:
            raise FieldValueError('expected a non-empty list', field)
        return result

    return check


def list_of_length(other, length):
    def check(field, value):
        if iterutils.isiterable(value) and len(value) == length:
            with wrap_field_error(field):
                return [other(i, v) for i, v in enumerate(value)]

        raise FieldValueError('expected a list of length {}'.format(length),
                              field)

    return check


def dict_of(key_type, value_type):
    def check_each(value):
        # Do this here instead of a dict comprehension so we can guarantee that
        # `key_type` is called first.
        for k, v in value.items():
            yield key_type(k, k), value_type(k, v)

    def check(field, value):
        if not iterutils.ismapping(value):
            raise FieldValueError('expected a dict', field)
        with wrap_field_error(field):
            return {k: v for k, v in check_each(value)}

    return check


def dict_shape(shape, desc):
    def check_item(value, key, check):
        if key in value:
            return check(key, value[key])
        try:
            return check(key, None)
        except FieldValueError:
            raise FieldValueError('expected {}'.format(desc), ())

    def check(field, value):
        if not iterutils.ismapping(value):
            raise FieldValueError('expected {}'.format(desc), field)
        with wrap_field_error(field):
            for k in value:
                if k not in shape:
                    raise FieldValueError('unexpected key', k)
            return {k: check_item(value, k, sub_check)
                    for k, sub_check in shape.items()}

    return check


def string(field, value):
    if not isinstance(value, str):
        raise FieldValueError('expected a string', field)
    return value


def placeholder_string(field, value):
    if not isinstance(value, (str, PlaceholderString)):
        raise FieldValueError('expected a string', field)
    return value


def boolean(field, value):
    if not isinstance(value, bool):
        raise FieldValueError('expected a boolean', field)
    return value


def path_fragment(field, value):
    value = string(field, value)
    if os.path.isabs(value) or os.path.splitdrive(value)[0]:
        raise FieldValueError('expected a relative path', field)

    value = os.path.normpath(value)
    if value.split(os.path.sep)[0] == os.path.pardir:
        raise FieldValueError('expected an inner path', field)
    return value


def path_string(base):
    def check(field, value):
        return os.path.normpath(os.path.join(base, string(field, value)))

    return check


def abs_or_inner_path(base):
    def check(field, value):
        with ensure_field_error(field):
            value = Path.ensure_path(value, base or Path.Base.absolute)
            if not value.is_abs() and not value.is_inner():
                raise FieldValueError('expected an absolute or inner path',
                                      field)
            return value

    return check


def any_path(base):
    def check(field, value):
        with ensure_field_error(field):
            return Path.ensure_path(value, base)

    return check


def ssh_path(field, value):
    value = string(field, value)
    if not _ssh_ex.match(value):
        raise FieldValueError('expected an ssh path', field)
    return value


def url(field, value):
    value = string(field, value)
    if not _url_ex.match(value):
        raise FieldValueError('expected a URL', field)
    return value


def dependency(field, value):
    value = string(field, value)
    m = _dependency_ex.match(value)
    if not m:
        raise FieldValueError('expected a dependency', field)

    package, submodules = m.groups()
    if submodules:
        submodules = submodules.split(',')
    return package, submodules


def dependency_string(package, submodules):
    def check(s):
        if not s or _bad_dependency_ex.search(s):
            raise ValueError('invalid dependency')
        return s

    submodules_str = ','.join(check(i) for i in iterutils.iterate(submodules))
    if submodules_str:
        return '{}[{}]'.format(check(package), submodules_str)
    return check(package)


def shell_args(none_ok=False, escapes=False):
    def check_item(field, value):
        with ensure_field_error(field):
            if isinstance(value, str):
                return value
            elif isinstance(value, PlaceholderString):
                return value.unbox(simplify=True)
            raise TypeError('expected a string')

    def check(field, value):
        if value is None or value is Unset:
            if none_ok:
                return ShellArguments([])
            raise FieldValueError('expected shell arguments', field)

        if iterutils.isiterable(value):
            with wrap_field_error(field):
                return ShellArguments(check_item(i, v) for i, v in
                                      enumerate(value))

        with ensure_field_error(field):
            return split_posix(value, escapes=escapes)

    return check


def placeholder_fill(other, placeholder, fill_value):
    def check(field, value):
        value = map_placeholder(value, lambda value: value.replace(
            placeholder, fill_value, simplify=True
        ))
        return other(field, value)

    return check
