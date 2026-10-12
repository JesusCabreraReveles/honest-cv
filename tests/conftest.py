import copy
from pathlib import Path

import pytest
import yaml

from honest_cv.model import load

ADA = Path(__file__).parent.parent / "examples" / "ada"


@pytest.fixture
def ada():
    return load(ADA)


@pytest.fixture
def ada_raw():
    """The Ada files as dicts, to build broken variants in tests."""
    return {name: yaml.safe_load((ADA / f"{name}.yaml").read_text()) for name in ("profile", "bullets", "skills", "variants")}


@pytest.fixture
def make_source(tmp_path, ada_raw):
    def _make(mutate):
        raw = copy.deepcopy(ada_raw)
        mutate(raw)
        for name, data in raw.items():
            (tmp_path / f"{name}.yaml").write_text(yaml.safe_dump(data, allow_unicode=True))
        return load(tmp_path)

    return _make
