from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from typing import Iterator
from uuid import uuid4

from jarvis.v2.schemas import ApprovalCard, ApprovalStatus


class ApprovalCenter:
    def __init__(self, db_path: Path | None = None, *, encryption_secret: str | None = None) -> None:
        self._db_path = db_path
        self._fernet = self._build_fernet(encryption_secret)
        self._lock = Lock()
        self._cards: dict[str, ApprovalCard] = {}
        if self._db_path:
            self._init_db()
            self._load_cards()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        assert self._db_path is not None
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS v2_approvals (
                  approval_id TEXT PRIMARY KEY,
                  payload TEXT NOT NULL,
                  encrypted INTEGER NOT NULL DEFAULT 0
                )
                """
            )

    def create_card(
        self,
        *,
        source: str,
        summary: str,
        risk_level: str,
        requires_pin: bool = False,
        metadata: dict[str, Any] | None = None,
        ttl_minutes: int | None = 30,
    ) -> ApprovalCard:
        now = datetime.now(timezone.utc)
        expires_at = None
        if ttl_minutes is not None:
            expires_at = now + timedelta(minutes=ttl_minutes)
        card = ApprovalCard(
            approval_id=uuid4().hex[:12],
            source=source,  # type: ignore[arg-type]
            summary=summary,
            risk_level=risk_level,  # type: ignore[arg-type]
            requires_pin=requires_pin,
            status=ApprovalStatus.PENDING,
            created_at=now,
            expires_at=expires_at,
            metadata=metadata or {},
        )
        with self._lock:
            self._cards[card.approval_id] = card
            self._save_card_locked(card)
        return card

    def get_card(self, approval_id: str) -> ApprovalCard | None:
        with self._lock:
            card = self._cards.get(approval_id)
        if card is None:
            return None
        if self._is_expired(card):
            return self._expire(card.approval_id)
        return card.model_copy(deep=True)

    def list_pending(self) -> list[ApprovalCard]:
        with self._lock:
            cards = list(self._cards.values())
        active: list[ApprovalCard] = []
        for card in cards:
            if self._is_expired(card):
                self._expire(card.approval_id)
                continue
            if card.status == ApprovalStatus.PENDING:
                active.append(card.model_copy(deep=True))
        return sorted(active, key=lambda c: c.created_at, reverse=True)

    def approve(self, approval_id: str) -> ApprovalCard | None:
        with self._lock:
            card = self._cards.get(approval_id)
            if card is None:
                return None
            if self._is_expired(card):
                card = self._expire_locked(approval_id)
                return card
            card.status = ApprovalStatus.APPROVED
            self._cards[approval_id] = card
            self._save_card_locked(card)
            return card.model_copy(deep=True)

    def deny(self, approval_id: str) -> ApprovalCard | None:
        with self._lock:
            card = self._cards.get(approval_id)
            if card is None:
                return None
            if self._is_expired(card):
                card = self._expire_locked(approval_id)
                return card
            card.status = ApprovalStatus.DENIED
            self._cards[approval_id] = card
            self._save_card_locked(card)
            return card.model_copy(deep=True)

    def _expire(self, approval_id: str) -> ApprovalCard | None:
        with self._lock:
            return self._expire_locked(approval_id)

    def _expire_locked(self, approval_id: str) -> ApprovalCard | None:
        card = self._cards.get(approval_id)
        if card is None:
            return None
        card.status = ApprovalStatus.EXPIRED
        self._cards[approval_id] = card
        self._save_card_locked(card)
        return card.model_copy(deep=True)

    def _is_expired(self, card: ApprovalCard) -> bool:
        if card.expires_at is None:
            return False
        return datetime.now(timezone.utc) > card.expires_at

    def _load_cards(self) -> None:
        if self._db_path is None:
            return
        with self._conn() as conn:
            rows = conn.execute("SELECT payload, encrypted FROM v2_approvals").fetchall()
        with self._lock:
            for row in rows:
                try:
                    payload = self._decode_payload(row["payload"], bool(row["encrypted"]))
                    card = ApprovalCard.model_validate(payload)
                    self._cards[card.approval_id] = card
                except Exception:
                    continue

    def _save_card_locked(self, card: ApprovalCard) -> None:
        if self._db_path is None:
            return
        payload, encrypted = self._encode_payload(card.model_dump(mode="json"))
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO v2_approvals (approval_id, payload, encrypted)
                VALUES (?, ?, ?)
                ON CONFLICT(approval_id) DO UPDATE SET payload = excluded.payload, encrypted = excluded.encrypted
                """,
                (card.approval_id, payload, int(encrypted)),
            )

    def _encode_payload(self, payload: dict[str, Any]) -> tuple[str, bool]:
        raw = json.dumps(payload)
        if not self._fernet:
            return raw, False
        token = self._fernet.encrypt(raw.encode("utf-8")).decode("utf-8")
        return token, True

    def _decode_payload(self, payload: str, encrypted: bool) -> dict[str, Any]:
        if encrypted and self._fernet:
            return json.loads(self._fernet.decrypt(payload.encode("utf-8")).decode("utf-8"))
        if encrypted and not self._fernet:
            raise ValueError("Encrypted approval cannot be decoded without cryptography/secret.")
        return json.loads(payload)

    def _build_fernet(self, secret: str | None):
        if not secret:
            return None
        try:
            from cryptography.fernet import Fernet  # type: ignore
        except Exception:
            return None
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
        return Fernet(key)
