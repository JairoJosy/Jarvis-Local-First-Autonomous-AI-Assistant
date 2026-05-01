from __future__ import annotations

import re

from jarvis.v2.approvals import ApprovalCenter
from jarvis.v2.schemas import (
    ApprovalStatus,
    VoiceAuthConfirmRequest,
    VoiceCommandRequest,
    VoiceCommandResponse,
)


class VoiceSecurityService:
    SENSITIVE_PATTERNS = (
        r"\bpay\b",
        r"\btransfer\b",
        r"\bwire\b",
        r"\bshutdown\b",
        r"\bdelete\b",
        r"\bpurchase\b",
        r"\bsend\b",
    )

    def __init__(self, approvals: ApprovalCenter, default_pin: str = "2580", confirm_phrase: str = "confirm") -> None:
        self._approvals = approvals
        self._default_pin = default_pin
        self._confirm_phrase = confirm_phrase.lower()

    def handle_voice_command(self, request: VoiceCommandRequest) -> VoiceCommandResponse:
        if not request.wake_word_detected:
            return VoiceCommandResponse(
                accepted=False,
                message="Wake word not detected. Say the wake word and try again.",
            )

        if self._is_sensitive(request.transcript) and request.spoken_pin != self._default_pin:
            card = self._approvals.create_card(
                source="voice",
                summary=f"Sensitive voice command pending approval: {request.transcript[:120]}",
                risk_level="high",
                requires_pin=True,
                metadata={
                    "session_id": request.session_id,
                    "transcript": request.transcript,
                },
            )
            return VoiceCommandResponse(
                accepted=False,
                message="Sensitive voice command requires authentication.",
                requires_auth=True,
                approval_id=card.approval_id,
            )

        return VoiceCommandResponse(
            accepted=True,
            message="Voice command accepted.",
            requires_auth=False,
        )

    def confirm(self, request: VoiceAuthConfirmRequest) -> VoiceCommandResponse:
        card = self._approvals.get_card(request.approval_id)
        if card is None:
            return VoiceCommandResponse(accepted=False, message="Approval not found.")
        if card.status != ApprovalStatus.PENDING:
            return VoiceCommandResponse(accepted=False, message=f"Approval is {card.status.value}.")

        pin_ok = request.spoken_pin == self._default_pin
        phrase_ok = (request.confirm_phrase or "").strip().lower() == self._confirm_phrase
        if card.requires_pin and not (pin_ok or phrase_ok):
            return VoiceCommandResponse(
                accepted=False,
                message="Authentication failed. Provide spoken PIN or confirm phrase.",
                requires_auth=True,
                approval_id=card.approval_id,
            )

        approved = self._approvals.approve(card.approval_id)
        if approved is None:
            return VoiceCommandResponse(accepted=False, message="Approval no longer available.")
        return VoiceCommandResponse(
            accepted=True,
            message="Voice approval confirmed.",
            requires_auth=False,
            approval_id=approved.approval_id,
        )

    def _is_sensitive(self, transcript: str) -> bool:
        lowered = transcript.lower()
        return any(re.search(pattern, lowered) for pattern in self.SENSITIVE_PATTERNS)

