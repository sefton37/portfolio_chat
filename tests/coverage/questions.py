"""
QuestionBank — load, merge, and iterate over question parts.

Parts live in tests/coverage/parts/*.json. Each file is a JSON array of question
objects. This module merges them deterministically (sorted by id) and writes the
merged list to tests/coverage/questions.json.

The generate() method is idempotent: same parts → byte-identical questions.json
(sha256 stable across runs).

Do NOT hand-author questions.json or any parts/*.json here — generate() does that.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Required fields per question category
_REQUIRED_FIELDS_ALL = {"id", "category", "tones", "source_file", "expected_behavior"}
_REQUIRED_TONES = {"neutral", "adversarial", "anxious", "angry", "aloof", "wordy"}

_CATEGORY_REQUIRED_FIELDS: dict[str, set[str]] = {
    "in_scope": {"id", "category", "tones", "source_file", "expected_behavior", "grounding"},
    "adjacent": {"id", "category", "tones", "source_file", "expected_behavior", "false_premise"},
    "left_field": {"id", "category", "tones", "source_file", "expected_behavior"},
}

_DEFAULT_PARTS_DIR = Path(__file__).parent / "parts"
_DEFAULT_OUT_PATH = Path(__file__).parent / "questions.json"


class QuestionBank:
    """Manages the merged question corpus for coverage testing."""

    def generate(
        self,
        parts_dir: Path | str | None = None,
        out_path: Path | str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Read all parts/*.json files, validate, dedupe by id, sort by id,
        and write deterministically to questions.json.

        Args:
            parts_dir: Directory of parts JSON files. Defaults to tests/coverage/parts/.
            out_path:  Output path. Defaults to tests/coverage/questions.json.

        Returns:
            The merged, validated, sorted list of question dicts.

        Raises:
            ValueError: If a question fails validation.
        """
        parts_dir = Path(parts_dir) if parts_dir else _DEFAULT_PARTS_DIR
        out_path = Path(out_path) if out_path else _DEFAULT_OUT_PATH

        part_files = sorted(parts_dir.glob("*.json"))
        if not part_files:
            logger.warning(f"No part files found in {parts_dir}")
            questions_list: list[dict[str, Any]] = []
        else:
            seen_ids: dict[str, dict[str, Any]] = {}
            for part_file in part_files:
                with open(part_file, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, list):
                    raise ValueError(f"{part_file}: expected JSON array, got {type(data).__name__}")
                for q in data:
                    self._validate_question(q, part_file.name)
                    qid = q["id"]
                    if qid not in seen_ids:
                        seen_ids[qid] = q

            # Sort deterministically by id
            questions_list = sorted(seen_ids.values(), key=lambda x: x["id"])

        # Write with stable, idempotent formatting
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(questions_list, f, indent=2, sort_keys=True, ensure_ascii=False)
            f.write("\n")  # trailing newline for stable sha256

        logger.info(f"Generated questions.json with {len(questions_list)} questions")
        return questions_list

    def load(self, path: Path | str | None = None) -> list[dict[str, Any]]:
        """
        Read questions.json and return the list.

        Args:
            path: Path to questions.json. Defaults to tests/coverage/questions.json.

        Returns:
            List of question dicts.
        """
        path = Path(path) if path else _DEFAULT_OUT_PATH
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def iter_turns(
        self,
        questions: list[dict[str, Any]],
        tones: list[str] | None = None,
    ) -> Iterator[tuple[dict[str, Any], str, str]]:
        """
        Yield (question, tone, message_text) for each question × tone.

        Args:
            questions: List of question dicts.
            tones:     Tones to include. Defaults to all 6 standard tones.

        Yields:
            (question_dict, tone_name, message_text)
        """
        active_tones = tones or list(_REQUIRED_TONES)
        # Sort tones for deterministic ordering
        active_tones = sorted(active_tones)

        for question in questions:
            tone_map = question.get("tones", {})
            for tone in active_tones:
                if tone in tone_map:
                    yield question, tone, tone_map[tone]

    # ------------------------------------------------------------------
    # Internal validation
    # ------------------------------------------------------------------

    def _validate_question(self, q: Any, filename: str) -> None:
        """Validate a single question object. Raises ValueError on failure."""
        if not isinstance(q, dict):
            raise ValueError(f"{filename}: question must be a dict, got {type(q).__name__}")

        qid = q.get("id", "<unknown>")
        category = q.get("category")

        # All-category required fields
        for field in _REQUIRED_FIELDS_ALL:
            if field not in q:
                raise ValueError(f"{filename} [{qid}]: missing required field '{field}'")

        # Category-specific fields
        cat_fields = _CATEGORY_REQUIRED_FIELDS.get(category, _REQUIRED_FIELDS_ALL)
        for field in cat_fields:
            if field not in q:
                raise ValueError(
                    f"{filename} [{qid}]: missing required field '{field}' for category '{category}'"
                )

        # Tone keys
        tones = q.get("tones", {})
        if not isinstance(tones, dict):
            raise ValueError(f"{filename} [{qid}]: 'tones' must be a dict")
        missing_tones = _REQUIRED_TONES - set(tones.keys())
        if missing_tones:
            raise ValueError(
                f"{filename} [{qid}]: missing required tone keys: {sorted(missing_tones)}"
            )
