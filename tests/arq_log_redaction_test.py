"""arq's own job lines reach the log without the job's arguments or the exception message
(hard rule 6).

The `arq` CLI installs a plain-text handler that printed `→ job(<payload>)` — an auth
email's address and one-time code — and `! job failed, <Class>: <str(e)>` with the
traceback, past every redaction the JsonFormatter applies.
"""

from __future__ import annotations

import logging
from pathlib import Path

import arq.worker
from apps.api.core import logging as core_logging
from apps.api.core.logging import (
    ARQ_JOB_FAILED_TEMPLATE,
    ARQ_JOB_START_TEMPLATE,
    MESSAGE_WITHHELD,
    configure_logging,
)


def test_both_templates_are_the_ones_the_installed_arq_logs() -> None:
    source = Path(arq.worker.__file__).read_text(encoding="utf-8")
    assert f"'{ARQ_JOB_START_TEMPLATE}'" in source
    assert f"'{ARQ_JOB_FAILED_TEMPLATE}'" in source


def _record(msg: str, args: tuple[object, ...]) -> logging.LogRecord:
    return logging.LogRecord("arq.worker", logging.INFO, __file__, 1, msg, args, None)


def test_configure_logging_drops_arqs_handler_and_withholds_job_detail() -> None:
    arq_logger = logging.getLogger("arq")
    arq_logger.addHandler(logging.StreamHandler())
    configure_logging()
    assert arq_logger.handlers == []
    filters = [
        f
        for f in logging.getLogger("arq.worker").filters
        if isinstance(f, core_logging._ArqJobDetailFilter)
    ]
    assert len(filters) == 1
    configure_logging()
    again = [
        f
        for f in logging.getLogger("arq.worker").filters
        if isinstance(f, core_logging._ArqJobDetailFilter)
    ]
    assert again == filters, "configuring twice must not stack a second filter"

    started = _record(
        ARQ_JOB_START_TEMPLATE,
        (0.01, "send_auth_email:1", "{'to': 'a@b.in', 'secret': '493817'}", ""),
    )
    assert filters[0].filter(started)
    assert "493817" not in started.getMessage() and "a@b.in" not in started.getMessage()
    assert MESSAGE_WITHHELD in started.getMessage()

    failed = _record(
        ARQ_JOB_FAILED_TEMPLATE,
        (1.0, "extract:1", "ValidationError", "input_value='naa number 9876543210'"),
    )
    assert filters[0].filter(failed)
    assert "9876543210" not in failed.getMessage()
    assert "ValidationError" in failed.getMessage() and "extract:1" in failed.getMessage()
