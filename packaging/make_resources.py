"""Build the frozen app's packed UI and static resources."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("frontend_dist", type=Path)
    parser.add_argument("clients", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    if not args.frontend_dist.is_dir():
        raise SystemExit(f"frontend build is missing: {args.frontend_dist}")
    if not args.clients.is_file():
        raise SystemExit(f"client configuration is missing: {args.clients}")

    backend = Path(__file__).resolve().parents[1] / "Backend"
    sys.path.insert(0, str(backend))
    from dannify.respack import pack

    members = {
        f"ui/{path.relative_to(args.frontend_dist).as_posix()}": path.read_bytes()
        for path in args.frontend_dist.rglob("*")
        if path.is_file()
    }
    members["dannify/clients.json"] = args.clients.read_bytes()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(pack(members))
    print(f"packed {len(members)} resources into {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
