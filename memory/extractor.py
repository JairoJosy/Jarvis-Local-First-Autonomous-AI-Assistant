from __future__ import annotations

import re
from dataclasses import dataclass

from jarvis.schemas import EventFact, ExtractedFacts, PersonFact


@dataclass
class ExtractionResult:
    facts: ExtractedFacts
    last_person_name: str | None


class MemoryExtractor:
    PRONOUN_NAMES = {"he", "she", "they"}
    MEET_RE = re.compile(r"\b(?:met|meet)\s+(?P<name>[A-Z][a-z]+)\b")
    NAME_PROFESSION_RE = re.compile(
        r"\b(?P<name>[A-Z][a-z]+)\s+is\s+(?:an?\s+)?(?P<profession>[a-z][a-z\s]{1,40})\b",
        flags=re.IGNORECASE,
    )
    PRONOUN_PROFESSION_RE = re.compile(
        r"\b(?:he|she)\s+is\s+(?:an?\s+)?(?P<profession>[a-z][a-z\s]{1,40})\b",
        flags=re.IGNORECASE,
    )
    ALSO_TRAITS_RE = re.compile(
        r"\b(?:he|she|[A-Z][a-z]+)\s+is\s+also\s+(?:very\s+)?(?P<traits>[a-z][a-z\s,]+)",
        flags=re.IGNORECASE,
    )
    STRONG_TRAIT_RE = re.compile(
        r"\b(?:he|she|[A-Z][a-z]+)\s+is\s+(?:very\s+)?(?P<trait>smart|kind|helpful|creative|calm|friendly)\b",
        flags=re.IGNORECASE,
    )
    LOCATION_EVENT_RE = re.compile(
        r"\bi\s+(?P<verb>went to|visited|traveled to|travelled to)\s+(?P<location>[A-Za-z][A-Za-z\s]{1,60})",
        flags=re.IGNORECASE,
    )
    MEET_LOCATION_RE = re.compile(
        r"\bi\s+met\s+(?P<name>[A-Z][a-z]+)\s+at\s+(?P<location>[A-Za-z][A-Za-z\s]{1,60})",
        flags=re.IGNORECASE,
    )

    def extract(self, user_text: str, last_person_name: str | None = None) -> ExtractionResult:
        people: dict[str, dict[str, object]] = {}
        events: list[EventFact] = []
        current_person = last_person_name

        def ensure_person(name: str) -> dict[str, object]:
            bucket = people.setdefault(
                name,
                {
                    "name": name,
                    "profession": None,
                    "location": None,
                    "traits": set(),
                    "aliases": set(),
                },
            )
            return bucket

        for match in self.MEET_RE.finditer(user_text):
            name = match.group("name")
            ensure_person(name)
            current_person = name

        for match in self.NAME_PROFESSION_RE.finditer(user_text):
            name = match.group("name")
            if name.lower() in self.PRONOUN_NAMES:
                continue
            profession = self._normalize_phrase(match.group("profession"))
            if profession.startswith("also "):
                continue
            if profession:
                person = ensure_person(name)
                person["profession"] = profession
                current_person = name

        for match in self.PRONOUN_PROFESSION_RE.finditer(user_text):
            profession = self._normalize_phrase(match.group("profession"))
            if profession.startswith("also "):
                continue
            if profession and current_person:
                person = ensure_person(current_person)
                person["profession"] = profession

        for match in self.ALSO_TRAITS_RE.finditer(user_text):
            traits = self._split_traits(match.group("traits"))
            if traits and current_person:
                person = ensure_person(current_person)
                person["traits"].update(traits)

        for match in self.STRONG_TRAIT_RE.finditer(user_text):
            trait = self._normalize_phrase(match.group("trait"))
            if trait and current_person:
                person = ensure_person(current_person)
                person["traits"].add(trait)

        for match in self.LOCATION_EVENT_RE.finditer(user_text):
            verb = match.group("verb").lower()
            location = self._normalize_phrase(match.group("location"))
            event_name = "visit" if "visit" in verb else "travel"
            events.append(
                EventFact(
                    event=event_name,
                    location=location,
                    description=f"User {verb} {location}",
                )
            )

        for match in self.MEET_LOCATION_RE.finditer(user_text):
            name = match.group("name")
            location = self._normalize_phrase(match.group("location"))
            person = ensure_person(name)
            person["location"] = location
            current_person = name
            events.append(
                EventFact(
                    event="meeting",
                    location=location,
                    description=f"User met {name} at {location}",
                )
            )

        person_facts: list[PersonFact] = []
        for payload in people.values():
            person_facts.append(
                PersonFact(
                    name=str(payload["name"]),
                    profession=payload["profession"],
                    location=payload["location"],
                    traits=sorted(payload["traits"]),
                    aliases=sorted(payload["aliases"]),
                )
            )
        return ExtractionResult(
            facts=ExtractedFacts(people=person_facts, events=events),
            last_person_name=current_person,
        )

    def _split_traits(self, value: str) -> set[str]:
        parts = re.split(r",| and ", value)
        return {self._normalize_phrase(part) for part in parts if self._normalize_phrase(part)}

    def _normalize_phrase(self, value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().lower())
