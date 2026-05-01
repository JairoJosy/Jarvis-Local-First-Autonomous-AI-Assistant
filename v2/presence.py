from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock

from jarvis.v2.schemas import PresenceMode, PresenceSignal, PresenceState


class PresenceStateMachine:
    """
    Presence mode state machine:
    - ActiveUse: background-first UI behavior.
    - IdleScreensaver: minimal visual mode.
    - LockedPrivacy: screensaver mode with privacy filtering.
    - SleepOffline: no local UI while offline/asleep.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._state = PresenceState(
            mode=PresenceMode.ACTIVE_USE,
            ui_foreground=False,
            reason="initialized",
            allow_sensitive_details=True,
            updated_at=datetime.now(timezone.utc),
        )

    def get_state(self) -> PresenceState:
        with self._lock:
            return self._state.model_copy(deep=True)

    def apply_signal(self, signal: PresenceSignal) -> PresenceState:
        with self._lock:
            mode = self._state.mode
            if signal.is_sleeping:
                mode = PresenceMode.SLEEP_OFFLINE
            elif signal.is_locked:
                mode = PresenceMode.LOCKED_PRIVACY
            elif not signal.is_user_active:
                mode = PresenceMode.IDLE_SCREENSAVER
            else:
                mode = PresenceMode.ACTIVE_USE

            allow_sensitive = mode == PresenceMode.ACTIVE_USE
            ui_foreground = mode in {PresenceMode.IDLE_SCREENSAVER, PresenceMode.LOCKED_PRIVACY}

            if mode == PresenceMode.ACTIVE_USE:
                ui_foreground = False
                if signal.explicit_reveal:
                    ui_foreground = True
                if signal.explicit_background:
                    ui_foreground = False
            elif signal.explicit_background:
                ui_foreground = False

            self._state = PresenceState(
                mode=mode,
                ui_foreground=ui_foreground,
                reason=signal.reason,
                allow_sensitive_details=allow_sensitive,
                updated_at=datetime.now(timezone.utc),
            )
            return self._state.model_copy(deep=True)

    def explicit_ui_reveal(self, reason: str = "manual_reveal") -> PresenceState:
        signal = PresenceSignal(
            is_user_active=True,
            explicit_reveal=True,
            reason=reason,
        )
        return self.apply_signal(signal)

    def explicit_background(self, reason: str = "manual_background") -> PresenceState:
        signal = PresenceSignal(
            is_user_active=True,
            explicit_background=True,
            reason=reason,
        )
        return self.apply_signal(signal)

