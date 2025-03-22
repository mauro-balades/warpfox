import platform
import subprocess

from .objutils import memoize


@memoize
def platform_name():
    system = platform.system().lower()
    if system.startswith('cygwin'):
        return 'cygwin'
    elif system == 'windows':
        try:
            uname = subprocess.check_output(
                'uname', universal_newlines=True
            ).lower()
            if uname.startswith('cygwin'):
                return 'cygwin'
        except OSError:
            pass

    return system
