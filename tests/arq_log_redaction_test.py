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
    UVICORN_ACCESS_TEMPLATE,
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


def test_an_arq_line_of_another_shape_is_passed_through_untouched() -> None:
    """Only the two templates carry a payload or an exception message; another four-argument
    line of arq's is left as it was."""
    configure_logging()
    [withholding] = [
        f
        for f in logging.getLogger("arq.worker").filters
        if isinstance(f, core_logging._ArqJobDetailFilter)
    ]
    other = _record("%6.2fs ← %s ● %s %s", (0.5, "extract:1", "ok", "done"))
    assert withholding.filter(other)
    assert other.args == (0.5, "extract:1", "ok", "done")


def test_the_access_template_is_the_one_the_installed_uvicorn_logs() -> None:
    import uvicorn.protocols.http.h11_impl as h11_impl
    import uvicorn.protocols.http.httptools_impl as httptools_impl

    for module in (h11_impl, httptools_impl):
        source = Path(module.__file__ or "").read_text(encoding="utf-8")
        assert f"'{UVICORN_ACCESS_TEMPLATE}'" in source


def test_the_access_line_keeps_the_path_and_withholds_every_query_value() -> None:
    """A GET search (`?q=` on campaign contacts) matches a name or the last digits of a
    number, neither of which `redact_text` can see."""
    configure_logging()
    [withholding] = [
        f
        for f in logging.getLogger("uvicorn.access").filters
        if isinstance(f, core_logging._AccessLineQueryFilter)
    ]
    line = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        UVICORN_ACCESS_TEMPLATE,
        ("10.0.0.1:5000", "GET", "/v1/campaigns/abc/contacts?q=Priya&limit=50", "1.1", 200),
        None,
    )
    assert withholding.filter(line)
    rendered = line.getMessage()
    assert "Priya" not in rendered
    assert "/v1/campaigns/abc/contacts?q=[redacted]&limit=[redacted]" in rendered
    assert rendered.endswith('HTTP/1.1" 200')

    bare = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        UVICORN_ACCESS_TEMPLATE,
        ("10.0.0.1:5000", "GET", "/v1/me", "1.1", 200),
        None,
    )
    assert withholding.filter(bare)
    assert bare.args == ("10.0.0.1:5000", "GET", "/v1/me", "1.1", 200)

    other = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, "%s?%s", ("/x", "q=1"), None
    )
    assert withholding.filter(other)
    assert other.args == ("/x", "q=1"), "only uvicorn's own access line is rewritten"
