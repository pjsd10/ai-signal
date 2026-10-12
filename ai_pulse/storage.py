"""Validate before writing; replace files atomically to protect old digests."""
import os
from pathlib import Path
import tempfile
from ai_pulse.models import Digest

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIGEST = ROOT / 'data' / 'latest_digest.json'
DRAFT_DIGEST = ROOT / 'data' / 'draft_digest.json'
DEMO_DIGEST = ROOT / 'tests' / 'fixtures' / 'demo_digest.json'


def load_digest(path: Path = DEFAULT_DIGEST) -> Digest:
    """Read a JSON digest from disk and validate every stored field."""
    return Digest.model_validate_json(path.read_text(encoding='utf-8'))


def save_digest(digest: Digest, path: Path = DEFAULT_DIGEST) -> None:
    """Validate and atomically save a digest without damaging an older copy."""
    validated = Digest.model_validate(digest.model_dump())
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(validated.model_dump_json(indent=2) + '\n')
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
