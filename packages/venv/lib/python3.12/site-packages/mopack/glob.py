import fnmatch
import posixpath
import re
from collections import namedtuple
from itertools import zip_longest

from .iterutils import iterate, list_view

__all__ = ['filter_glob', 'Glob']


class Glob:
    _glob_ex = re.compile('([*?[])')
    _glob_run = namedtuple('_glob_bit', ['matchers', 'length'])

    def __init__(self, pattern):
        if pattern == '':
            self._directory = False
            self._glob = [self._glob_run([], 0)]
        else:
            bits = pattern.replace('\\', '/').split(posixpath.sep)
            self._directory = bits[-1] == ''
            if self._directory:
                del bits[-1]

            self._glob = self._compile_glob(bits)

    @classmethod
    def _is_glob(cls, s):
        return bool(cls._glob_ex.search(s))

    @classmethod
    def _compile_glob(cls, bits):
        # Divide our glob into a series of "runs". Each run is a list of
        # "simple" globs to be matched against path components. In between each
        # run is an implicit `**` pattern.
        globs = [[]]

        # Treat a pattern not beginning with `/` as starting with `**` (i.e.
        # it's a relative path, rather than an absolute one).
        starstar = False
        if bits[0] != '':
            starstar = True
            globs.append([])

        for i in bits:
            if i == '**':
                # This line is fully-covered, but coverage.py can't detect it
                # correctly...
                if not starstar:  # pragma: no branch
                    starstar = True
                    globs.append([])
                continue

            starstar = False
            if cls._is_glob(i):
                globs[-1].append(re.compile(fnmatch.translate(i)).match)
            elif i:
                globs[-1].append(cls._match_string(i))

        # Make a list of the remaining *total* lengths for each run of globs.
        # This makes it easier to determine how much "wiggle room" we have for
        # a given run when there are multiple `**` patterns. See also the
        # `_match_glob_runs` method below.
        lengths = [len(i) for i in globs]
        for i in reversed(range(len(lengths) - 1)):
            lengths[i] += lengths[i + 1]
        return [cls._glob_run(i, j) for i, j in zip(globs, lengths)]

    @staticmethod
    def _match_string(s):
        return lambda x: x == s

    def _match_glob_run(self, run, path_bits):
        wanted_bits, next_bits = path_bits.split_at(len(run.matchers))
        for matcher, path_bit in zip_longest(run.matchers, wanted_bits):
            if path_bit is None or not matcher(path_bit):
                # `path` is a parent of or diverges from our pattern.
                return False, next_bits

        return True, next_bits

    def _match_glob_runs(self, runs, path_bits, is_directory):
        if len(runs) == 0:
            # `path` matches our pattern exactly or is a child.
            return True, path_bits
        elif not len(path_bits):
            if is_directory:
                # We have no more matchers in any of our glob runs *and* `path`
                # is a directory, so `path` matches our pattern exactly.
                return runs[0].length == 0, path_bits

            # `path` diverges from our pattern because it's a file and we want
            # a directory here.
            return False, path_bits

        # The current run could start anywhere so long as we have enough path
        # components left to fit all the runs.
        wiggle_room = len(path_bits) - runs[0].length
        for offset in range(wiggle_room + 1):
            result, bits = self._match_glob_run(runs[0], path_bits[offset:])
            if result:
                return self._match_glob_runs(runs[1:], bits, is_directory)
        return False, []

    def match(self, path):
        path_bits = path.replace('\\', '/').split(posixpath.sep)
        is_directory = path_bits[-1] == ''
        if is_directory:
            del path_bits[-1]
        path_bits = list_view(path_bits)

        glob = list_view(self._glob)
        result, path_bits = self._match_glob_run(glob[0], path_bits)
        if not result:
            return result

        if len(glob) > 1:
            result, path_bits = self._match_glob_runs(glob[1:], path_bits,
                                                      is_directory)
            if not result:
                return result

        if len(path_bits):
            # `path` is a child of our pattern.
            return True

        # `path` matches our pattern. Check if it's a directory if needed.
        return is_directory if self._directory else True


def filter_glob(patterns, paths, **kwargs):
    globs = [i if isinstance(i, Glob) else Glob(i) for i in iterate(patterns)]
    for p in paths:
        for g in globs:
            if g.match(p, **kwargs):
                yield p
                break
