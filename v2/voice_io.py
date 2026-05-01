from __future__ import annotations

import base64
import html
import platform
import subprocess
import tempfile
import wave
from pathlib import Path
from shutil import which
from uuid import uuid4

from jarvis.config import Settings
from jarvis.v2.schemas import VoiceInputRequest, VoiceInputResponse, VoiceOutputRequest, VoiceOutputResponse


class VoiceIOService:
    """
    Voice input/output adapter.

    v2.6 supports transcript-backed voice input and Windows local speech output.
    Raw audio STT is intentionally treated as partial until a real recognizer is configured.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings
        self._voice_dir = (settings.data_dir / "voice") if settings else Path(tempfile.gettempdir()) / "jarvis_voice"
        self._voice_dir.mkdir(parents=True, exist_ok=True)

    def transcribe(self, request: VoiceInputRequest) -> VoiceInputResponse:
        if request.transcript_hint:
            return VoiceInputResponse(
                accepted=True,
                transcript=request.transcript_hint.strip(),
                confidence=0.96,
                engine="transcript_hint",
                message="Transcript accepted from client-provided voice hint.",
            )

        if request.audio_base64 and request.mime_type == "text/plain":
            try:
                decoded = base64.b64decode(request.audio_base64).decode("utf-8").strip()
            except (ValueError, UnicodeDecodeError) as exc:
                return VoiceInputResponse(
                    accepted=False,
                    confidence=0.0,
                    engine="text_plain_base64",
                    message=f"Could not decode text/plain voice input: {exc}",
                )
            if decoded:
                return VoiceInputResponse(
                    accepted=True,
                    transcript=decoded,
                    confidence=0.9,
                    engine="text_plain_base64",
                    message="Transcript decoded from text/plain payload.",
                )

        if request.audio_base64:
            return self._transcribe_audio(request)

        return VoiceInputResponse(
            accepted=False,
            confidence=0.0,
            engine="unconfigured_stt",
            message="Audio speech-to-text is partial: configure an STT adapter or send transcript_hint.",
            warnings=["Raw audio transcription is not implemented in the current local build."],
        )

    def synthesize(self, request: VoiceOutputRequest) -> VoiceOutputResponse:
        ssml = self._ssml(request.text, voice=request.voice)
        estimate = self._duration_estimate_ms(request.text)
        response = VoiceOutputResponse(
            accepted=True,
            message="Speech output prepared.",
            text=request.text,
            voice=request.voice,
            engine="speech_payload",
            spoken_locally=False,
            ssml=ssml,
            duration_ms_estimate=estimate,
        )
        if request.speak_locally:
            return self._speak_locally(request, response)
        return response

    def _transcribe_audio(self, request: VoiceInputRequest) -> VoiceInputResponse:
        try:
            audio_bytes = base64.b64decode(request.audio_base64 or "")
        except ValueError as exc:
            return VoiceInputResponse(
                accepted=False,
                engine="audio_base64",
                message=f"Could not decode audio payload: {exc}",
            )

        suffix = {
            "audio/wav": ".wav",
            "audio/mpeg": ".mp3",
            "audio/webm": ".webm",
            "audio/ogg": ".ogg",
        }.get(request.mime_type, ".audio")
        audio_path = self._voice_dir / f"voice_input_{uuid4().hex[:12]}{suffix}"
        audio_path.write_bytes(audio_bytes)

        vosk_result = self._try_vosk(audio_path, request)
        if vosk_result is not None:
            return vosk_result

        whisper_result = self._try_whisper_cli(audio_path, request)
        if whisper_result is not None:
            return whisper_result

        return VoiceInputResponse(
            accepted=False,
            confidence=0.0,
            engine="unconfigured_stt",
            message="No real STT adapter is configured or available for this audio payload.",
            warnings=[
                "Install/configure Vosk with JARVIS_VOSK_MODEL_PATH or install a whisper CLI.",
                f"Audio payload was stored temporarily at {audio_path}",
            ],
        )

    def _try_vosk(self, audio_path: Path, request: VoiceInputRequest) -> VoiceInputResponse | None:
        if request.mime_type != "audio/wav" or not self._settings or not self._settings.vosk_model_path:
            return None
        try:
            from vosk import KaldiRecognizer, Model  # type: ignore
        except Exception:
            return None
        try:
            with wave.open(str(audio_path), "rb") as audio:
                model = Model(str(self._settings.vosk_model_path))
                recognizer = KaldiRecognizer(model, audio.getframerate())
                chunks: list[str] = []
                while True:
                    data = audio.readframes(4000)
                    if not data:
                        break
                    if recognizer.AcceptWaveform(data):
                        chunks.append(recognizer.Result())
                chunks.append(recognizer.FinalResult())
        except Exception as exc:
            return VoiceInputResponse(
                accepted=False,
                confidence=0.0,
                engine="vosk",
                message=f"Vosk transcription failed: {exc}",
            )

        import json

        texts = []
        for chunk in chunks:
            try:
                text = json.loads(chunk).get("text", "")
            except Exception:
                text = ""
            if text:
                texts.append(text)
        transcript = " ".join(texts).strip()
        return VoiceInputResponse(
            accepted=bool(transcript),
            transcript=transcript,
            confidence=0.82 if transcript else 0.0,
            engine="vosk",
            message="Audio transcribed with local Vosk." if transcript else "Vosk returned no transcript.",
        )

    def _try_whisper_cli(self, audio_path: Path, request: VoiceInputRequest) -> VoiceInputResponse | None:
        if not self._settings:
            return None
        whisper_cmd = self._settings.whisper_cli_path
        if which(whisper_cmd) is None:
            return None
        output_dir = self._voice_dir / "whisper"
        output_dir.mkdir(parents=True, exist_ok=True)
        command = [
            whisper_cmd,
            str(audio_path),
            "--language",
            request.language,
            "--output_format",
            "txt",
            "--output_dir",
            str(output_dir),
        ]
        try:
            subprocess.run(command, check=True, timeout=120, capture_output=True, text=True)
        except Exception as exc:
            return VoiceInputResponse(
                accepted=False,
                confidence=0.0,
                engine="whisper_cli",
                message=f"Whisper CLI transcription failed: {exc}",
            )
        txt_path = output_dir / f"{audio_path.stem}.txt"
        transcript = txt_path.read_text(encoding="utf-8").strip() if txt_path.exists() else ""
        return VoiceInputResponse(
            accepted=bool(transcript),
            transcript=transcript,
            confidence=0.86 if transcript else 0.0,
            engine="whisper_cli",
            message="Audio transcribed with whisper CLI." if transcript else "Whisper CLI returned no transcript.",
        )

    def _speak_locally(self, request: VoiceOutputRequest, response: VoiceOutputResponse) -> VoiceOutputResponse:
        if platform.system().lower() != "windows":
            pyttsx_result = self._try_pyttsx3(request, response)
            if pyttsx_result is not None:
                return pyttsx_result
            response.warnings.append("Local speech playback currently supports Windows SAPI only.")
            response.message = "Speech payload prepared; local playback is unavailable on this OS."
            return response

        text_b64 = base64.b64encode(request.text.encode("utf-8")).decode("ascii")
        script = (
            "$bytes=[Convert]::FromBase64String('" + text_b64 + "');"
            "$text=[Text.Encoding]::UTF8.GetString($bytes);"
            "Add-Type -AssemblyName System.Speech;"
            "$speaker=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            "$speaker.Speak($text);"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                check=True,
                timeout=20,
                capture_output=True,
                text=True,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            response.warnings.append(f"Windows SAPI playback failed: {exc}")
            response.message = "Speech payload prepared, but local playback failed."
            response.engine = "windows_sapi_failed"
            return response

        return response.model_copy(
            update={
                "message": "Speech output spoken locally.",
                "engine": "windows_sapi",
                "spoken_locally": True,
            }
        )

    def _try_pyttsx3(self, request: VoiceOutputRequest, response: VoiceOutputResponse) -> VoiceOutputResponse | None:
        try:
            import pyttsx3  # type: ignore
        except Exception:
            return None
        try:
            engine = pyttsx3.init()
            engine.say(request.text)
            engine.runAndWait()
        except Exception as exc:
            response.warnings.append(f"pyttsx3 playback failed: {exc}")
            return response.model_copy(update={"engine": "pyttsx3_failed", "message": "Speech payload prepared, but pyttsx3 playback failed."})
        return response.model_copy(
            update={
                "message": "Speech output spoken locally.",
                "engine": "pyttsx3",
                "spoken_locally": True,
            }
        )

    def _ssml(self, text: str, *, voice: str) -> str:
        rate = {
            "calm": "slow",
            "clear": "medium",
            "energetic": "fast",
            "default": "medium",
        }[voice]
        return f"<speak><prosody rate=\"{rate}\">{html.escape(text)}</prosody></speak>"

    def _duration_estimate_ms(self, text: str) -> int:
        words = max(1, len(text.split()))
        words_per_minute = 155
        return int((words / words_per_minute) * 60_000)
