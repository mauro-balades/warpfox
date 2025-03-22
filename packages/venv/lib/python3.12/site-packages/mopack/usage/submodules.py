from ..placeholder import placeholder as _placeholder


class SubmodulePlaceholder:
    pass


placeholder = SubmodulePlaceholder()
variable = _placeholder(placeholder)
expr_symbols = {'submodule': variable}
