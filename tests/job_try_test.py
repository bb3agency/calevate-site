"""`apps.api.core.queue.job_try`: the one reading of arq's attempt counter.

FAILS IF: a job called without arq's counter (no key, None, or 0) reads as anything but
the first attempt, or a real counter is not passed through.
"""

from __future__ import annotations

from typing import Any

import pytest
from apps.api.core.queue import job_try


@pytest.mark.parametrize(
    ("ctx", "expected"),
    [
        ({}, 1),
        ({"job_try": None}, 1),
        ({"job_try": 0}, 1),
        ({"job_try": 3}, 3),
    ],
)
def test_job_try_counts_from_one(ctx: dict[str, Any], expected: int) -> None:
    assert job_try(ctx) == expected
