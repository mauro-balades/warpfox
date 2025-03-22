from collections.abc import Iterable, Mapping, Sequence

__all__ = ['isiterable', 'ismapping', 'issequence', 'iterate', 'iteritems',
           'listify', 'list_view', 'merge_dicts', 'merge_into_dict', 'uniques']


def isiterable(thing):
    return (isinstance(thing, Iterable) and not isinstance(thing, str) and
            not ismapping(thing))


def issequence(thing):
    return isinstance(thing, Sequence) and not isinstance(thing, str)


def ismapping(thing):
    return isinstance(thing, Mapping)


def iterate(thing):
    def generate_none():
        return iter(())

    def generate_one(x):
        yield x

    if thing is None:
        return generate_none()
    elif isiterable(thing):
        return iter(thing)
    else:
        return generate_one(thing)


def iteritems(iterable):
    if ismapping(iterable):
        return iterable.items()
    return enumerate(iterable)


def listify(thing, always_copy=False, scalar_ok=True, type=list):
    if not always_copy and isinstance(thing, type):
        return thing
    if scalar_ok:
        thing = iterate(thing)
    elif not isiterable(thing):
        raise TypeError('expected an iterable')
    return type(thing)


def each_attr(iterable, attr):
    for i in iterable:
        try:
            yield getattr(i, attr)
        except AttributeError:
            pass


def flatten(iterables, type=list):
    result = type()
    for i in iterables:
        result.extend(i)
    return result


def uniques(iterable):
    def generate_uniques(iterable):
        seen = set()
        for item in iterable:
            if item not in seen:
                seen.add(item)
                yield item
    return list(generate_uniques(iterable))


class list_view(Sequence):
    def __init__(self, container, start=None, stop=None):
        length = len(container)

        def clamp(n):
            return max(0, min(n, length))

        start = 0 if start is None else clamp(start)
        stop = length if stop is None else clamp(stop)

        if isinstance(container, list_view):
            self.data = container.data
            self.start = container.start + start
            self.stop = container.start + stop
        else:
            self.data = container
            self.start = start
            self.stop = stop

    def __getitem__(self, i):
        if isinstance(i, slice):
            if i.step != 1 and i.step is not None:
                raise ValueError(i)
            return list_view(self, i.start, i.stop)

        if i < 0 or i >= len(self):
            raise IndexError(i)
        return self.data[self.start + i]

    def __len__(self):
        return self.stop - self.start

    def split_at(self, i):
        return list_view(self, 0, i), list_view(self, i)


def merge_into_dict(dst, *args):
    for d in args:
        for k, v in d.items():
            curr = dst.get(k)
            if ismapping(v):
                if curr is None:
                    dst[k] = dict(v)
                elif ismapping(curr):
                    merge_into_dict(curr, v)
                else:
                    raise TypeError('type mismatch for {}'.format(k))
            elif isiterable(v):
                if curr is None:
                    dst[k] = type(v)(v)
                elif isiterable(curr):
                    curr.extend(v)
                else:
                    raise TypeError('type mismatch for {}'.format(k))
            elif v is not None:
                if curr is not None and isiterable(curr) or ismapping(curr):
                    raise TypeError('type mismatch for {}'.format(k))
                dst[k] = v
            elif k not in dst:
                dst[k] = None  # v is always None here


def merge_dicts(*args):
    dst = {}
    merge_into_dict(dst, *args)
    return dst


def slice_dict(d, keys):
    result = {}
    for k in keys:
        if k in d:
            result[k] = d.pop(k)
    return result
