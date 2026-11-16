"""Control the local deployment marker, never user credentials or billing data."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.deployment import drain_path

MARKER = b"cat-api-deployment-drain-v1\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("begin", "status", "end"))
    action = parser.parse_args().action
    path = drain_path().resolve()
    if action == "begin":
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as target:
                target.write(MARKER)
            path.chmod(0o600)
        except FileExistsError:
            if path.read_bytes() != MARKER:
                raise SystemExit("Refusing to overwrite an unknown drain marker")
    elif action == "end" and path.exists():
        if path.read_bytes() != MARKER:
            raise SystemExit("Refusing to remove an unknown drain marker")
        path.unlink()
    print(("draining" if path.exists() else "accepting") + ": " + str(path))


if __name__ == "__main__":
    main()
