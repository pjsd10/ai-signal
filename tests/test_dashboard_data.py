from streamlit.testing.v1 import AppTest
from ai_pulse.storage import ROOT


def test_missing_digest_has_helpful_empty_state(monkeypatch, tmp_path):
    """Without a saved digest, the dashboard should explain how to try the demo."""
    from ai_pulse import storage

    original_load = storage.load_digest

    def load_missing_digest(path=tmp_path / 'missing.json'):
        """Point the dashboard at a missing file for this empty-state test."""
        return original_load(path)

    monkeypatch.setattr(storage, 'load_digest', load_missing_digest)
    app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=15).run()
    assert not app.exception
    assert 'No digest yet' in app.info[0].value


def test_demo_dashboard_filter():
    """The sample label and category filter should work in the dashboard."""
    app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=15).run()
    app.toggle[0].set_value(True).run()
    assert not app.exception
    assert 'FICTIONAL SAMPLE' in app.warning[0].value
    assert len([heading for heading in app.subheader
                if heading.value.startswith('Sample:')]) == 2
    app.selectbox[0].select('AI in Testing').run()
    assert len([heading for heading in app.subheader
                if heading.value.startswith('Sample:')]) == 1
    assert any('test cases' in heading.value for heading in app.subheader)


def test_live_dashboard_shows_saved_digest_age(monkeypatch):
    """A live digest should show its age and its saved story cards."""
    from ai_pulse import storage

    live_digest = storage.load_digest(storage.DEMO_DIGEST).model_copy(
        update={'status': 'live'})

    def load_live_digest(path=None):
        """Supply a valid live digest without depending on today's RSS output."""
        return live_digest

    monkeypatch.setattr(storage, 'load_digest', load_live_digest)
    app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=15).run()
    assert not app.exception
    assert any('Age:' in caption.value for caption in app.caption)
    assert not any('Coverage:' in caption.value for caption in app.caption)
    assert not any(item.value == '**The story**' for item in app.markdown)
    assert any('Why it matters' in item.value for item in app.markdown)
    assert len([heading for heading in app.subheader
                if heading.value.startswith('Sample:')]) == 2
