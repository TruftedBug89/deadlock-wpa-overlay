"""Worker polling and UI state delivery for the overlay."""

import queue
import time
from typing import Optional

from models import GameState
from runtime_policy import game_running, poll_interval
from ui.hud_presentation import format_tray_text
from win32_overlay import attach_to_default_desktop, ensure_topmost


class StateUpdatesMixin:
    def _ui_tick(self) -> None:
        """One second of UI housekeeping , no I/O, no OCR."""
        self._tick += 1
        self._update_visibility()
        if self._tick % 3 == 0 and self._hwnd and not self._user_hidden:
            if not self._parked:
                try:
                    ensure_topmost(self._hwnd)
                except Exception:
                    pass
        if getattr(self, "_view", None) is not None and self._content_kind == "items":
            self._view.update_timer(self._timer_text())
        self.root.after(1000, self._ui_tick)

    def _drain_queue(self) -> None:
        try:
            latest: Optional[GameState] = None
            while True:
                try:
                    latest = self._queue.get_nowait()
                except queue.Empty:
                    break
            if latest is not None:
                self._apply_new_state(latest)
            current = self._current_state
            if current.valid_until is not None and time.time() >= current.valid_until:
                self._apply_new_state(GameState(source="advisor", scan_status="unknown"))
        except Exception as err:
            print(f"[UI] Drain queue error: {err}")
        finally:
            if not self._stop_event.is_set():
                self.root.after(200, self._drain_queue)

    def _apply_new_state(self, state: GameState) -> None:
        if state.valid_until is not None and time.time() >= state.valid_until:
            state = GameState(source="advisor", scan_status="unknown")
        previous = self._current_state
        self._current_state = state
        self._last_poll_time = time.time()

        def _sig(s: GameState):
            return (
                tuple((it.name, it.image_url, it.class_name, it.cost, it.win_rate,
                       it.samples, it.reason, it.can_buy) for it in s.recommended_items),
                tuple((c.name, c.samples, c.gain, c.enemy_name) for c in s.counter_items),
                tuple(s.enemy_heroes),
                s.is_in_match,
                s.source,
                s.scan_status,
                s.match_id,
                s.hero_id,
                s.hero_name,
                s.stage,
                s.net_worth,
                (s.next_buy.name, s.next_buy.cost) if s.next_buy else None,
                s.strongest_enemy,
                s.strongest_enemy_winrate,
            )

        try:
            if _sig(state) != _sig(previous) or self._content_kind is None:
                self._render_content()
            elif self._content_kind == "items" and self._view is not None:
                self._view.update_timer(self._timer_text())
            self._update_visibility()
        except Exception as err:
            print(f"[UI] Render error: {err}")
        if self.tray_manager is not None:
            self.tray_manager.set_status(self._tray_text())

    def _tray_text(self) -> str:
        return format_tray_text(self._current_state)

    def poll_once(self) -> GameState:
        """One exact worker poll: fetch, queue, prewarm. Used by the worker and tests."""
        state = self.data_source.get_game_state(
            max_items=self.config.max_items,
            queue_seconds=self.config.queue_seconds,
            region_override=self.config.wpa_region,
            allow_db_fallback=self.config.allow_db_fallback,
        )
        self._publish(state)
        if state.recommended_items:
            from icon_loader import prewarm_icon

            for item in state.recommended_items:
                try:
                    prewarm_icon(item.name, item.image_url, item.class_name)
                except Exception:
                    continue  # an icon problem must not hide the items
        return state

    def _worker_loop(self) -> None:
        """Heavy polling in the background: DB, log tail, capture, OCR."""
        try:
            attach_to_default_desktop()
        except Exception:
            pass
        if self._stop_event.wait(0.8):
            return
        while not self._stop_event.is_set():
            running = True
            try:
                if self._preview_event.is_set():
                    self._preview_event.clear()
                    self.data_source.cycle_next_hero()
                if self._preview_clear_event.is_set():
                    self._preview_clear_event.clear()
                    self.data_source.manual_hero_id = None
                advisor = bool(getattr(self.data_source, "is_advisor", False))
                live_required = bool(getattr(self.data_source, "require_match", False))
                running = game_running() if advisor and live_required else True
                if advisor and live_required and not running:
                    self._publish(GameState(source="advisor", scan_status="idle"))
                else:
                    self.poll_once()
            except Exception as err:
                print(f"[Worker] Exception in poll: {err}")
                self._publish(GameState(scan_status="error", last_error=f"{type(err).__name__}: {err}", generated_at=time.time()))
            # Poll fast enough that Statlocker changes/removals reach the
            # overlay within a couple of seconds instead of lingering.
            delay = poll_interval(self.config, self._current_state,
                                  bool(getattr(self.data_source, "is_advisor", False)), running)
            self._wake_event.wait(timeout=delay)
            self._wake_event.clear()

    def _publish(self, state: GameState) -> None:
        try:
            self._queue.put_nowait(state)
        except queue.Full:
            try: self._queue.get_nowait(); self._queue.put_nowait(state)
            except queue.Empty: pass
