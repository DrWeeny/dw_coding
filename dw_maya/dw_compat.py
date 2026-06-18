"""Typing compatibility helpers for mixed Python versions.

Maya ships different Python versions across releases: Maya 2022 runs Python 3.7,
whose :mod:`typing` module has **no** ``Literal`` (added in 3.8), while newer
Maya (2023+) runs 3.9/3.10 where it is built in. ``typing_extensions`` provides
a backport, but it is not guaranteed to be installed in a stock Maya — and we
explicitly want the toolkit to work for anyone **without any pip install**.

Import ``Literal`` from here instead of from ``typing`` / ``typing_extensions``::

    from dw_maya.dw_compat import Literal

Resolution order:
    1. ``typing.Literal``           — Python 3.8+ (the normal case).
    2. ``typing_extensions.Literal``— Python 3.7 if the backport happens to be installed.
    3. A minimal runtime stub       — Python 3.7 with nothing installed.

The stub only needs to let annotations such as ``Literal['flood', 'smooth']``
*evaluate* at import time; the values are never enforced at runtime, so it
simply collapses to :data:`typing.Any`. Static type checkers run on a modern
Python and resolve via branch 1, so they keep full ``Literal`` checking.

Author:
    DrWeeny
"""

try:
    from typing import Literal  # Python 3.8+
except ImportError:
    try:
        from typing_extensions import Literal  # Python 3.7 with the backport
    except ImportError:
        # Python 3.7 without typing_extensions: runtime no-op so that
        # `Literal['a', 'b']` evaluates to `Any` instead of raising.
        from typing import Any as _Any

        class _LiteralStub:
            """Subscriptable stand-in for ``typing.Literal`` (annotations only)."""

            def __getitem__(self, item):
                return _Any

        Literal = _LiteralStub()