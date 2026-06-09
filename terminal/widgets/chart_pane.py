"""Real-time terminal charts via plotext."""

from __future__ import annotations

import io

import plotext as plt
from rich.text import Text
from textual.widgets import Static

from terminal.core.models import MetricPoint


class ChartPane(Static):
    """Renders balance/equity curve using plotext → Rich."""

    DEFAULT_CSS = """
    ChartPane {
        height: 1fr;
        width: 1fr;
        padding: 0 1;
    }
    """

    def __init__(self, title: str = "Balance", **kwargs) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._points: list[MetricPoint] = []

    def update_metrics(self, points: list[MetricPoint]) -> None:
        self._points = points
        self.refresh()

    def render(self) -> Text:
        if len(self._points) < 2:
            return Text("Collecting metrics…", style="dim")

        values = [p.value for p in self._points]
        plt.clear_figure()
        plt.theme("clear")
        plt.plot(values, marker="braille", color="orange")
        plt.title(self._title)
        plt.xlabel("t")
        plt.ylabel("$")
        plt.plotsize(max(40, self.size.width - 4), max(8, self.size.height - 2))

        buf = io.StringIO()
        plt.savefig(buf, clear=False)
        chart = buf.getvalue()
        plt.clear_figure()

        text = Text(chart, style="")
        return text
