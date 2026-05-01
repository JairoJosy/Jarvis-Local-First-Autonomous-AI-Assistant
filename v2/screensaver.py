from __future__ import annotations

from datetime import datetime, timezone

from jarvis.v2.schemas import PresenceMode, PresenceState


class ScreenSaverRenderService:
    """
    Backend render model for a native .scr shell.
    The native frontend can consume this model and paint minimal black/blue-green waves.
    """

    def render_model(
        self,
        *,
        state: PresenceState,
        transcript: str | None = None,
        status_text: str | None = None,
        answer_text: str | None = None,
        topic: str | None = None,
        top_reminder: str | None = None,
        weather_summary: str | None = None,
    ) -> dict:
        animation = "ambient_waves"
        if topic:
            normalized = topic.lower()
            if "weather" in normalized:
                animation = "weather_particles"
            elif "time" in normalized or "clock" in normalized:
                animation = "clock_pulse"
            elif "system" in normalized:
                animation = "system_grid"

        return {
            "mode": state.mode.value,
            "is_screensaver": state.mode in {PresenceMode.IDLE_SCREENSAVER, PresenceMode.LOCKED_PRIVACY},
            "theme": {
                "background": "#05070d",
                "wave_primary": "#1ea5ff",
                "wave_secondary": "#1fd5a2",
                "accent": "#77e0ff",
            },
            "widgets": {
                "clock": datetime.now(timezone.utc).isoformat(),
                "weather": weather_summary or "Weather unavailable",
                "top_reminder": top_reminder or "",
                "transcript": transcript or "",
                "status": status_text or "",
                "answer": answer_text or "",
            },
            "animation": animation,
            "privacy_filtered": not state.allow_sensitive_details,
        }

