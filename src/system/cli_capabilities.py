import json
import sys
from typing import List, Optional

from .capabilities import get_capabilities


def main(argv: Optional[List[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    pretty = False
    for a in args:
        if a in ("-p", "--pretty"):
            pretty = True
    caps = get_capabilities()
    if pretty:
        print(json.dumps(caps, indent=2, sort_keys=True))
    else:
        print(json.dumps(caps, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
