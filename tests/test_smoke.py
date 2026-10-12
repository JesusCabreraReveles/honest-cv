from honest_cv import __version__
from honest_cv.cli import main


def test_version():
    assert __version__


def test_cli_runs():
    assert main([]) == 0
