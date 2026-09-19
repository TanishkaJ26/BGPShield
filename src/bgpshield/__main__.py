"""Allow ``python -m bgpshield`` as an alternative to the ``bgpshield`` console script.

The reproduction runner falls back to this form when the console script cannot be found,
so a checkout that was installed without scripts on the PATH still works end to end.
"""

from bgpshield.cli import run

if __name__ == "__main__":
    run()
