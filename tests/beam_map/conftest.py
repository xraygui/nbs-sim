from pathlib import Path

import pytest

EXAMPLE = Path(__file__).parent / "example_map.toml"


@pytest.fixture
def example_path():
    return str(EXAMPLE)
