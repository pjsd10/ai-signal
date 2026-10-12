import pytest
from pydantic import ValidationError
from ai_pulse.models import Digest
from ai_pulse.storage import DEMO_DIGEST, load_digest, save_digest


def test_round_trip(tmp_path):
    """A saved digest should load back with the same validated values."""
    digest = load_digest(DEMO_DIGEST)
    path = tmp_path / 'digest.json'
    save_digest(digest, path)
    assert load_digest(path) == digest


def test_unsafe_source_link_rejected():
    """Script and plain HTTP URLs from untrusted sources should fail validation."""
    data = load_digest(DEMO_DIGEST).model_dump(mode='json')
    for unsafe_url in ('javascript:alert(1)', 'http://example.com/insecure'):
        data['stories'][0]['source_url'] = unsafe_url
        with pytest.raises(ValidationError):
            Digest.model_validate(data)


def test_invalid_save_preserves_previous_digest(tmp_path):
    """Invalid new data should leave the previous digest file untouched."""
    path = tmp_path / 'digest.json'
    digest = load_digest(DEMO_DIGEST)
    save_digest(digest, path)
    before = path.read_bytes()
    digest.stories = []
    with pytest.raises(ValidationError):
        save_digest(digest, path)
    assert path.read_bytes() == before


def test_demo_is_explicitly_labeled():
    """Sample content must be marked as a demo rather than live news."""
    assert load_digest(DEMO_DIGEST).status == 'demo'
