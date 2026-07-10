"""Studio pipeline adapter for dw_open_tools.

Summary:
    Single porting surface between this library and a studio pipeline.
    Tools never hardcode folder logic; they call ``get_project()`` and ask
    the returned :class:`Project` for names and paths. An external user
    ports the library by subclassing :class:`Project` in one file and
    pointing the ``DW_PIPE_PROJECT`` environment variable at it.

Features:
    - Abstract :class:`Project` interface (namespace queries + asset
      listing + preset locations).
    - :class:`DefaultProject` filesystem fallback rooted at a stable temp
      directory (overridable with ``DW_PRESET_PATH`` or ``set_root``).
    - ``get_project()`` / ``set_project()`` module-level accessors with
      lazy loading of the external adapter. A broken adapter logs a
      traceback and falls back to :class:`DefaultProject` - it must never
      prevent a tool from opening.

Classes:
    Project, DefaultProject

Functions:
    get_project, set_project

Example:
    # my_studio_pipe.py, then set DW_PIPE_PROJECT=D:/pipe/my_studio_pipe.py
    import dw_pipe_project

    class MyStudioProject(dw_pipe_project.Project):
        def list_assets(self, category=None):
            return my_asset_db.query(category)
        def get_preset_dir(self, asset, category=None):
            return f"/prod/assets/{asset}/cfx/presets"

TODO:
    - Reconcile with dw_utils.dw_project (shot-context dataclass).

Author:
    DrWeeny
"""

import os
import tempfile
import traceback
import importlib
import importlib.util

from dw_logger import get_logger

logger = get_logger()


class Project(object):
    """Abstract pipe adapter. Subclass and implement what your tools need.

    Asset identifiers are opaque strings: encode as many hierarchy levels
    as your studio uses (category/variation/department/...) - tools only
    display them and hand them back to :meth:`get_preset_dir`.
    """

    # ------------------------------------------------------------------
    # Namespace-keyed queries (scene -> pipe identity)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Listing / preset locations (pipe -> UI)
    # ------------------------------------------------------------------

    def list_asset_categories(self):
        """Return category labels used to group assets (may be empty)."""
        raise NotImplementedError("'list_asset_categories' is not implemented")

    def list_assets(self, category: str = None):
        """Return asset identifiers, optionally filtered by category."""
        raise NotImplementedError("'list_assets' is not implemented")

    def get_preset_dir(self, asset: str, category: str = None):
        """Return the directory where this asset's presets are stored."""
        raise NotImplementedError("'get_preset_dir' is not implemented")


class DefaultProject(Project):
    """Filesystem fallback: ``{root}/{category}/{asset}/attr_presets``.

    Root resolution order: explicit :meth:`set_root` -> ``DW_PRESET_PATH``
    environment variable -> stable folder under the system temp dir (fixed
    name on purpose, so quick-test presets survive across sessions).
    """

    TEMP_DIRNAME = 'dw_attr_presets'
    DEFAULT_CATEGORIES = ['character', 'prop']

    def __init__(self, root: str = None):
        self._root = root or None

    @property
    def root(self) -> str:
        if self._root:
            return self._root
        env_root = os.environ.get('DW_PRESET_PATH')
        if env_root:
            return env_root
        return os.path.join(tempfile.gettempdir(), self.TEMP_DIRNAME)

    def set_root(self, root: str = None):
        """Override the root (None restores env/temp resolution)."""
        self._root = root or None

    def _list_dirs(self, path: str):
        if not os.path.isdir(path):
            return []
        return sorted(d for d in os.listdir(path)
                      if os.path.isdir(os.path.join(path, d)))

    def list_asset_categories(self):
        found = self._list_dirs(self.root)
        return found or list(self.DEFAULT_CATEGORIES)

    def list_assets(self, category: str = None):
        base = os.path.join(self.root, category) if category else self.root
        return self._list_dirs(base)

    def get_preset_dir(self, asset: str, category: str = None):
        parts = [self.root]
        if category:
            parts.append(category)
        if asset:
            parts.append(asset)
        parts.append('attr_presets')
        return os.path.join(*parts)


# ---------------------------------------------------------------------------
# Active project accessors
# ---------------------------------------------------------------------------

_current_project = None


def set_project(project: Project):
    """Register the active pipe adapter (e.g. from a studio userSetup)."""
    global _current_project
    _current_project = project


def get_project() -> Project:
    """Return the active adapter, loading it on first call.

    Resolution: instance passed to :func:`set_project` -> module/file named
    by the ``DW_PIPE_PROJECT`` environment variable -> :class:`DefaultProject`.
    """
    global _current_project
    if _current_project is None:
        _current_project = _load_external_project() or DefaultProject()
    return _current_project


def _load_external_project():
    """Load a Project from ``DW_PIPE_PROJECT`` (file path or module name).

    The module may expose a ``get_project()`` factory or simply define a
    :class:`Project` subclass (first one found is instantiated). Any error
    is logged with its traceback and None is returned so callers fall back
    to :class:`DefaultProject`.
    """
    target = os.environ.get('DW_PIPE_PROJECT')
    if not target:
        return None
    try:
        if os.path.isfile(target):
            spec = importlib.util.spec_from_file_location('dw_pipe_project_ext',
                                                          target)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        else:
            module = importlib.import_module(target)

        factory = getattr(module, 'get_project', None)
        if callable(factory):
            project = factory()
            if isinstance(project, Project):
                return project
            logger.warning(f"DW_PIPE_PROJECT '{target}': get_project() did not "
                           f"return a Project instance, ignoring it")

        for obj in vars(module).values():
            if (isinstance(obj, type) and issubclass(obj, Project)
                    and obj is not Project and obj is not DefaultProject):
                return obj()

        logger.warning(f"DW_PIPE_PROJECT '{target}' defines no get_project() "
                       f"factory nor Project subclass")
    except Exception:
        logger.error(f"Failed to load DW_PIPE_PROJECT '{target}', falling back "
                     f"to DefaultProject:\n{traceback.format_exc()}")
    return None
