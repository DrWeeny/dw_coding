"""
guide_registry.py - DynForge guide backend plugin registry

A "guide" is anything an artist installs on a costume to drive secondary
deformation: a joint chain today, an nHair curve or a constraint setup later.
Each guide TYPE is a GuideBackend subclass that self-registers once at import
time via register(). The UI and snapshot code talk to the registry without
knowing any concrete guide type.

Registration is triggered by importing the backends package:
    from dw_maya.DynForge import backends   # noqa: F401

Design note
-----------
SimSystem (DynEval) is a dataclass-of-callables because a sim backend is a
stateless descriptor. A guide is different: an INSTANCE carries state (status,
the built nodes, the source curve) and polymorphic build logic, so GuideBackend
is an abstract base class and instances are what the UI manages. The class is
what gets registered; calling it (or its factories) produces instances.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from typing import Optional

from dw_logger import get_logger

logger = get_logger()


# ============================================================================
# STATUS
# ============================================================================

class GuideStatus(enum.Enum):
    """Lifecycle state of a single guide instance (one row in the guide list)."""
    PENDING = "pending"   # parameters / locators set, nodes not built yet
    BUILT   = "built"     # the joint chain / curve exists in the scene
    BROKEN  = "broken"    # built before but source / nodes can no longer be found


# ============================================================================
# GUIDE BACKEND (abstract base for one guide instance)
# ============================================================================

class GuideBackend(ABC):
    """
    Abstract base for ONE guide instance (one row in the guide list).

    Subclasses describe a guide TYPE via the three class attributes below and
    implement the build / destroy / serialize behaviour.

    Class attributes (override in every subclass)
    ---------------------------------------------
    type_name       stable key used in the registry and JSON ('chain_joint')
    label           human-readable name shown in the UI ('Joint Chain')
    creation_modes  creation flows this type supports ('edge', 'face', 'locator')
    """

    type_name:      str = ""
    label:          str = ""
    creation_modes: tuple = ()

    def __init__(self, name: str = "guide") -> None:
        self.name    = name
        self._status = GuideStatus.PENDING

    @property
    def status(self) -> GuideStatus:
        return self._status

    # -- Lifecycle --------------------------------------------------------

    @abstractmethod
    def build(self) -> None:
        """Materialize the guide in the scene (PENDING -> BUILT)."""

    @abstractmethod
    def destroy(self) -> None:
        """Remove the built nodes from the scene (-> PENDING)."""

    # -- Serialization (reproducibility snapshot) -------------------------

    @abstractmethod
    def to_dict(self) -> dict:
        """Return a JSON-serializable reproducibility snapshot of this guide."""

    @classmethod
    @abstractmethod
    def from_dict(cls,
                  data: dict,) -> "GuideBackend":
        """Rebuild a guide instance from a to_dict() payload (not yet built)."""

    # -- Creation ---------------------------------------------------------

    @classmethod
    def create(cls,
               **params,) -> "GuideBackend":
        """
        Create a new (PENDING) guide of this type from a flat params dict
        (expects at least a 'mode' key). Override per backend to dispatch to the
        right creation factory. Lets the UI create any guide type generically.
        """
        raise NotImplementedError(
            f"{cls.__name__} does not implement create()."
        )

    # -- Discovery --------------------------------------------------------

    @classmethod
    def discover(cls) -> list:
        """
        Find already-built guides of this type in the current scene and return
        them as instances (status BUILT). Default: nothing. Override per backend.
        """
        return []


# ============================================================================
# REGISTRY STORAGE
# ============================================================================

_by_type_name: dict[str, type] = {}


def register(backend_cls: type) -> None:
    """
    Register a GuideBackend subclass. Called once at import time from backends/.
    Idempotent: re-registering the same type_name overwrites the previous entry.
    """
    type_name = getattr(backend_cls, "type_name", "")
    if not type_name:
        raise ValueError(f"GuideBackend {backend_cls!r} has no type_name set.")
    _by_type_name[type_name] = backend_cls
    logger.debug(f"GuideBackend registered: {type_name!r}")


def get_backend(type_name: str) -> Optional[type]:
    """Lookup a backend class by its type_name (e.g. 'chain_joint')."""
    return _by_type_name.get(type_name)


def available_backends() -> list[type]:
    """All registered backend classes, in registration order."""
    return list(_by_type_name.values())


def discover_all() -> list[GuideBackend]:
    """
    Ask every registered backend to find its built guides in the current scene.

    Returns
    -------
    list[GuideBackend]  - flat list of instances (status BUILT), across all types.
    """
    found: list[GuideBackend] = []
    for backend_cls in _by_type_name.values():
        try:
            found.extend(backend_cls.discover())
        except Exception as e:
            name = getattr(backend_cls, "type_name", backend_cls)
            logger.warning(f"discover_all: {name!r} discover failed: {e}")
    return found


def guide_from_dict(data: dict) -> Optional[GuideBackend]:
    """
    Rebuild a guide instance from a snapshot dict, dispatching on its 'type_name'.
    Returns None if the type is not registered.
    """
    type_name = data.get("type_name", "")
    backend_cls = _by_type_name.get(type_name)
    if backend_cls is None:
        logger.warning(f"guide_from_dict: no backend registered for {type_name!r}")
        return None
    return backend_cls.from_dict(data)