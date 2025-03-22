# Portions of this code (see below) are forked from PyYAML, available at
# <https://pyyaml.org/>. The following license applies to those portions:
#
# Copyright (c) 2017-2020 Ingy döt Net
# Copyright (c) 2006-2016 Kirill Simonov
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import collections.abc
import io
import json
import warnings
import yaml
from collections import namedtuple
from contextlib import contextmanager
from yaml.error import Mark, MarkedYAMLError
from yaml.loader import SafeLoader
from yaml.nodes import MappingNode, SequenceNode
from yaml.constructor import ConstructorError

from .exceptions import ConfigurationError

__all__ = ['load_file', 'make_parse_error', 'to_parse_error', 'MarkedDict',
           'MarkedJSONEncoder', 'MarkedList', 'MarkedYAMLOffsetError',
           'MarkedYAMLWarning', 'SafeLineLoader', 'YamlParseError']


class MarkedYAMLOffsetError(MarkedYAMLError):
    def __init__(self, context=None, context_range=None, problem=None,
                 problem_range=None, note=None, offset=0):
        self.context = context
        self.context_range = context_range
        self.problem = problem
        self.problem_range = problem_range
        self.note = note
        self.offset = offset

    @property
    def context_mark(self):
        return self.context_range.start

    @property
    def problem_mark(self):
        return self.problem_range.start


class MarkedYAMLWarning(MarkedYAMLError, Warning):
    pass


class YamlParseError(ConfigurationError):
    def __init__(self, message, mark, snippet):
        super().__init__(message)
        self.mark = mark
        self.snippet = snippet

    def __str__(self):
        return (self.args[0] + '\n' +
                str(self.mark) + '\n' +
                '  ' + self.snippet + '\n' +
                ' ' * (self.mark.column + 2) + '^')


def _read_line_for_mark(stream, mark):
    stream.seek(mark.index - mark.column, 0)
    return stream.readline()


def _read_mark_range(stream, start, end):
    stream.seek(start.index, 0)
    return stream.read(end.index - start.index)


def _get_indent_at_mark(stream, mark):
    line = _read_line_for_mark(stream, mark)
    for i, c in enumerate(line):
        if c != ' ':
            return i
    assert False


def _get_line_for_index(s, index):
    newline = '\0\r\n\x85\u2028\u2029'
    start = index
    while start > 0 and s[start - 1] not in newline:
        start -= 1
    end = index
    while end < len(s) and s[end] not in newline:
        end += 1
    return s[start:end]


@contextmanager
def _maybe_open(stream_or_filename, *args, **kwargs):
    if isinstance(stream_or_filename, io.IOBase):
        yield stream_or_filename
    else:
        with open(stream_or_filename, newline='') as f:
            yield f


def make_parse_error(e, stream_or_filename):
    with _maybe_open(stream_or_filename) as f:
        if isinstance(e, MarkedYAMLOffsetError) and e.offset != 0:
            start_mark, end_mark = e.problem_range
            indent = _get_indent_at_mark(f, start_mark)
            data = _read_mark_range(f, start_mark, end_mark)

            mark = _get_offset_mark(data, e.offset, indent)
            if mark.line == 0:
                snippet = _read_line_for_mark(f, start_mark)
                mark = Mark(start_mark.name, start_mark.index + mark.index,
                            start_mark.line, start_mark.column + mark.column,
                            None, None)
            else:
                snippet = _get_line_for_index(data, mark.index)
                mark = Mark(start_mark.name, start_mark.index + mark.index,
                            start_mark.line + mark.line, mark.column,
                            None, None)
        else:
            mark = e.problem_mark
            snippet = _read_line_for_mark(f, mark)

    return YamlParseError(e.problem, mark, snippet.rstrip())


@contextmanager
def to_parse_warning(stream_or_filename):
    original = warnings.showwarning

    def showwarning(message, *args, **kwargs):
        if isinstance(message, MarkedYAMLWarning):
            with _maybe_open(stream_or_filename) as f:
                message = UserWarning(make_parse_error(message, f))
        return original(message, *args, **kwargs)

    warnings.showwarning = showwarning
    try:
        yield
    finally:
        warnings.showwarning = original


@contextmanager
def to_parse_error(filename):
    with to_parse_warning(filename):
        try:
            yield
        except MarkedYAMLError as e:
            raise make_parse_error(e, filename)


@contextmanager
def load_file(filename, Loader=SafeLoader):
    with open(filename, newline='') as f, \
         to_parse_warning(f):
        try:
            yield yaml.load(f, Loader=Loader)
        except MarkedYAMLError as e:
            raise make_parse_error(e, f)


def dump(data):
    # `sort_keys` only works on newer versions of PyYAML, so don't worry too
    # much if we can't use it.
    try:
        return yaml.dump(data, sort_keys=False)
    except TypeError:  # pragma: no cover
        return yaml.dump(data)


class MarkRange(namedtuple('MarkRange', ['start', 'end'])):
    def __new__(self, node):
        return super().__new__(self, node.start_mark, node.end_mark)


class MarkedCollection:
    def __init__(self, data, mark, marks):
        self.data = data
        self.mark = mark
        self.marks = marks

    def __getitem__(self, index):
        return self.data[index]

    def __setitem__(self, index, value):
        self.data[index] = value

    def __len__(self):
        return len(self.data)

    def __iter__(self):
        return iter(self.data)

    def __repr__(self):
        return repr(self.data)

    def __eq__(self, rhs):
        if isinstance(rhs, MarkedCollection):
            return self.data == rhs.data
        return self.data == rhs


class MarkedList(MarkedCollection, collections.abc.Sequence):
    def __init__(self, mark=None):
        super().__init__([], mark, [])

    def _extend_marks(self, rhs):
        if isinstance(rhs, MarkedCollection):
            if self.mark is None:
                self.mark = rhs.mark
            self.marks.extend(rhs.marks)
        else:
            for i in range(len(self.marks), len(self.data)):
                self.marks.append(None)

    @property
    def value_marks(self):
        return self.marks

    def append(self, value, mark=None):
        assert len(self.data) == len(self.marks)
        self.data.append(value)
        self.marks.append(mark)

    def extend(self, rhs):
        assert len(self.data) == len(self.marks)
        self.data.extend(rhs)
        self._extend_marks(rhs)

    def copy(self):
        result = MarkedList()
        result.extend(self)
        return result

    def __copy__(self):
        return self.copy()

    def __deepcopy__(self, memo):
        import copy
        result = MarkedList()
        result.data.extend(copy.deepcopy(i, memo) for i in self)
        result._extend_marks(self)
        return result


class MarkedDict(MarkedCollection, collections.abc.Mapping):
    def __init__(self, mark=None):
        super().__init__({}, mark, {})
        self.value_marks = {}

    def _update_marks(self, rhs):
        if isinstance(rhs, MarkedDict):
            if self.mark is None:
                self.mark = rhs.mark
            self.marks.update(rhs.marks)
            self.value_marks.update(rhs.value_marks)
        else:
            for k in self.data:
                if k not in self.marks:
                    self.marks[k] = self.value_marks[k] = None

    def add(self, key, value, key_mark=None, value_mark=None):
        self.data[key] = value
        if key_mark is not None:
            self.marks[key] = key_mark
        if value_mark is not None:
            self.value_marks[key] = value_mark

    def pop(self, key, *args):
        result = self.data.pop(key, *args)
        self.marks.pop(key, None)
        self.value_marks.pop(key, None)
        return result

    def update(self, *args, **kwargs):
        self.data.update(*args, **kwargs)
        if len(args):
            self._update_marks(args[0])

    def copy(self):
        result = MarkedDict()
        result.update(self)
        return result

    def __copy__(self):
        return self.copy()

    def __deepcopy__(self, memo):
        import copy
        result = MarkedDict()
        result.data.update({copy.deepcopy(k, memo): copy.deepcopy(v, memo)
                            for k, v in self.items()})
        result._update_marks(self)
        return result


class MarkedJSONEncoder(json.JSONEncoder):
    def default(self, thing):
        if isinstance(thing, MarkedList):
            return list(thing)
        elif isinstance(thing, MarkedDict):
            return dict(thing)
        return super().default(thing)


class SafeLineLoader(SafeLoader):
    def construct_yaml_seq(self, node):
        data = MarkedList()
        yield data
        data.extend(self.construct_sequence(node))

    def construct_yaml_map(self, node):
        data = MarkedDict()
        yield data
        data.update(self.construct_mapping(node))

    def construct_sequence(self, node, deep=False):
        if not isinstance(node, SequenceNode):  # pragma: no cover
            raise ConstructorError(
                None, None, 'expected a sequence node, but found %s' % node.id,
                node.start_mark
            )
        sequence = MarkedList(MarkRange(node))
        for child_node in node.value:
            sequence.append(self.construct_object(child_node, deep=deep),
                            MarkRange(child_node))
        return sequence

    def construct_mapping(self, node, deep=False):
        if not isinstance(node, MappingNode):  # pragma: no cover
            raise ConstructorError(
                None, None, 'expected a mapping node, but found %s' % node.id,
                node.start_mark
            )
        self.flatten_mapping(node)
        mapping = MarkedDict(MarkRange(node))
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(
                key, collections.abc.Hashable
            ):  # pragma: no cover
                raise ConstructorError(
                    'while constructing a mapping', node.start_mark,
                    'found unhashable key', key_node.start_mark
                )
            value = self.construct_object(value_node, deep=deep)
            mapping.add(key, value, MarkRange(key_node), MarkRange(value_node))
        return mapping


SafeLineLoader.add_constructor('tag:yaml.org,2002:seq',
                               SafeLineLoader.construct_yaml_seq)
SafeLineLoader.add_constructor('tag:yaml.org,2002:map',
                               SafeLineLoader.construct_yaml_map)


# /!\ Hack Alert /!\
#
# This code is forked from PyYAML and allows us to read a YAML scalar up to a
# particular offset in the parsed representation, and then return the Mark
# object pointing to where that offset occurs in the raw YAML data. This makes
# it possible to report syntax errors in mopack's mini-expression language with
# the correct offsets.
#
# Starting here, the following code is dual-licensed under the BSD 3-clause
# license and PyYAML's MIT license as described above.


def _get_offset_mark(data, offset, indent=0, Loader=SafeLoader):
    loader = Loader(data)
    loader.indent = indent

    ch = loader.peek()
    if ch == '&':
        loader.fetch_anchor()
        loader.scan_to_next_token()
        ch = loader.peek()

    if ch in ('|', '>'):
        return _scan_block_scalar(loader, ch, offset)
    if ch in ("'", '"'):
        return _scan_flow_scalar(loader, ch, offset)
    if loader.check_plain():
        return _scan_plain(loader, offset)
    assert False


def _scan_block_scalar(loader, style, offset):
    folded = bool(style == '>')
    start_mark = loader.get_mark()

    # Scan the header.
    loader.forward()
    chomping, increment = loader.scan_block_scalar_indicators(start_mark)
    loader.scan_block_scalar_ignored_line(start_mark)

    # Determine the indentation level and go to the first non-empty line.
    min_indent = loader.indent + 1
    if min_indent < 1:  # pragma: no cover
        min_indent = 1
    if increment is None:
        breaks, max_indent, end_mark = loader.scan_block_scalar_indentation()
        indent = max(min_indent, max_indent)
    else:
        indent = min_indent + increment - 1
        breaks, end_mark = loader.scan_block_scalar_breaks(indent)
    line_break = ''

    # Scan the inner part of the block scalar.
    while loader.column == indent and loader.peek() != '\0':
        offset -= len(breaks)
        if offset <= 0:
            return loader.get_mark()

        leading_non_space = loader.peek() not in ' \t'
        length = 0
        while loader.peek(length) not in '\0\r\n\x85\u2028\u2029':
            length += 1
            if offset - length <= 0:
                loader.forward(length)
                return loader.get_mark()
        offset -= length
        loader.forward(length)

        line_break = loader.scan_line_break()
        breaks, end_mark = loader.scan_block_scalar_breaks(indent)
        if loader.column == indent and loader.peek() != '\0':
            if ( folded and line_break == '\n' and leading_non_space and
                 loader.peek() not in ' \t' ):
                if not breaks:  # pragma: no branch
                    offset -= 1
            else:
                offset -= len(line_break)
        else:
            break  # pragma: no cover

    return end_mark


def _scan_flow_scalar(loader, style, offset):
    double = bool(style == '"')

    start_mark = loader.get_mark()
    quote = loader.peek()
    loader.forward()

    offset = _scan_flow_scalar_non_spaces(loader, double, start_mark, offset)
    if offset <= 0:
        return loader.get_mark()

    while loader.peek() != quote:
        offset -= len(loader.scan_flow_scalar_spaces(double, start_mark))
        if offset <= 0:
            return loader.get_mark()
        offset = _scan_flow_scalar_non_spaces(loader, double, start_mark,
                                              offset)
        if offset <= 0:
            return loader.get_mark()

    loader.forward()
    return loader.get_mark()


def _scan_flow_scalar_non_spaces(loader, double, start_mark, offset):
    while True:
        if offset <= 0:
            return 0

        length = 0
        while loader.peek(length) not in '\'\"\\\0 \t\r\n\x85\u2028\u2029':
            length += 1
            if offset - length <= 0:
                loader.forward(length)
                return 0
        offset -= length
        loader.forward(length)

        ch = loader.peek()
        if not double and ch == "'" and loader.peek(1) == "'":
            offset -= 1
            loader.forward(2)
        elif (double and ch == "'") or (not double and ch in '"\\'):
            offset -= 1
            loader.forward()
        elif double and ch == '\\':
            offset -= 1
            loader.forward()
            ch = loader.peek()
            if ch in loader.ESCAPE_REPLACEMENTS:
                loader.forward()
            elif ch in loader.ESCAPE_CODES:
                length = loader.ESCAPE_CODES[ch]
                loader.forward(length + 1)
            elif ch in '\r\n\x85\u2028\u2029':
                loader.scan_line_break()
                offset -= len(loader.scan_flow_scalar_breaks(
                    double, start_mark
                ))
            else:
                assert False
        else:
            return offset


def _scan_plain(loader, offset):
    plain_ws = '\0 \t\r\n\x85\u2028\u2029'
    start_mark = loader.get_mark()
    indent = loader.indent + 1
    spaces = []
    while True:
        length = 0
        while True:
            ch = loader.peek(length)
            extra_ws = plain_ws + (',[]{}' if loader.flow_level else '')
            if ( ch in plain_ws or
                 (ch == ':' and loader.peek(length+1) in extra_ws) or
                 (loader.flow_level and ch in ',?[]{}') ):
                break  # pragma: no cover
            length += 1

        loader.allow_simple_key = False
        offset -= len(''.join(spaces))
        if length > offset:
            loader.forward(offset)
            break

        offset -= length
        loader.forward(length)
        spaces = loader.scan_plain_spaces(indent, start_mark)
    return loader.get_mark()
