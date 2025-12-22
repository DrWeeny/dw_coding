import os

class Project(object):

    def get_asset_category(self, namespace_name: str):
        raise NotImplementedError("'get_asset_category' is not implemented")

    def get_asset_name(self, namespace_name: str):
        raise NotImplementedError("'get_asset_name' is not implemented")

    def get_asset_variant_name(self, namespace_name: str):
        raise NotImplementedError("'get_asset_variant_name' is not implemented")

    def get_asset_wip_path(self, namespace_name: str):
        raise NotImplementedError("'get_asset_wip_path' is not implemented")

    def get_asset_pub_path(self, namespace_name: str):
        raise NotImplementedError("'get_asset_pub_path' is not implemented")