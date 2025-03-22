from argparse import *
import yaml

from .iterutils import merge_into_dict

_ArgumentParser = ArgumentParser
_Action = Action


# Add some simple wrappers to make it easier to specify shell-completion
# behaviors.

def _add_complete(argument, complete):
    if complete is not None:
        argument.complete = complete
    return argument


class Action(_Action):
    def __init__(self, *args, complete=None, **kwargs):
        super().__init__(*args, **kwargs)
        _add_complete(self, complete)


class ArgumentParser(_ArgumentParser):
    @staticmethod
    def _wrap_complete(action):
        def wrapper(*args, complete=None, **kwargs):
            return _add_complete(action(*args, **kwargs), complete)

        return wrapper

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for k, v in self._registries['action'].items():
            self._registries['action'][k] = self._wrap_complete(v)


class KeyValueAction(Action):
    def __call__(self, parser, namespace, values, option_string=None):
        try:
            key, value = values.split('=', 1)
        except ValueError:
            raise ArgumentError(self, 'expected TYPE=PATH')
        if getattr(namespace, self.dest) is None:
            setattr(namespace, self.dest, {})
        getattr(namespace, self.dest)[key] = value


class ConfigOptionAction(Action):
    def __init__(self, *args, key=None, **kwargs):
        if 'const' in kwargs:
            kwargs['nargs'] = 0
        super().__init__(*args, **kwargs)
        self.key = key or []

    def __call__(self, parser, namespace, values, option_string=None):
        if self.nargs == 0:
            key = self.key
            value = self.const
        else:
            try:
                key, value = values.split('=', 1)
            except ValueError:
                raise ArgumentError(self, 'expected OPTION=VALUE')

            key = self.key + key.split(':')

            try:
                value = yaml.safe_load(value)
            except yaml.parser.ParserError:
                raise ArgumentError(self, 'invalid yaml: {!r}'.format(value))

        for i in reversed(key):
            value = {i: value}
        if getattr(namespace, self.dest) is None:
            setattr(namespace, self.dest, {})
        merge_into_dict(getattr(namespace, self.dest), value)
