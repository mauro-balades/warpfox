from .freezedried import FreezeDried
from .types import try_load_config


class BaseOptions:
    def accumulate(self, config, **kwargs):
        kind = getattr(self, self._type_field or 'type')
        with try_load_config(config, self._context, kind):
            return self(**config, **kwargs)


@FreezeDried.fields(skip={'_options'}, skip_compare={'_options'})
class OptionsHolder(FreezeDried):
    def __init__(self, options):
        self._options = options

    @classmethod
    def rehydrate(cls, config, *, _options, **kwargs):
        result = super(OptionsHolder, cls).rehydrate(
            config, _options=_options, **kwargs
        )
        result._options = _options
        return result

    @property
    def _common_options(self):
        return self._options.common

    @property
    def _this_options(self):
        name = getattr(self, self._type_field)
        return getattr(self._options, self._options_type).get(name)
