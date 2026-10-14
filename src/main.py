"""Compatibility entry point for running the travel-claim CLI from source."""

from travel_claim.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
