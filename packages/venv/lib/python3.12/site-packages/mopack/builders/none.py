from . import Builder


class NoneBuilder(Builder):
    type = 'none'
    _version = 1

    @staticmethod
    def upgrade(config, version):
        return config

    def path_bases(self):
        return ()

    def path_values(self, metadata):
        return {}

    def clean(self, metadata, pkg):
        pass

    def build(self, metadata, pkg):
        pass

    def deploy(self, metadata, pkg):
        pass
