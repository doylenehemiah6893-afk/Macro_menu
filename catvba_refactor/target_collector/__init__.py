"""Native Windows B28 discovery collector.

This package intentionally depends only on the Python 3.12 standard library.
Its output is raw, untrusted evidence that must be ingested in the trusted A
environment before any Gate decision is made.
"""

from __future__ import annotations

__version__ = "0.1.0"

TRUST_LEVEL = "raw-untrusted"
SESSION_MODE = "discovery"
PACKAGE_ID = "core"
PROFILE_ID = "DISCOVERY"
