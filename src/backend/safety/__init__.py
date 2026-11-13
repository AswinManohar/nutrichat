"""Patient safety: hard profile, clinical tables, recipe checker, reply guard.

This package must stay free of model clients and network libraries so its
checks are deterministic (see tests/safety/test_boundaries.py).
"""

from __future__ import annotations
