"""Explicit live lane is never part of the default offline suite."""

import pytest


@pytest.mark.live
def test_live_lane_is_operator_authorized_only() -> None:
    pytest.fail("live lane must be invoked explicitly with pytest -m live")
