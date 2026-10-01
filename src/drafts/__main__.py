"""Allow ``python -m drafts`` as an alternative to the ``drafts`` console script."""

import sys

from drafts.cli import main

if __name__ == "__main__":
    sys.exit(main())
