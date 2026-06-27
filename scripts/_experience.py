#!/usr/bin/env python3
"""Experience accumulation for dream self-looping.

Stores structured lessons learned from dream operations in a single Markdown
file (``.wiki/dream/experiences.md``).  Deduplicates via SHA256 hashing of
normalised lesson text so the same mistake is not recorded twice — instead
its ``recurrence_count`` is incremented.

Capacity: capped at 100 entries; oldest single-occurrence entries evicted first.

Usage:
    from _experience import Experience, ExperienceStore

    store = ExperienceStore(wiki_dir)

    exp = Experience(
        category="merge",
        phase=3,
        context="Merged duplicate pages for '评审组'",
        outcome="rollback",
        lesson="Merging pages from different sources broke 6 wikilinks. "
               "Always run lint --auto-heal after merging.",
    )
    is_new = store.add(exp)   # False if duplicate → increments recurrence

    ctx = store.to_context(3)  # Markdown block for dream phase execution
"""

from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ── constants ────────────────────────────────────────────────────────────────

MAX_EXPERIENCES = 100
EXPERIENCES_FILE = "dream/experiences.md"

# ── data types ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Experience:
    """A single lesson learned during dream execution.  Immutable — updates
    create new instances."""

    category: str  # "merge" | "enrich" | "rollback" | "quality"
    phase: int     # 3 or 4
    context: str   # 1-2 sentences on what was attempted
    outcome: str   # "success" | "rollback" | "warning"
    lesson: str    # actionable lesson

    date: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    hash_id: str = ""
    recurrence_count: int = 1

    def __post_init__(self) -> None:
        if not self.hash_id:
            object.__setattr__(self, "hash_id", self._compute_hash())

    def _compute_hash(self) -> str:
        """SHA256 of normalised lesson text (first 16 hex chars)."""
        normalized = re.sub(r"\s+", " ", self.lesson.strip().lower())
        normalized = normalized.strip(".!?,;:，。！？；：")
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    def with_incremented_recurrence(self) -> "Experience":
        """Return a new Experience with recurrence_count + 1."""
        return Experience(
            category=self.category,
            phase=self.phase,
            context=self.context,
            outcome=self.outcome,
            lesson=self.lesson,
            date=self.date,
            hash_id=self.hash_id,
            recurrence_count=self.recurrence_count + 1,
        )

    @staticmethod
    def compute_hash_static(lesson: str) -> str:
        """Static version for external use."""
        normalized = re.sub(r"\s+", " ", lesson.strip().lower())
        normalized = normalized.strip(".!?,;:，。！？；：")
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]


# ── store ─────────────────────────────────────────────────────────────────────


class ExperienceStore:
    """Manages dream experiences with deduplication.

    Storage: ``.wiki/dream/experiences.md`` — YAML frontmatter + one section per
    experience.
    """

    def __init__(self, wiki_dir: Path) -> None:
        self._wiki_dir = wiki_dir
        self._path = wiki_dir / EXPERIENCES_FILE
        self._entries: list[Experience] = []
        self._load()

    # ── public API ────────────────────────────────────────────────────────

    def add(self, exp: Experience) -> bool:
        """Add an experience.  Returns False if it is a duplicate (recurrence
        incremented instead)."""
        for i, existing in enumerate(self._entries):
            if existing.hash_id == exp.hash_id:
                self._entries[i] = existing.with_incremented_recurrence()
                self._save()
                return False

        self._entries.append(exp)
        self._evict_if_needed()
        self._save()
        return True

    def load_for_phase(self, phase: int) -> list[Experience]:
        """Return experiences relevant to *phase*, newest first.

        Includes: same-phase experiences + frequently-recurring (>= 2) from any phase.
        """
        relevant = [
            e
            for e in self._entries
            if e.phase == phase or e.recurrence_count >= 2
        ]
        relevant.sort(key=lambda e: (e.recurrence_count, e.date), reverse=True)
        return relevant[:30]

    def to_context(self, phase: int) -> str:
        """Format experiences as a Markdown context block for dream execution.

        Example output::

            ## Prior Dream Experiences (Lessons Learned)

            - **[ROLLBACK]** (recurred 3×): Merging pages with different source
              prefixes breaks cross-references. Always update edges after merge.
              > Context: Phase 3 merge of coursepl-评审组 and projectb-评审组.
        """
        entries = self.load_for_phase(phase)
        if not entries:
            return ""

        lines = [
            "## Prior Dream Experiences (Lessons Learned)",
            "",
            "> The following lessons were recorded during previous dream runs.",
            "> Apply them when making modification decisions.",
            "",
        ]

        for e in entries:
            recur = (
                f"recurred {e.recurrence_count}×"
                if e.recurrence_count > 1
                else "once"
            )
            outcome_label = e.outcome.upper()
            lines.append(
                f"- **[{outcome_label}]** ({recur}): {e.lesson}"
            )
            if e.context:
                lines.append(f"  > Context: {e.context}")
            lines.append("")

        return "\n".join(lines)

    # ── internal ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load experiences from the markdown file."""
        if not self._path.is_file():
            return

        try:
            content = self._path.read_text(encoding="utf-8")
        except OSError:
            return

        sections = re.split(r"\n## Experience: ", content)
        for section in sections[1:]:
            exp = self._parse_section(section.strip())
            if exp:
                self._entries.append(exp)

    def _parse_section(self, text: str) -> Experience | None:
        """Parse a single experience section."""
        try:
            hash_id = text.split("\n", 1)[0].strip()
            lines = text.splitlines()

            category = ""
            phase = 0
            date_str = ""
            context = ""
            outcome = ""
            lesson_parts: list[str] = []
            recurrence = 1

            in_lesson = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("- **Category**:"):
                    category = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("- **Phase**:"):
                    try:
                        phase = int(stripped.split(":", 1)[1].strip())
                    except ValueError:
                        phase = 0
                elif stripped.startswith("- **Date**:"):
                    date_str = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("- **Context**:"):
                    context = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("- **Outcome**:"):
                    outcome = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("- **Lesson**:"):
                    lesson_parts.append(stripped.split(":", 1)[1].strip())
                    in_lesson = True
                elif stripped.startswith("- **Recurrence**:"):
                    try:
                        recurrence = int(stripped.split(":", 1)[1].strip())
                    except ValueError:
                        recurrence = 1
                    in_lesson = False
                elif in_lesson and stripped and not stripped.startswith("-"):
                    lesson_parts.append(stripped)

            if not category or not outcome:
                return None

            lesson = " ".join(lesson_parts).strip()
            if not lesson:
                return None

            return Experience(
                hash_id=hash_id,
                category=category,
                phase=phase,
                date=date_str,
                context=context,
                outcome=outcome,
                lesson=lesson,
                recurrence_count=recurrence,
            )
        except Exception:
            return None

    def _save(self) -> None:
        """Write all experiences back to the markdown file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        last_updated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        total = len(self._entries)

        lines = [
            "---",
            "dream_experiences: true",
            f'last_updated: "{last_updated}"',
            f"total_entries: {total}",
            "---",
            "",
            "# Dream Experiences",
            "",
            "Automatically recorded lessons from dream self-looping execution.",
            "",
        ]

        for exp in self._entries:
            lines.append(f"## Experience: {exp.hash_id}")
            lines.append(f"- **Category**: {exp.category}")
            lines.append(f"- **Phase**: {exp.phase}")
            lines.append(f"- **Date**: {exp.date}")
            lines.append(f"- **Context**: {exp.context}")
            lines.append(f"- **Outcome**: {exp.outcome}")
            lines.append(f"- **Lesson**: {exp.lesson}")
            lines.append(f"- **Recurrence**: {exp.recurrence_count}")
            lines.append("")

        try:
            self._path.write_text("\n".join(lines), encoding="utf-8")
        except OSError as exc:
            print(f"  [dream/experience] failed to save: {exc}", file=sys.stderr)

    def _evict_if_needed(self) -> None:
        """Cap entries at MAX_EXPERIENCES, evicting oldest single-recurrence
        entries first."""
        if len(self._entries) <= MAX_EXPERIENCES:
            return

        single = [e for e in self._entries if e.recurrence_count <= 1]
        recurring = [e for e in self._entries if e.recurrence_count > 1]

        single.sort(key=lambda e: e.date)
        recurring.sort(key=lambda e: e.date)

        while len(self._entries) > MAX_EXPERIENCES:
            if single:
                removed = single.pop(0)
                self._entries.remove(removed)
            elif recurring:
                removed = recurring.pop(0)
                self._entries.remove(removed)
            else:
                break
