from __future__ import annotations

import base64
import threading
from typing import Callable

from jarvis.v2.schemas import VoiceInputRequest, VoiceListenerStatus
from jarvis.v2.voice_io import VoiceIOService


class VoiceListenerService:
    """
    Optional live microphone listener. It uses speech_recognition for microphone
    capture when installed and routes WAV chunks through VoiceIOService.
    """

    def __init__(self, voice_io: VoiceIOService, on_transcript: Callable[[VoiceInputRequest], None] | None = None) -> None:
        self._voice_io = voice_io
        self._on_transcript = on_transcript
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._status = VoiceListenerStatus(
            running=False,
            engine="speech_recognition+voice_io",
            wake_word="jarvis",
            warnings=[],
        )

    def start(self, *, session_id: str, wake_word: str = "jarvis") -> VoiceListenerStatus:
        with self._lock:
            if self._status.running:
                return self._status.model_copy(deep=True)
            self._stop.clear()
            self._status.running = True
            self._status.wake_word = wake_word.lower()
            self._status.last_error = None
            self._thread = threading.Thread(
                target=self._run,
                kwargs={"session_id": session_id, "wake_word": wake_word.lower()},
                daemon=True,
            )
            self._thread.start()
            return self._status.model_copy(deep=True)

    def stop(self) -> VoiceListenerStatus:
        self._stop.set()
        with self._lock:
            self._status.running = False
            return self._status.model_copy(deep=True)

    def status(self) -> VoiceListenerStatus:
        with self._lock:
            return self._status.model_copy(deep=True)

    def _run(self, *, session_id: str, wake_word: str) -> None:
        try:
            import speech_recognition as sr  # type: ignore
        except Exception as exc:
            self._fail(f"speech_recognition is not installed or microphone support is unavailable: {exc}")
            return

        recognizer = sr.Recognizer()
        try:
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                while not self._stop.is_set():
                    audio = recognizer.listen(source, timeout=1, phrase_time_limit=8)
                    wav_b64 = base64.b64encode(audio.get_wav_data()).decode("ascii")
                    transcription = self._voice_io.transcribe(
                        VoiceInputRequest(
                            session_id=session_id,
                            audio_base64=wav_b64,
                            mime_type="audio/wav",
                            route_to_command=False,
                        )
                    )
                    if transcription.accepted:
                        with self._lock:
                            self._status.last_transcript = transcription.transcript
                        if wake_word in transcription.transcript.lower() and self._on_transcript:
                            self._on_transcript(
                                VoiceInputRequest(
                                    session_id=session_id,
                                    transcript_hint=transcription.transcript,
                                    wake_word_detected=True,
                                    route_to_command=True,
                                )
                            )
        except Exception as exc:
            if not self._stop.is_set():
                self._fail(str(exc))
                return
        finally:
            with self._lock:
                self._status.running = False

    def _fail(self, error: str) -> None:
        with self._lock:
            self._status.running = False
            self._status.last_error = error
            if error not in self._status.warnings:
                self._status.warnings.append(error)
