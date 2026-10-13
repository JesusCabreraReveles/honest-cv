"""Release metadata stays consistent: one version, and the MCP registry's ownership line."""

import json
from pathlib import Path

from honest_cv import __version__

ROOT = Path(__file__).parent.parent
SERVER = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))


def test_server_json_version_matches_the_package():
    assert SERVER["version"] == __version__
    assert [p["version"] for p in SERVER["packages"]] == [__version__]


def test_readme_proves_ownership_to_the_mcp_registry():
    # The registry reads PyPI's description (README.md) for "mcp-name: <name>".
    line = f"<!-- mcp-name: {SERVER['name']} -->"
    assert line in (ROOT / "README.md").read_text(encoding="utf-8")


def test_registry_package_runs_the_server():
    package = SERVER["packages"][0]
    assert (package["registryType"], package["identifier"], package["runtimeHint"]) == ("pypi", "honest-cv", "uvx")
    assert [a["value"] for a in package["packageArguments"]] == ["serve"]
