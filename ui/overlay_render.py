"""Content rendering for the overlay window.

Mixin split so ``OverlayWindow`` stays below the file-size ceiling.  The mixin
reads and mutates the window's own fields; it adds no state.
"""

from typing import Tuple

from ui import counter_panel
from ui.counter_view import CounterView
from ui.hud_geometry import stack_metrics
from ui.hud_presentation import format_timer_text, get_desired_content
from ui.icon_view import IconStripView
from ui.idle_view import StatusBadgeView
from ui.minimal_view import MinimalItemView


class RenderMixin:
    def _timer_text(self) -> str:
        return format_timer_text(
            self._current_state,
            self._last_poll_time,
            bool(getattr(self.config, "show_timer", False)),
        )

    def _desired_content(self) -> Tuple[str, int]:
        return get_desired_content(
            self._current_state,
            self.config,
            self._is_ingame(),
            self._feedback,
            force_visible=self._forced_visible,
        )

    def _render_content(self) -> None:
        if self._drag_handler.active:
            self._refresh_drag_content()
            return
        kind, slots = self._desired_content()
        same_shell = (
            kind == self._content_kind
            and slots == self._content_slots
            and self._view is not None
            and self.container.winfo_children()
        )
        if same_shell and kind == "items":
            # The counter view can only swap chips in place; a different chip
            # count needs a rebuild, otherwise the old count stays on screen.
            desired = len(counter_panel.visible_counters(self._current_state, self.config))
            current = len(self._counter_view.counters) if self._counter_view is not None else 0
            same_shell = current == desired
        if same_shell and kind == "items":
            self._view.set_items(self._current_state.recommended_items[: self.config.max_items])
            self._view.update_timer(self._timer_text())
            if self._counter_view is not None:
                self._counter_view.set_counters(
                    counter_panel.visible_counters(self._current_state, self.config),
                    counter_panel.subtitle(self._current_state),
                )
            self._apply_geometry(slots)
            return
        if same_shell and kind in ("feedback", "status"):
            title, color = self._status_info()
            self._view.set_status(title, "", color)
            self._apply_metrics(self._badge_metrics(title))
            return

        self._content_kind, self._content_slots = kind, slots
        for child in self.container.winfo_children():
            child.destroy()
        self._view = None
        self._counter_view = None

        if kind == "hidden":
            self._withdraw()
            return

        pack_options = {"fill": "both", "expand": True}
        if kind == "items":
            items = self._current_state.recommended_items[: self.config.max_items]
            base = self._base_metrics_for(slots)
            panel, counters = counter_panel.panel_for(
                self._current_state, self.config, self._scale, base
            )
            metrics = stack_metrics(base, panel) if panel is not None else base
            if bool(getattr(self.config, "icons_only", False)):
                view = IconStripView(self.container, items, base)
            else:
                view = MinimalItemView(self.container, items, base, timer_text=self._timer_text())
            self._counter_view = None
            if panel is not None:
                self._counter_view = CounterView(
                    self.container, counters, panel, subtitle=counter_panel.subtitle(self._current_state)
                )
                self._counter_view.pack(side="bottom", fill="x")
                pack_options = {"side": "top", "fill": "x"}
        else:
            title, color = self._status_info()
            metrics = self._badge_metrics(title)
            view = StatusBadgeView(self.container, title=title, subtitle="", dot_color=color,
                                   scale=self._scale)
        self._view = view
        view.pack(**pack_options)
        self._position_window(metrics)
        self._update_visibility()

    def _refresh_drag_content(self) -> None:
        """Refresh safety-sensitive content while leaving drag geometry alone."""
        if self._view is None or not hasattr(self._view, "set_items"):
            return
        items = self._current_state.recommended_items[: self.config.max_items]
        if len(items) != len(self._view.items):
            self._content_kind = None  # rebuild the shell after release
        self._view.set_items(items)
        if self._counter_view is not None:
            counters = counter_panel.visible_counters(self._current_state, self.config)
            if len(counters) == len(self._counter_view.counters):
                self._counter_view.set_counters(counters, counter_panel.subtitle(self._current_state))
            else:
                # Existing chip widgets cannot change count in place. Hide them
                # now rather than retaining a claim that failed the latest gates.
                self._counter_view.pack_forget()
                self._content_kind = None

    def show_feedback(self, title: str, dot_color: str = "#38bdf8", duration_ms: int = 1200) -> None:
        """Flash one short word, then return to the live state."""
        self._feedback = (title, dot_color)
        self._feedback_token += 1
        token = self._feedback_token
        self._render_content()

        def _clear():
            if token != self._feedback_token:
                return
            self._feedback = None
            self._render_content()

        self.root.after(duration_ms, _clear)
