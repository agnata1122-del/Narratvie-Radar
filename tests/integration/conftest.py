import pytest
from graphkit import GraphKit


@pytest.fixture
def g(session, clock):
    return GraphKit(session, clock)
