"""Smoke test — proves pytest runs and the package imports.

Replaced with real tests as milestones land. Exists now so the CI eval gate
(M0 Step 7) has something green to run from day one.
"""


def test_package_imports():
    import src  # noqa: F401


def test_sanity():
    assert 1 + 1 == 2
