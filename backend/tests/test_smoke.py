"""Step 1 smoke test: verify the backend package is importable and basic Python works."""


def test_app_package_importable() -> None:
    """The app package must be importable without side-effects."""
    import app  # noqa: F401

    assert app is not None


def test_python_version() -> None:
    """Confirm we are running on Python 3.13+."""
    import sys

    assert sys.version_info >= (3, 13), f"Expected Python 3.13+, got {sys.version}"
