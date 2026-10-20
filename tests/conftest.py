import pytest

from mtl_analyst.catalog import connect


@pytest.fixture(scope="session")
def con():
    return connect()
