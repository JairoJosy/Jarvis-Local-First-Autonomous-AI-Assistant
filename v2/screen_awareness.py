from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4

from jarvis.v2.schemas import (
    PrivacyMaskReport,
    ScreenCaptureRequest,
    ScreenCaptureResponse,
    SamplingMode,
    ScreenContextSnapshot,
    ScreenExplainRequest,
    ScreenExplainResponse,
    ScreenObservationControlRequest,
    ScreenObservationStatus,
)


class ScreenAwarenessService:
    """
    Local-first screen awareness service.
    This implementation keeps processing in-memory and stores only masked, ephemeral summaries.
    """

    SENSITIVE_APP_KEYWORDS = (
        "bank",
        "wallet",
        "password",
        "1password",
        "keepass",
        "bitwarden",
        "private",
    )

    MASK_PATTERNS = {
        "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "otp": re.compile(r"\b\d{4,8}\b"),
        "card": re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
        "password": re.compile(r"(?i)(password|passcode|pin)\s*[:=]\s*\S+"),
    }

    def __init__(self, data_dir: Path | None = None, *, tesseract_cmd: str | None = None) -> None:
        self._lock = Lock()
        self._data_dir = data_dir or Path("data")
        self._tesseract_cmd = tesseract_cmd
        self._screen_dir = self._data_dir / "screen"
        self._screen_dir.mkdir(parents=True, exist_ok=True)
        self._privacy_override = False
        self._observer_stop = threading.Event()
        self._observer_thread: threading.Thread | None = None
        self._observer_status = ScreenObservationStatus(running=False, interval_seconds=5.0, captures=0)
        self._last_snapshot = ScreenContextSnapshot(
            timestamp=datetime.now(timezone.utc),
            mode=SamplingMode.LOW,
            sampling_hz=0.5,
            privacy_mode_enabled=False,
            sensitive_app_detected=False,
            deep_inspection_paused=False,
            app_name=None,
            ocr_text_excerpt="",
            ui_elements=[],
            mask_report=PrivacyMaskReport(masked_fields=0),
        )

    def set_privacy_mode(self, enabled: bool) -> ScreenContextSnapshot:
        with self._lock:
            self._privacy_override = enabled
            self._last_snapshot.privacy_mode_enabled = enabled
            self._last_snapshot.deep_inspection_paused = enabled or self._last_snapshot.sensitive_app_detected
            self._last_snapshot.timestamp = datetime.now(timezone.utc)
            return self._last_snapshot.model_copy(deep=True)

    def capture_screen(self, request: ScreenCaptureRequest) -> ScreenCaptureResponse:
        warnings: list[str] = []
        try:
            from PIL import ImageStat  # type: ignore
            from PIL import ImageGrab  # type: ignore
        except Exception as exc:
            snapshot = self.state()
            return ScreenCaptureResponse(
                captured=False,
                message=f"Screen capture requires Pillow/ImageGrab: {exc}",
                snapshot=snapshot,
                warnings=["Install the screen extra and run on a desktop session that permits capture."],
            )

        try:
            image = ImageGrab.grab()
        except Exception as exc:
            snapshot = self.state()
            return ScreenCaptureResponse(
                captured=False,
                message=f"Screen capture failed: {exc}",
                snapshot=snapshot,
                warnings=["The OS/session may block screenshot capture."],
            )

        image_path: Path | None = None
        if request.save_debug_image:
            image_path = self._screen_dir / f"screen_{uuid4().hex[:12]}.png"
            image.save(image_path)

        ocr_text = ""
        if request.include_ocr:
            ocr_text, ocr_warnings = self._ocr_image(image)
            warnings.extend(ocr_warnings)

        masked_text, report = self._mask_text(ocr_text)
        ui_elements = self._extract_ui_elements(masked_text)
        vision_summary = self._vision_summary(image, ImageStat)
        with self._lock:
            snapshot = ScreenContextSnapshot(
                timestamp=datetime.now(timezone.utc),
                mode=SamplingMode.BURST if request.burst else SamplingMode.LOW,
                sampling_hz=2.0 if request.burst else 0.5,
                privacy_mode_enabled=self._privacy_override,
                sensitive_app_detected=False,
                deep_inspection_paused=self._privacy_override,
                ocr_text_excerpt=masked_text[:250],
                ui_elements=ui_elements,
                mask_report=report,
            )
            self._last_snapshot = snapshot
        return ScreenCaptureResponse(
            captured=True,
            message="Screen captured and analyzed.",
            snapshot=snapshot,
            image_path=str(image_path) if image_path else None,
            ocr_text=masked_text,
            vision_summary=vision_summary,
            warnings=warnings,
        )

    def control_observation(self, request: ScreenObservationControlRequest) -> ScreenObservationStatus:
        if request.action == "stop":
            self._observer_stop.set()
            with self._lock:
                self._observer_status.running = False
                return self._observer_status.model_copy(deep=True)

        with self._lock:
            if self._observer_status.running:
                return self._observer_status.model_copy(deep=True)
            self._observer_stop.clear()
            self._observer_status.running = True
            self._observer_status.interval_seconds = request.interval_seconds
            self._observer_status.last_error = None
            self._observer_thread = threading.Thread(
                target=self._observe_loop,
                args=(request.interval_seconds, request.include_ocr),
                daemon=True,
            )
            self._observer_thread.start()
            return self._observer_status.model_copy(deep=True)

    def observation_status(self) -> ScreenObservationStatus:
        with self._lock:
            return self._observer_status.model_copy(deep=True)

    def update_from_presence(self, *, active: bool, locked: bool) -> ScreenContextSnapshot:
        with self._lock:
            mode = SamplingMode.LOW
            hz = 0.5 if active else 0.2
            if locked:
                hz = 0.1
            self._last_snapshot.mode = mode
            self._last_snapshot.sampling_hz = hz
            self._last_snapshot.timestamp = datetime.now(timezone.utc)
            return self._last_snapshot.model_copy(deep=True)

    def state(self) -> ScreenContextSnapshot:
        with self._lock:
            return self._last_snapshot.model_copy(deep=True)

    def explain(self, request: ScreenExplainRequest) -> ScreenExplainResponse:
        text = request.visible_text or ""
        app_name = (request.app_name or "").strip() or None

        sensitive_app = self._is_sensitive_app(app_name)
        masked_text, report = self._mask_text(text)
        ui_elements = self._extract_ui_elements(masked_text)

        with self._lock:
            mode = SamplingMode.BURST if request.burst else SamplingMode.LOW
            hz = 2.0 if mode == SamplingMode.BURST else 0.5
            privacy_enabled = self._privacy_override or sensitive_app
            deep_paused = privacy_enabled and sensitive_app

            snapshot = ScreenContextSnapshot(
                timestamp=datetime.now(timezone.utc),
                mode=mode,
                sampling_hz=hz,
                privacy_mode_enabled=privacy_enabled,
                sensitive_app_detected=sensitive_app,
                deep_inspection_paused=deep_paused,
                app_name=app_name,
                ocr_text_excerpt=masked_text[:250],
                ui_elements=ui_elements,
                mask_report=report,
            )
            self._last_snapshot = snapshot

        summary = self._build_summary(snapshot, request.prompt)
        return ScreenExplainResponse(
            summary=summary,
            masked_text=masked_text,
            mask_report=report,
            snapshot=snapshot,
        )

    def _build_summary(self, snapshot: ScreenContextSnapshot, prompt: str) -> str:
        if snapshot.deep_inspection_paused:
            return (
                "Sensitive application detected. Deep analysis is paused for privacy. "
                "I can still provide high-level guidance."
            )
        if snapshot.ui_elements:
            element_preview = ", ".join(snapshot.ui_elements[:4])
            return f"{prompt} I can see likely UI elements: {element_preview}."
        if snapshot.ocr_text_excerpt:
            return f"{prompt} Screen appears text-focused. Preview: {snapshot.ocr_text_excerpt[:120]}"
        return f"{prompt} I currently see limited visible text."

    def _observe_loop(self, interval_seconds: float, include_ocr: bool) -> None:
        while not self._observer_stop.is_set():
            response = self.capture_screen(
                ScreenCaptureRequest(include_ocr=include_ocr, save_debug_image=False, burst=False)
            )
            with self._lock:
                self._observer_status.captures += 1 if response.captured else 0
                self._observer_status.last_capture_at = datetime.now(timezone.utc)
                self._observer_status.last_snapshot = response.snapshot
                self._observer_status.last_error = None if response.captured else response.message
            self._observer_stop.wait(interval_seconds)
        with self._lock:
            self._observer_status.running = False

    def _ocr_image(self, image) -> tuple[str, list[str]]:
        try:
            import pytesseract  # type: ignore

            if self._tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = self._tesseract_cmd
            return pytesseract.image_to_string(image).strip(), []
        except Exception as exc:
            return "", [f"OCR unavailable or failed: {exc}"]

    def _vision_summary(self, image, image_stat_module) -> str:
        try:
            stat = image_stat_module.Stat(image.convert("L"))
            brightness = float(stat.mean[0])
            width, height = image.size
            tone = "bright" if brightness > 170 else "dark" if brightness < 80 else "balanced"
            return f"{width}x{height} screen capture with {tone} overall brightness."
        except Exception as exc:
            return f"Basic vision analysis failed: {exc}"

    def _is_sensitive_app(self, app_name: str | None) -> bool:
        if not app_name:
            return False
        lowered = app_name.lower()
        return any(keyword in lowered for keyword in self.SENSITIVE_APP_KEYWORDS)

    def _mask_text(self, text: str) -> tuple[str, PrivacyMaskReport]:
        masked = text
        categories: dict[str, int] = {}
        total = 0
        for category, pattern in self.MASK_PATTERNS.items():
            count = len(pattern.findall(masked))
            if count <= 0:
                continue
            categories[category] = count
            total += count
            masked = pattern.sub(f"[{category.upper()}_MASKED]", masked)
        report = PrivacyMaskReport(
            masked_fields=total,
            categories=categories,
            retention_hours=24,
            ephemeral=True,
        )
        return masked, report

    def _extract_ui_elements(self, text: str) -> list[str]:
        keywords = [
            "button",
            "menu",
            "settings",
            "form",
            "login",
            "dashboard",
            "timeline",
            "panel",
            "editor",
            "terminal",
            "browser",
            "canvas",
        ]
        lowered = text.lower()
        found = [k for k in keywords if k in lowered]
        if found:
            return found
        words = re.findall(r"[A-Za-z]{4,}", text)
        return list(dict.fromkeys(words[:5]))
