"""The typed chart and table Pip shows in the chat and on a pinned dashboard card (D-934).

A spec is DATA, never markup: the browser draws it with the console's own chart components
(`components/arc/*`), so nothing a model writes or a caller said can reach the page as HTML.
Every value is a decimal STRING — counts and rupees alike — so money stays exact on the wire
(hard rule 7) and the table fallback shows the figure as computed; the browser parses a copy
only to size a bar.

`chart` and `args` are the QUERY that produced the spec. A pin stores those two and nothing
else, so a pinned card re-runs under the viewer's own session and permissions instead of
showing figures somebody else was allowed to see.
"""

from __future__ import annotations

from datetime import date
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

ChartKind = Literal["line", "bar", "stacked_bar", "pie", "number", "table"]
ChartUnit = Literal["calls", "leads", "inr", "minutes", "percent", "count"]
ChartBucket = Literal["day", "week", "month", "category"]

#: The longest window a chart reads, the same ceiling the Performance screen's reads take.
MAX_CHART_DAYS: Final = 366
DEFAULT_CHART_DAYS: Final = 30
#: The most categories or table rows a spec carries; the rest are counted, not shown.
MAX_CHART_ROWS: Final = 10


class ChartArgs(BaseModel):
    """What a chart was asked for. The same shape in a pin, so a pin replays exactly."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    days: int = Field(DEFAULT_CHART_DAYS, ge=1, le=MAX_CHART_DAYS)


class ChartAxis(BaseModel):
    """The x axis: IST dates (`YYYY-MM-DD`, each the first day of its bucket) or names."""

    model_config = ConfigDict(extra="forbid")

    label: str
    bucket: ChartBucket
    labels: list[str]


class ChartSeries(BaseModel):
    """One line, one bar colour or the slices of a pie. One value per x label."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    values: list[str]


class ChartColumn(BaseModel):
    """One column of a table spec. `numeric` right-aligns it."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    numeric: bool = False


class ChartOpen(BaseModel):
    """The console screen that shows the same set, with the same filters.

    `path` is a constant from the server's own screen inventory, relative to the realm's
    root (`/calls` under `/c/{slug}`, `/health` under `/admin`); `query` is the screen's
    own filter parameters. Neither is ever written by a model."""

    model_config = ConfigDict(extra="forbid")

    screen: str
    path: str
    query: dict[str, str] = {}


class ChartSpec(BaseModel):
    """One chart or table, with the sentence saying how it was counted."""

    model_config = ConfigDict(extra="forbid")

    chart: str
    args: ChartArgs
    kind: ChartKind
    title: str
    unit: ChartUnit
    #: Present for every kind but `number` and `table`.
    x: ChartAxis | None = None
    series: list[ChartSeries] = []
    #: Present for `table`.
    columns: list[ChartColumn] = []
    rows: list[list[str]] = []
    #: The headline figure, as a decimal string, when one sums the chart.
    total: str | None = None
    #: How this was counted, in one plain sentence: the window, the bucket, what is left out.
    counted: str
    #: The IST days the figures cover, inclusive.
    window_from: date | None = None
    window_to: date | None = None
    #: Set when the rows or categories were cut: "top `shown` of `of`".
    shown: int | None = None
    of: int | None = None
    open: ChartOpen | None = None


__all__ = [
    "DEFAULT_CHART_DAYS",
    "MAX_CHART_DAYS",
    "MAX_CHART_ROWS",
    "ChartArgs",
    "ChartAxis",
    "ChartBucket",
    "ChartColumn",
    "ChartKind",
    "ChartOpen",
    "ChartSeries",
    "ChartSpec",
    "ChartUnit",
]
