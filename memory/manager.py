from __future__ import annotations

import re
from typing import Any

from jarvis.config import Settings
from jarvis.schemas import EventFact, IntentType, MemoryContext, MemorySnippet

from .extractor import MemoryExtractor
from .short_term import ShortTermMemory
from .structured import StructuredMemoryStore
from .vector import VectorMemoryStore


class MemoryManager:
    def __init__(
        self,
        settings: Settings,
        *,
        short_term: ShortTermMemory | None = None,
        structured: StructuredMemoryStore | None = None,
        vector: VectorMemoryStore | None = None,
        extractor: MemoryExtractor | None = None,
    ) -> None:
        self._settings = settings
        self.short_term = short_term or ShortTermMemory(max_turns=settings.short_term_max_turns)
        self.structured = structured or StructuredMemoryStore(settings.sqlite_path, settings.timezone)
        self.vector = vector or VectorMemoryStore(settings)
        self.extractor = extractor or MemoryExtractor()

    def retrieve_context(self, *, session_id: str, user_text: str, intent: IntentType) -> MemoryContext:
        snippets: list[MemorySnippet] = []

        for turn in self.short_term.recent(session_id, limit=6):
            snippets.append(
                MemorySnippet(
                    source="history",
                    text=f'{turn["role"]}: {turn["text"]}',
                )
            )

        names = self._extract_name_candidates(user_text)
        for name in names:
            person = self.structured.get_person(name)
            if person:
                snippets.append(
                    MemorySnippet(
                        source="person",
                        ref_id=int(person["id"]),
                        text=self._format_person(person),
                    )
                )

        if intent == "memory_query" and not names:
            for person in self.structured.search_people(user_text, limit=2):
                snippets.append(
                    MemorySnippet(
                        source="person",
                        ref_id=int(person["id"]),
                        text=self._format_person(person),
                    )
                )

        if intent in {"memory_query", "chat"}:
            for event in self.structured.search_events(user_text, limit=3):
                snippets.append(
                    MemorySnippet(
                        source="event",
                        ref_id=int(event["id"]),
                        text=self._format_event(event),
                    )
                )

        for vector_id, score in self.vector.search(user_text, top_k=self._settings.semantic_top_k):
            metadata_batch = self.structured.get_vector_metadata([vector_id])
            if not metadata_batch:
                continue
            metadata = metadata_batch[0]
            snippets.append(
                MemorySnippet(
                    source="semantic",
                    ref_id=vector_id,
                    score=score,
                    text=metadata["text"],
                )
            )

        unique: list[MemorySnippet] = []
        seen_texts: set[str] = set()
        for item in snippets:
            if item.text in seen_texts:
                continue
            seen_texts.add(item.text)
            unique.append(item)
        return MemoryContext(snippets=unique[: self._settings.memory_recent_limit])

    def update_after_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        user_text: str,
        assistant_text: str,
        intent: IntentType,
        tool_action: str | None = None,
        tool_success: bool | None = None,
    ) -> dict[str, Any]:
        self.short_term.add_turn(session_id, "user", user_text)
        self.short_term.add_turn(session_id, "assistant", assistant_text)

        last_person = self.short_term.get_state(session_id, "last_person_name")
        extraction = self.extractor.extract(user_text, last_person_name=last_person)
        if extraction.last_person_name:
            self.short_term.set_state(session_id, "last_person_name", extraction.last_person_name)

        person_ids: list[int] = []
        event_ids: list[int] = []

        for person_fact in extraction.facts.people:
            saved = self.structured.upsert_person(person_fact)
            person_ids.append(int(saved["id"]))

        for event_fact in extraction.facts.events:
            event_payload = EventFact(
                event=event_fact.event,
                location=event_fact.location,
                description=event_fact.description,
                source_turn_id=turn_id,
            )
            event_id = self.structured.add_event(event_payload)
            event_ids.append(event_id)
            self.structured.append_timeline(
                "event",
                f'Event: {event_payload.event} at {event_payload.location or "unknown location"}',
                {"event_id": event_id, "source_turn_id": turn_id},
            )

        self.structured.append_timeline(
            "user_turn",
            user_text[:200],
            {"turn_id": turn_id, "intent": intent},
        )

        if tool_action:
            summary = f"Tool executed: {tool_action} ({'success' if tool_success else 'failed'})"
            self.structured.append_timeline(
                "tool",
                summary,
                {"turn_id": turn_id, "tool_action": tool_action, "success": bool(tool_success)},
            )

        semantic_stored = False
        if self.should_store_meaningful(user_text, extraction.facts.people, extraction.facts.events):
            ref_type = "turn"
            ref_id: int | None = None
            if person_ids:
                ref_type = "person"
                ref_id = person_ids[0]
            elif event_ids:
                ref_type = "event"
                ref_id = event_ids[0]
            vector_id = self.structured.insert_vector_metadata(
                text=user_text,
                ref_type=ref_type,
                ref_id=ref_id,
                source_turn_id=turn_id,
            )
            self.vector.add(vector_id=vector_id, text=user_text)
            semantic_stored = True

        return {
            "person_ids": person_ids,
            "event_ids": event_ids,
            "semantic_stored": semantic_stored,
        }

    def query_person(self, name: str) -> dict[str, Any] | None:
        return self.structured.get_person(name)

    def query_timeline(self, *, range_key: str, limit: int) -> list[dict[str, Any]]:
        return self.structured.get_timeline(range_key=range_key, limit=limit, local_tz=self._settings.timezone)

    def semantic_search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        pairs = self.vector.search(query, top_k=limit)
        ids = [item[0] for item in pairs]
        scores = {item[0]: item[1] for item in pairs}
        metadata = self.structured.get_vector_metadata(ids)
        for item in metadata:
            item["score"] = scores.get(int(item["id"]), 0.0)
        return metadata

    def should_store_meaningful(self, text: str, people: list[Any], events: list[Any]) -> bool:
        if people or events:
            return True
        return self.vector.should_store_semantic(text)

    def _extract_name_candidates(self, text: str) -> list[str]:
        return list(dict.fromkeys(re.findall(r"\b([A-Z][a-z]+)\b", text)))

    def _format_person(self, payload: dict[str, Any]) -> str:
        traits = ", ".join(payload.get("traits") or []) or "none"
        return (
            f'{payload["name"]}: profession={payload.get("profession") or "unknown"}, '
            f'location={payload.get("location") or "unknown"}, traits={traits}'
        )

    def _format_event(self, payload: dict[str, Any]) -> str:
        return (
            f'Event "{payload.get("event")}" at {payload.get("location") or "unknown"} '
            f'({payload.get("timestamp_local")}) - {payload.get("description")}'
        )

