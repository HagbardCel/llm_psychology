"""Thin wrapper to keep the existing CLI location while delegating to the packaged module."""

from psychoanalyst_app.schemas.generate_schemas import main


if __name__ == "__main__":
    main()
