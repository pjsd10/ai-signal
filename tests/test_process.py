from datetime import datetime, timedelta, timezone

from ai_pulse.models import SourceItem
from ai_pulse.process import (classify_category, filter_recent, is_ai_cybersecurity,
                              is_ai_tool, is_fun, prepare_candidates, select_stories)


NOW = datetime(2026, 10, 10, 15, tzinfo=timezone.utc)


def item(title: str, link: str, category: str, hours_old: int = 1) -> SourceItem:
    """Build a dated, fictional source item for selection tests."""
    return SourceItem(
        id=link,
        title=title,
        source_name='Fictional Test Feed',
        source_url=link,
        published_at=NOW - timedelta(hours=hours_old),
        category=category,
    )


def test_recent_filter_removes_old_and_duplicate_stories():
    """Old stories, repeat links, and punctuation-only headline variants are excluded."""
    recent = item('AI Tool Launches', 'https://example.com/one', 'AI Tools')
    same_url = item('Another headline', 'https://example.com/one', 'Other')
    same_title = item('AI Tool: Launches!', 'https://example.com/two', 'AI Tools')
    old = item('Old research', 'https://example.com/old', 'AI Research', hours_old=80)
    assert filter_recent([recent, same_url, same_title, old], NOW) == [recent]


def test_daily_selection_prefers_one_cyber_two_updates_two_tools():
    """The updated daily 1/2/2 convention takes priority over pure recency."""
    stories = [
        item('A company launches an AI app', 'https://example.com/tool1', 'AI Tools', 3),
        item('Another team unveils an AI tool', 'https://example.com/tool2', 'AI Tools', 4),
        item('Researchers publish model findings', 'https://example.com/news1', 'AI Research', 1),
        item('AI agents gain new safety checks', 'https://example.com/news2', 'AI Agents', 2),
        item('A robot plays a music game', 'https://example.com/fun', 'Other', 5),
        item('AI detects a phishing campaign', 'https://example.com/cyber', 'AI & Cybersecurity', 6),
        item('AI policy update', 'https://example.com/extra', 'Other', 0),
    ]
    selected = select_stories(stories)
    assert len(selected) == 5
    assert sum(is_ai_tool(story) for story in selected) == 2
    assert sum(is_ai_cybersecurity(story) for story in selected) == 1
    assert sum(not is_ai_tool(story) and not is_ai_cybersecurity(story)
               for story in selected) == 2
    assert stories[5] in selected


def test_cyber_slot_uses_another_current_story_when_none_exists():
    """An absent 72-hour cyber story should never create or mislabel one."""
    stories = [
        item('A company launches an AI app', 'https://example.com/tool', 'AI Tools'),
        item('AI research update one', 'https://example.com/one', 'AI Research'),
        item('AI research update two', 'https://example.com/two', 'AI Research'),
        item('AI research update three', 'https://example.com/three', 'AI Research'),
        item('AI robot makes music', 'https://example.com/fun', 'Other'),
    ]
    selected = select_stories(prepare_candidates(stories, NOW))
    assert len(selected) == 5
    assert not any(is_ai_cybersecurity(story) for story in selected)
    assert all(story in stories for story in selected)


def test_cyber_search_extends_to_72_hours_even_when_feed_is_full():
    """The cyber slot can use a verified 60-hour article despite five newer items."""
    stories = [
        item('AI news one', 'https://example.com/one', 'Other'),
        item('AI news two', 'https://example.com/two', 'Other'),
        item('AI news three', 'https://example.com/three', 'Other'),
        item('AI news four', 'https://example.com/four', 'Other'),
        item('AI news five', 'https://example.com/five', 'Other'),
        item('AI detects malware', 'https://example.com/cyber', 'AI & Cybersecurity', 60),
    ]
    selected = select_stories(prepare_candidates(stories, NOW))
    assert stories[-1] in selected


def test_cyber_classification_requires_ai_and_security_evidence():
    """Security headlines without AI and AI safety headlines stay outside cyber."""
    assert classify_category('AI detects phishing campaign') == 'AI & Cybersecurity'
    assert classify_category('Security update', 'AI helps detect malware') == 'AI & Cybersecurity'
    assert classify_category('Security update') != 'AI & Cybersecurity'
    assert classify_category('AI safety update') != 'AI & Cybersecurity'


def test_selection_never_fabricates_missing_slots():
    """A short feed produces a shorter digest instead of invented stories."""
    one = item('AI research update', 'https://example.com/only', 'AI Research')
    assert select_stories([one]) == [one]


def test_music_lawsuit_is_not_fun_and_direct_ai_news_wins_fallback():
    """A serious music lawsuit cannot displace a clearly AI-focused update."""
    music_lawsuit = item('DistroKid takes down songs after a lawsuit',
                         'https://example.com/music', 'Other', 0)
    stories = [
        music_lawsuit,
        item('AI models face new risks', 'https://example.com/models', 'AI Models', 1),
        item('Anthropic changes AI evaluations', 'https://example.com/evals', 'AI Agents', 2),
        item('AI agents raise privacy questions', 'https://example.com/agents', 'AI Agents', 3),
        item('OpenAI tool detects malware', 'https://example.com/cyber', 'AI & Cybersecurity', 4),
        item('GPT improves browser tests', 'https://example.com/testing', 'AI Models', 5),
    ]
    selected = select_stories(stories)
    assert not is_fun(music_lawsuit)
    assert len(selected) == 5
    assert music_lawsuit not in selected


def test_general_ai_reporting_has_a_real_news_category():
    """AI reporting gets a news label without relabeling unrelated technology."""
    assert classify_category('The government proposes AI rules') == 'AI News'
    assert classify_category('A new AI app', 'The app uses a frontier model.') == 'AI Tools'
    assert classify_category('An AI service turns sketches into videos',
                             'The service uses frontier models.') == 'AI Tools'
    assert classify_category('A new bicycle is announced') == 'Other'


def test_people_helping_stories_stay_out_of_daily_news_slots():
    """Education and accessibility features remain separate even with stale tags."""
    assert classify_category('AI helps students learn independently') == 'AI for Good'
    assert classify_category('AI supports patients during recovery') == 'AI for Good'
    assert classify_category('AI researchers publish a new model') != 'AI for Good'
    human = item('AI helps students learn independently', 'https://example.com/human', 'Other')
    news = [item(f'AI research update {index}', f'https://example.com/{index}',
                 'AI Research', index + 1) for index in range(5)]
    selected = select_stories([human, *news])
    assert len(selected) == 5
    assert human not in selected


def test_human_features_do_not_prevent_widening_a_sparse_daily_pool():
    """Feature candidates cannot make a short news pool look full."""
    features = [item(f'AI helps students learn topic {index}',
                     f'https://example.com/feature-{index}', 'AI for Good')
                for index in range(5)]
    news = [item(f'AI research topic {index}', f'https://example.com/news-{index}',
                 'AI Research', 60) for index in range(5)]
    assert prepare_candidates([*features, *news], NOW) == news
