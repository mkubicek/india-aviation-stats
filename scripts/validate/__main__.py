"""CLI: ``PYTHONPATH=scripts python -m validate [--assumptions]``."""

import argparse
import sys

from . import run


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the canonical aviation layers.")
    parser.add_argument("--assumptions", action="store_true",
                        help="also re-test the assumptions ledger + reverse gate")
    parser.add_argument("--revisions", action="store_true",
                        help="also emit REVISIONS.md (git-diff vs last data commit)")
    args = parser.parse_args()

    code = run()

    if args.assumptions:
        from .assumptions import run_assumptions
        code = max(code, run_assumptions())
    if args.revisions:
        from .revisions import run_revisions
        run_revisions()
    return code


if __name__ == "__main__":
    sys.exit(main())
