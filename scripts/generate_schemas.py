"""Thin wrapper for the existing CLI location.

Delegates to the packaged module.
"""

from psychoanalyst_app.schemas.generate_schemas import main

if __name__ == "__main__":
    main()
