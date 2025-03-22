import re

from . import iterutils


class PlaceholderValue:
    def __init__(self, value):
        self.value = value

    def __eq__(self, rhs):
        if not isinstance(rhs, PlaceholderValue):
            return NotImplemented
        return self.value == rhs.value

    def __str__(self):
        raise NotImplementedError('{} cannot be converted to str'
                                  .format(type(self).__name__))

    def __repr__(self):
        return '@({!r})'.format(self.value)


class PlaceholderString:
    def __init__(self, *args):
        self.__bits = tuple(self.__canonicalize(args))

    @staticmethod
    def __canonicalize(value):
        def flatten_bits(value):
            for i in value:
                if isinstance(i, PlaceholderString):
                    yield from i.bits
                elif isinstance(i, (str, PlaceholderValue)):
                    yield i
                else:  # pragma: no cover
                    raise TypeError(type(i))

        bits = flatten_bits(value)
        try:
            last = next(bits)
        except StopIteration:
            return

        for i in bits:
            if isinstance(last, str) and isinstance(i, str):
                last += i
            else:
                yield last
                last = i
        yield last

    @classmethod
    def make(cls, *args, simplify=False):
        result = PlaceholderString(*args)
        if simplify:
            if len(result.bits) == 0:
                return ''
            elif len(result.bits) == 1 and isinstance(result.bits[0], str):
                return result.bits[0]
        return result

    @property
    def bits(self):
        return self.__bits

    def unbox(self, simplify=False):
        if simplify:
            if len(self.bits) == 0:
                return ''
            elif len(self.bits) == 1:
                if isinstance(self.bits[0], PlaceholderValue):
                    return self.bits[0].value
                return self.bits[0]
        return tuple(i.value if isinstance(i, PlaceholderValue) else i
                     for i in self.__bits)

    def replace(self, placeholder, value, *, simplify=False):
        def each(i):
            if isinstance(i, PlaceholderValue) and i.value == placeholder:
                return value
            return i
        return self.make(*[each(i) for i in self.bits], simplify=simplify)

    def stash(self):
        stashed = ''
        placeholders = []
        for i in self.bits:
            if isinstance(i, PlaceholderValue):
                stashed += '\x11{}\x13'.format(len(placeholders))
                placeholders.append(i)
            else:
                stashed += i.replace('\x11', '\x11\x13')
        return stashed, placeholders

    @classmethod
    def unstash(cls, string, placeholders):
        bits = []
        last = 0
        for m in re.finditer('\x11([^\x11]*)\x13', string):
            if m.start() > last:
                bits.append(string[last:m.start()])
            if len(m.group(1)):
                bits.append(placeholders[int(m.group(1))])
            else:
                bits.append('\x11')
            last = m.end()
        if last < len(string):
            bits.append(string[last:])

        return PlaceholderString(*bits)

    def __add__(self, rhs):
        return PlaceholderString(self, rhs)

    def __radd__(self, lhs):
        return PlaceholderString(lhs, self)

    def __eq__(self, rhs):
        if not isinstance(rhs, PlaceholderString):
            return NotImplemented
        return self.__bits == rhs.__bits

    def __str__(self):
        raise NotImplementedError('{} cannot be converted to str'
                                  .format(type(self).__name__))

    def __repr__(self):
        return '|{}|'.format(', '.join(repr(i) for i in self.bits))


def placeholder(value):
    return PlaceholderString(PlaceholderValue(value))


def map_placeholder(value, fn):
    if iterutils.issequence(value):
        return [map_placeholder(i, fn) for i in value]
    elif iterutils.ismapping(value):
        return {k: map_placeholder(v, fn) for k, v in value.items()}
    elif isinstance(value, PlaceholderString):
        return fn(value)
    else:
        return value
