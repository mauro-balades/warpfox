import os.path
import tarfile
import zipfile

__all__ = ['Archive', 'open', 'TarArchive', 'ZipArchive']


def _check_safe_path(path):
    if ( os.path.splitdrive(path)[0] or
         os.path.isabs(path) or
         os.path.normpath(path).split(os.path.sep)[0] == '..' ):
        raise ValueError('unsafe path in archive: {!r}'.format(path))


class Archive:
    def __init__(self, archive):
        self._archive = archive

    def __enter__(self):
        self._archive.__enter__()
        return self

    def __exit__(self, type, value, traceback):
        self._archive.__exit__(type, value, traceback)


class TarArchive(Archive):
    def __init__(self, file, mode='r:*'):
        super().__init__(tarfile.open(mode=mode, fileobj=file))
        for i in self._archive.getmembers():
            _check_safe_path(i.name)

    def getnames(self):
        def fixdir(info):
            return info.name + '/' if info.isdir() else info.name

        result = [fixdir(i) for i in self._archive.getmembers()]
        result.sort()
        return result

    def extract(self, member, path='.'):
        return self._archive.extract(member.rstrip('/'), path)

    def extractall(self, path='.', members=None):
        if members:
            members = (self._archive.getmember(i.rstrip('/')) for i in members)
        return self._archive.extractall(path, members)


class ZipArchive(Archive):
    def __init__(self, file, mode='r:*'):
        split_mode = mode.split(':', 1)
        if len(split_mode) == 2 and split_mode[1] not in ('*', 'zip'):
            raise ValueError('unexpected compression mode {!r}'
                             .format(split_mode[1]))

        super().__init__(zipfile.ZipFile(file, split_mode[0]))
        for i in self._archive.namelist():
            _check_safe_path(i)

    def getnames(self):
        result = self._archive.namelist()
        result.sort()
        return result

    def extract(self, member, path='.'):
        return self._archive.extract(member, path)

    def extractall(self, path='.', members=None):
        return self._archive.extractall(path, members)


def open(file, mode='r:*'):
    split_mode = mode.split(':', 1)
    fmt = split_mode[1] if len(split_mode) == 2 else '*'

    if fmt == '*':
        is_zip = zipfile.is_zipfile(file)
        file.seek(0)
        kind = ZipArchive if is_zip else TarArchive
    elif fmt == 'zip':
        kind = ZipArchive
    else:
        kind = TarArchive

    return kind(file, mode)
