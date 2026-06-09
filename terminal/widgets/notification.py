"""Toast-style notification overlay."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.timer import Timer
from textual.widgets import Static


class NotificationOverlay(Static):
    """Transient notification banner."""

    DEFAULT_CSS = """
    NotificationOverlay {
        layer: overlay;
        dock: top;
        height: 3;
        width: 60;
        offset-x: 50%;
        margin-top: 1;
        display: none;
    }
    NotificationOverlay.visible {
        display: block;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", classes="notification", **kwargs)
        self._timer: Timer | None = None

    def show(self, message: str, duration: float = 3.0) -> None:
        self.update(message)
        self.add_class("visible")
        if self._timer:
            self._timer.stop()
        self._timer = self.set_timer(duration, self.hide)

    def hide(self) -> None:
        self.remove_class("visible")
