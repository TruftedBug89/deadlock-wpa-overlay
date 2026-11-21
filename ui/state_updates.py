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
                    request, candidate = self._queue.get_nowait()
                    if request is self._connection_request:
                        latest = candidate
                except queue.Empty:
                    break
            if latest is not None:
                self._apply_new_state(latest)
            current = self._current_state
            if current.valid_until is not None and time.time() >= current.valid_until:
                self._apply_new_state(self._expired_state())
            if self._icon_refresh.is_set():
                self._icon_refresh.clear()
                if self._content_kind in {"items", "full_build"}:
                    self._render_content()
        except Exception as err:
            print(f"[UI] Drain queue error: {err}")
        finally:
            if not self._stop_event.is_set():
                self.root.after(200, self._drain_queue)

    def _apply_new_state(self, state: GameState) -> None:
        if state.valid_until is not None and time.time() >= state.valid_until:
            state = self._expired_state()
        if self._settings is not None:
            self._settings.update_connection_status(state)
        previous = self._current_state
        self._current_state = state
        self._last_poll_time = time.time()

        def _sig(s: GameState):
            return (
                tuple((it.name, it.image_url, it.class_name, it.cost, it.win_rate,
                       it.samples, it.reason, it.can_buy) for it in s.recommended_items),
                tuple((c.name, c.image_url, c.samples, c.gain, c.enemy_name, c.evidence.get("basis"))
                      for c in s.counter_items),
                tuple(s.enemy_heroes),
                tuple((it.item_id, it.name, it.image_url, it.cost, it.win_rate, it.reason, it.can_buy)
                      for it in s.build_plan),
                tuple(sorted(s.owned_items)), s.threat_summary, s.build_note, s.last_error, s.buy_budget,
                getattr(s, "replacement", None), getattr(s, "inventory_capacity", None), s.known_owned_items,
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
        health = getattr(self, "_playtest_health", None)
        if health is not None:
            health.record(state, self._content_kind, getattr(self.data_source, "last_explanation", None))

    def _tray_text(self) -> str:
        return format_tray_text(self._current_state)

    @staticmethod
    def _expired_state():
        return GameState(source="advisor", scan_status="unknown",
                         last_error="Waiting for a fresh public broadcast snapshot.")

    def request_connection(self) -> None:
        """Post one coherent set of settings for the worker's next scan."""
        self._connection_request = (self.config.account_id, self.config.match_id,
                                    self.config.read_match_id)
        self._apply_new_state(GameState(source="advisor", scan_status="connecting"))
        self._wake_event.set()

    def poll_once(self) -> GameState:
        """One exact worker poll: fetch, queue, prewarm. Used by the worker and tests."""
        request = self._connection_request
        if request is not self._worker_connection:
            source = self.data_source
            source.account_id, source.match_id, source.read_match_id = request
            source.reset_connection()
            self._worker_connection = request
        scan_args = dict(max_items=self.config.max_items, region_override=self.config.wpa_region,
                         allow_db_fallback=self.config.allow_db_fallback)
        if getattr(self.data_source, "is_advisor", False):
            def announce():
                state = GameState(source="advisor", scan_status="connecting",
                                  last_error="Match ID found. Waiting for the public broadcast.")
                self._publish(state, request)

            def capacity_ready():
                if request is self._connection_request and not self._stop_event.is_set():
                    self._wake_event.set()

            scan_args.update(queue_seconds=self.config.queue_seconds, on_broadcast_start=announce,
                             on_capacity_ready=capacity_ready)
        state = self.data_source.get_game_state(**scan_args)
        self._publish(state, request)
        if request is self._connection_request:
            self._prewarm_icons(state)
        return state

    def _prewarm_icons(self, state):
        from icon_loader import can_prewarm, prewarm_icon

        # Make at most two network attempts per poll, after advice is visible.
        full_build = self.config.view_mode == "full"
        extra = state.build_plan if full_build else ()
        counters = state.counter_items if self.config.show_counters and not full_build else ()
        replacement = getattr(state, "replacement", None)
        swap = (replacement.buy,) if full_build and replacement is not None else ()
        attempts = 0
        for item in (*swap, *state.recommended_items, *extra, *counters):
            if not can_prewarm(item.image_url):
                continue
            if prewarm_icon(item.image_url):
                self._icon_refresh.set()
            attempts += 1
            if attempts >= 2:
                break

    def _worker_loop(self) -> None:
        """Heavy polling in the background: DB, log tail, capture, OCR."""
        try:
            attach_to_default_desktop()
        except Exception:
            pass
        if self._stop_event.wait(0.8):
            return
        while not self._stop_event.is_set():
            self._wake_event.clear()
            request = self._connection_request
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
                    self._publish(GameState(source="advisor", scan_status="idle"), request)
                else:
                    self.poll_once()
            except Exception as err:
                print(f"[Worker] Exception in poll: {err}")
                self._publish(GameState(scan_status="error", last_error="Could not refresh the overlay.",
                                        generated_at=time.time()), request)
            delay = poll_interval(self.config, self._current_state,
                                  bool(getattr(self.data_source, "is_advisor", False)), running)
            self._wake_event.wait(timeout=delay)

    def _publish(self, state: GameState, request) -> None:
        if request is not self._connection_request:
            return
        try:
            self._queue.put_nowait((request, state))
        except queue.Full:
            try: self._queue.get_nowait(); self._queue.put_nowait((request, state))
            except queue.Empty: pass
