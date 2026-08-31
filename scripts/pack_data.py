"""Pack data/, config/, output/, and .env into a restorable seed tarball."""

import argparse
from pathlib import Path

from resume_tailor_harness.services.backup import pack_local_checkout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="seed.tar.gz", type=Path)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    archive = pack_local_checkout(repo_root, args.out)
    print(f"Wrote {archive} — treat it as secret material (.env is inside).")


if __name__ == "__main__":
    main()
