# ──────────────────────────────────────────────────────────────────────
#  Arrissa Data — License & Attribution Integrity
#  Copyright (c) 2026 Arrissa Pty Ltd · https://arrissadata.com
#  Author: @davidrichchild · https://arrissa.trade · https://arrissacapital.com
#
#  This module verifies that required attribution remains intact in
#  the UI templates as mandated by the LICENSE file. Removal of
#  attribution is a license violation and disables the application.
# ──────────────────────────────────────────────────────────────────────

import os as _os
import hashlib as _hl

_DIR = _os.path.dirname(_os.path.abspath(__file__))
_TPL = _os.path.join(_DIR, "templates")

# Fingerprints that must be present in templates (obfuscated checks)
_SIG = [
    # Each tuple: (filename, list of required substrings)
    ("layout.html", [
        "arrissadata.com",
        "arrissa.trade",
        "arrissacapital.com",
        "davidrichchild",
        "Arrissa Pty Ltd",
        "data-arrissa",
    ]),
    ("base.html", [
        "arrissadata.com",
        "arrissa.trade",
        "arrissacapital.com",
        "davidrichchild",
        "arrissa-attribution",
        "data-arrissa",
    ]),
]

# Compact digest of the attribution block for fast re-verification
_EXPECTED_MARKS = {
    _hl.md5(b"arrissadata.com").hexdigest(),
    _hl.md5(b"davidrichchild").hexdigest(),
    _hl.md5(b"arrissa.trade").hexdigest(),
    _hl.md5(b"Arrissa Pty Ltd").hexdigest(),
    _hl.md5(b"arrissacapital.com").hexdigest(),
}


def _read(name):
    p = _os.path.join(_TPL, name)
    if not _os.path.isfile(p):
        return ""
    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def verify_attribution():
    """Check that all required attribution strings exist in templates.
    Returns True if intact; raises RuntimeError if tampered.
    Called at startup and periodically at request time.
    """
    for fname, marks in _SIG:
        content = _read(fname)
        if not content:
            raise RuntimeError(
                f"License violation: template '{fname}' is missing. "
                "See LICENSE for attribution requirements."
            )
        for mark in marks:
            if mark not in content:
                raise RuntimeError(
                    f"License violation: required attribution removed from '{fname}'. "
                    "Restore the original attribution block or see LICENSE. "
                    "https://github.com/vestorfinance/arrissa-data"
                )
    return True


def quick_check():
    """Lightweight check — verifies attribution marks exist.
    Returns True if OK, False if tampered.
    """
    try:
        found = set()
        for fname, marks in _SIG:
            content = _read(fname)
            for m in marks:
                if m in content:
                    found.add(_hl.md5(m.encode()).hexdigest())
        return _EXPECTED_MARKS.issubset(found)
    except Exception:
        return False


# ── Run on import (startup) ──
try:
    verify_attribution()
except RuntimeError as _e:
    import sys
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  FATAL: {_e}", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)
    sys.exit(1)
