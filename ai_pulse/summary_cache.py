"""Reuse checked summaries without storing article bodies or model prompts."""

from collections.abc import Callable
from datetime import datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from ai_pulse.models import SourceItem, Story
from ai_pulse.quality import check_automatic_story, check_story
from ai_pulse.storage import ROOT
from ai_pulse.story_pool import validate_pool_item
from ai_pulse.summarize import SummaryBatch, build_prompt


DEFAULT_SUMMARY_CACHE = ROOT / 'data' / 'summary_cache.json'
MAX_ENTRIES = 200
MAX_CACHE_BYTES = 2_000_000
CACHE_LIFETIME = timedelta(days=7)
# Bump this when generation options, retry behavior, or validation policy changes.
SUMMARY_POLICY_VERSION = '1'


class CacheEntry(BaseModel):
    """Keep a checked card and its save time; evidence is represented by the key."""

    model_config = ConfigDict(extra='forbid')
    saved_at: AwareDatetime
    story: Story


class CacheFile(BaseModel):
    """Reject unexpected cache layouts and prevent unbounded entry counts."""

    model_config = ConfigDict(extra='forbid')
    version: Literal[1] = 1
    entries: dict[str, CacheEntry] = Field(default_factory=dict, max_length=MAX_ENTRIES)


class SummaryCache:
    """Persist passing summaries independently of whether a whole issue succeeds."""

    def __init__(self, path: Path, now: datetime,
                 model_identity: Callable[[], str]) -> None:
        """Load a small cache and resolve the installed model only if needed."""
        self.path = path
        self.now = now
        self.model_identity = model_identity
        self._identity: str | None = None
        self.notes: list[str] = []
        self.hits = 0
        self.misses = 0
        self.saved = 0
        self.entries = self._load()

    def _load(self) -> dict[str, CacheEntry]:
        """Ignore corrupt caches and discard expired or future-dated entries."""
        if not self.path.exists():
            return {}
        try:
            with self.path.open('rb') as handle:
                raw = handle.read(MAX_CACHE_BYTES + 1)
            if len(raw) > MAX_CACHE_BYTES:
                raise ValueError('Cache exceeds its size limit')
            cached = CacheFile.model_validate_json(raw)
        except (OSError, ValueError) as exc:
            self.notes.append(f'Summary cache could not be read ({type(exc).__name__}); '
                              'summaries will be checked again.')
            return {}
        return {key: entry for key, entry in cached.entries.items()
                if timedelta(0) <= self.now - entry.saved_at < CACHE_LIFETIME}

    def _key(self, item: SourceItem) -> str:
        """Hash the exact source, prompt, schema, and installed model version."""
        validate_pool_item(item.model_copy(update={'article_text': ''}), self.now)
        if len(item.article_text) < 300:
            raise ValueError('Summary caching requires readable article text')
        if self._identity is None:
            self._identity = self.model_identity()
        if not self._identity:
            raise ValueError('Summary caching requires an identified model')
        material = {
            'policy': SUMMARY_POLICY_VERSION,
            'model': self._identity,
            'source': item.model_dump(mode='json'),
            'prompt': build_prompt([item]),
            'schema': SummaryBatch.model_json_schema(),
        }
        return sha256(json.dumps(material, sort_keys=True,
                                 ensure_ascii=False).encode('utf-8')).hexdigest()

    def get(self, item: SourceItem) -> Story | None:
        """Return matching prose only after checking it against current evidence."""
        key = self._key(item)
        entry = self.entries.get(key)
        if entry is not None:
            try:
                check_automatic_story(entry.story, item)
                if check_story(entry.story):
                    raise ValueError('Cached summary failed current quality checks')
            except ValueError:
                self.entries.pop(key)
                self.notes.append('A cached summary failed current checks; regenerating it.')
            else:
                self.hits += 1
                return entry.story.model_copy(deep=True)
        self.misses += 1
        return None

    def put(self, item: SourceItem, story: Story) -> None:
        """Validate and immediately save a new result so later failures cannot lose it."""
        key = self._key(item)
        check_automatic_story(story, item)
        issues = check_story(story)
        if issues:
            raise ValueError('Draft quality check failed: ' + '; '.join(issues))
        self.entries[key] = CacheEntry(saved_at=self.now, story=story.model_copy(deep=True))
        self.entries = dict(sorted(self.entries.items(), key=self._saved_time,
                                   reverse=True)[:MAX_ENTRIES])
        try:
            self._save()
        except OSError as exc:
            self.notes.append(f'Summary cache could not be saved ({type(exc).__name__}); '
                              'this checked result remains available for the current run.')
        else:
            self.saved += 1

    @staticmethod
    def _saved_time(pair: tuple[str, CacheEntry]) -> datetime:
        """Order entries by generation time when enforcing the cache size limit."""
        return pair[1].saved_at

    def _save(self) -> None:
        """Atomically replace bounded JSON, preserving the old file if writing fails."""
        raw = CacheFile(entries=self.entries).model_dump_json(indent=2).encode('utf-8')
        while len(raw) > MAX_CACHE_BYTES and self.entries:
            self.entries.pop(next(reversed(self.entries)))
            raw = CacheFile(entries=self.entries).model_dump_json(indent=2).encode('utf-8')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='wb', dir=self.path.parent,
                                             suffix='.tmp', delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(raw)
            os.replace(temporary, self.path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
