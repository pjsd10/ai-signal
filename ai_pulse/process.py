"""Choose recent, distinct AI stories for the reader's five-slot digest."""

from datetime import datetime, timedelta, timezone
from operator import attrgetter
import re
from zoneinfo import ZoneInfo

from ai_pulse.models import Category, Digest, SourceItem, Story, StoryHistoryEntry


def classify_category(title: str, description: str = '') -> Category:
    """Use the headline for a topic label, falling back to its short description."""
    if is_ai_cyber_text(f'{title} {description}'):
        return 'AI & Cybersecurity'
    if is_ai_for_good_text(f'{title} {description}'):
        return 'AI for Good'
    title_category = category_from_text(title)
    if title_category != 'Other':
        return title_category
    description_category = category_from_text(description)
    if description_category != 'Other':
        return description_category
    return 'AI News' if is_ai_related_text(f'{title} {description}') else 'Other'


def is_ai_for_good_text(text: str) -> bool:
    """Identify AI helping people with education, care, or accessibility needs."""
    beneficiaries = re.search(
        r'\b(teens?|students?|patients?|disabilit(?:y|ies)|disabled|'
        r'special.needs|blind|deaf|refugees?|disaster survivors?)\b', text, re.I)
    assistance = re.search(
        r'\b(help(?:s|ing|ed)?|support(?:s|ing|ed)?|assist(?:s|ing|ed)?|'
        r'accessib(?:le|ility)|learn(?:s|ing)?|care|recover(?:y|ing)?)\b', text, re.I)
    return bool(is_ai_related_text(text) and beneficiaries and assistance)


def is_main_news_item(item: SourceItem | Story) -> bool:
    """Keep people-helping features out of all five main-news selection paths."""
    description = item.description if isinstance(item, SourceItem) else item.source_excerpt
    return (item.category != 'AI for Good'
            and not is_ai_for_good_text(f'{item.title} {description}'))


def category_from_text(text: str) -> Category:
    """Match familiar AI topic words without making a claim about article contents."""
    text = text.lower()
    if is_ai_cyber_text(text):
        return 'AI & Cybersecurity'
    if re.search(r'\b(testing|test cases|quality assurance|qa)\b', text):
        return 'AI in Testing'
    if re.search(r'\b(agents?|agentic|autonomous)\b', text):
        return 'AI Agents'
    if re.search(r'\b(?:turns?|transform(?:s|ing)?)\b.+\binto\b.+\b(?:images?|videos?|ads?|campaigns?)\b', text):
        return 'AI Tools'
    if re.search(r'\b(models?|llms?|gpt|gemini|claude)\b', text):
        return 'AI Models'
    if re.search(r'\b(research|study|paper|scientists?)\b', text):
        return 'AI Research'
    if re.search(r'\b(tools?|apps?|software|products?|platforms?|assistants?|editors?|features?)\b', text):
        return 'AI Tools'
    return 'Other'


def is_ai_cyber_text(text: str) -> bool:
    """Require both an AI term and a specific cybersecurity term in feed text."""
    ai_term = is_ai_related_text(text)
    cyber_term = re.search(
        r'\b(cyber(?:security)?|security|phishing|malware|ransomware|'
        r'vulnerabilit(?:y|ies)|prompt injection|threat detection)\b', text, re.I,
    )
    return bool(ai_term and cyber_term)


def is_ai_related_text(text: str) -> bool:
    """Require an explicit AI signal before a broad technology story enters the digest."""
    return bool(re.search(
        r'\b(ai|artificial intelligence|machine learning|generative ai|llms?|'
        r'gpt(?:-\d+)?|gemini|claude|copilot|openai|anthropic|deepmind)\b',
        text, re.I,
    ))


def has_sufficient_ai_context(title: str, description: str) -> bool:
    """Require AI in the title or enough feed detail to assess a broad title."""
    return is_ai_related_text(title) or (
        len(description.strip()) >= 100 and is_ai_related_text(description))


def normalized_title(title: str) -> str:
    """Ignore capitalization and punctuation when comparing article headlines."""
    return ' '.join(re.findall(r'\w+', title.casefold()))


def is_general_update(item: SourceItem) -> bool:
    """Identify an AI update outside the cyber and tool slots."""
    return is_main_news_item(item) and not is_ai_tool(item) and not is_ai_cybersecurity(item)


def filter_recent(items: list[SourceItem], now: datetime, hours: int = 48) -> list[SourceItem]:
    """Keep dated items in the lookback window and remove repeated URLs or titles."""
    if now.tzinfo is None:
        raise ValueError('now must include a timezone')
    cutoff = now.astimezone(timezone.utc) - timedelta(hours=hours)
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    result: list[SourceItem] = []
    for item in sorted(items, key=attrgetter('published_at'), reverse=True):
        if not cutoff <= item.published_at <= now:
            continue
        title_key = normalized_title(item.title)
        if str(item.source_url) in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(str(item.source_url))
        seen_titles.add(title_key)
        result.append(item)
    return result


def is_new_tool(item: SourceItem) -> bool:
    """Spot an apparent tool launch from the feed title, without claiming certainty."""
    return item.category == 'AI Tools' and bool(re.search(
        r'\b(launches?|launched|introduces?|introduced|unveils?|unveiled|debuts?|released|releases?)\b',
        item.title.lower(),
    ))


def is_ai_tool(item: SourceItem) -> bool:
    """Recognize a publisher item classified as an AI tool or product."""
    return item.category == 'AI Tools'


def is_ai_cybersecurity(item: SourceItem) -> bool:
    """Recognize an item classified as covering AI and cybersecurity."""
    return item.category == 'AI & Cybersecurity'


def is_fun(item: SourceItem) -> bool:
    """Spot lighter AI topics such as creative projects, games, or playful robots."""
    title = item.title.lower()
    if re.search(r'\b(lawsuits?|sues?|takedowns?|copyright|fraud|abuse|harm)\b', title):
        return False
    has_ai_in_title = is_ai_related_text(title) or bool(re.search(r'\brobots?\b', title))
    has_playful_topic = bool(re.search(
        r'\b(games?|music|art|artists?|movies?|films?|creative|memes?|pets?|toys?|robots?)\b',
        title,
    ))
    return has_ai_in_title and has_playful_topic


def prepare_candidates(items: list[SourceItem], now: datetime, hours: int = 48,
                       count: int = 5) -> list[SourceItem]:
    """Use a short window, widening to 72 hours for gaps or the cyber slot."""
    items = [item for item in items if is_main_news_item(item)]
    recent = filter_recent(items, now, hours)
    if hours >= 72:
        return recent
    wider = filter_recent(items, now, 72)
    if len(recent) < count:
        return wider
    if not any(is_ai_cybersecurity(item) for item in recent):
        older_cyber = next((item for item in wider if is_ai_cybersecurity(item)), None)
        if older_cyber:
            recent.append(older_cyber)
    return recent


def select_stories(items: list[SourceItem], count: int = 5) -> list[SourceItem]:
    """For a daily issue prefer one cyber, two news, and two AI tools."""
    remaining = sorted((item for item in items if is_main_news_item(item)), key=lambda item: (
        not is_ai_related_text(item.title), -item.published_at.timestamp()))
    selected: list[SourceItem] = []

    def take_matching(limit: int, predicate) -> None:
        """Move up to limit matching items into the final selection."""
        taken = 0
        for item in remaining[:]:
            if taken >= limit:
                break
            if predicate(item) and len(selected) < count:
                selected.append(item)
                remaining.remove(item)
                taken += 1

    take_matching(1, is_ai_cybersecurity)
    take_matching(2, is_general_update)
    take_matching(2, is_ai_tool)
    selected.extend(remaining[:max(0, count - len(selected))])
    return selected[:count]


def url_key(url: object) -> str:
    """Compare publisher links consistently when checking previous digests."""
    return str(url).rstrip('/')


def history_index(digest: Digest | None) -> dict[str, StoryHistoryEntry]:
    """Combine saved history with the visible digest for older MVP files."""
    if digest is None or digest.status != 'live':
        return {}
    entries = {url_key(entry.url): entry for entry in digest.story_history}
    current_stories = list(digest.stories)
    if digest.featured_story:
        current_stories.append(digest.featured_story)
    for story in current_stories:
        key = url_key(story.source_url)
        if key not in entries:
            entries[key] = StoryHistoryEntry(url=story.source_url,
                                             last_shown_at=digest.generated_at,
                                             times_shown=1)
    return entries


def is_same_day_refresh(previous: Digest | None, now: datetime) -> bool:
    """Use Eastern dates to distinguish another refresh from the next day's issue."""
    if previous is None or previous.status != 'live':
        return False
    history = history_index(previous)
    latest_shown = max((entry.last_shown_at for entry in history.values()),
                       default=previous.generated_at)
    eastern = ZoneInfo('America/New_York')
    return latest_shown.astimezone(eastern).date() == now.astimezone(eastern).date()


def previous_sources(previous: Digest | None) -> list[SourceItem]:
    """Recover news metadata from the visible issue if the feed pool is sparse."""
    if previous is None or previous.status != 'live':
        return []
    return [SourceItem(id=story.id, title=story.title,
                       source_name=story.source_name, source_url=story.source_url,
                       published_at=story.published_at,
                       description=story.source_excerpt,
                       category=classify_category(story.title, story.source_excerpt))
            for story in previous.stories
            if story.source_type == 'rss' and is_main_news_item(story)]


def select_for_rerun(items: list[SourceItem], now: datetime, hours: int,
                     count: int, previous: Digest | None,
                     relaxed_category: bool = False) -> list[SourceItem]:
    """Fill five slots from unseen items, then rotate shown items when needed."""
    items = [item for item in items if is_main_news_item(item)]
    history = history_index(previous)
    if not history:
        return select_stories(prepare_candidates(items, now, hours, count), count)
    five_day = filter_recent(items, now, 120)
    unseen = [item for item in five_day if url_key(item.source_url) not in history]
    if is_same_day_refresh(previous, now) and relaxed_category:
        selected = unseen[:count]
    else:
        selected = select_stories(unseen, count)
    selected_urls = {url_key(item.source_url) for item in selected}
    if len(selected) < count:
        repeated = [item for item in five_day
                    if url_key(item.source_url) in history
                    and url_key(item.source_url) not in selected_urls]
        repeated.sort(key=lambda item: (
            history[url_key(item.source_url)].last_shown_at,
            history[url_key(item.source_url)].times_shown,
            -item.published_at.timestamp()))
        selected.extend(repeated[:count - len(selected)])
        selected_urls = {url_key(item.source_url) for item in selected}
    if len(selected) < count:
        older = filter_recent([*items, *previous_sources(previous)], now, 24 * 365 * 20)
        fallback = [item for item in older
                    if url_key(item.source_url) not in selected_urls]
        fallback.sort(key=lambda item: (
            url_key(item.source_url) in history,
            history[url_key(item.source_url)].last_shown_at
            if url_key(item.source_url) in history else datetime.min.replace(tzinfo=timezone.utc),
            -item.published_at.timestamp()))
        selected.extend(fallback[:count - len(selected)])
    return selected


def remember_approved(draft: Digest, previous: Digest | None,
                      approved_at: datetime) -> Digest:
    """Carry forward shown links and update their last-shown time on approval."""
    if approved_at.tzinfo is None:
        raise ValueError('Approval time must include a timezone')
    entries = history_index(previous)
    current_stories = list(draft.stories)
    if draft.featured_story:
        current_stories.append(draft.featured_story)
    for story in current_stories:
        key = url_key(story.source_url)
        prior_count = entries[key].times_shown if key in entries else 0
        entries[key] = StoryHistoryEntry(url=story.source_url,
                                         last_shown_at=approved_at,
                                         times_shown=prior_count + 1)
    return draft.model_copy(update={'story_history': sorted(
        entries.values(), key=lambda entry: url_key(entry.url))})


def remember_feature(digest: Digest, feature: Story,
                     shown_at: datetime) -> Digest:
    """Record a manually added feature without recounting unchanged news cards."""
    if shown_at.tzinfo is None:
        raise ValueError('Feature time must include a timezone')
    entries = history_index(digest)
    key = url_key(feature.source_url)
    prior_count = entries[key].times_shown if key in entries else 0
    entries[key] = StoryHistoryEntry(url=feature.source_url,
                                     last_shown_at=shown_at,
                                     times_shown=prior_count + 1)
    return digest.model_copy(update={
        'featured_story': feature,
        'story_history': sorted(entries.values(), key=lambda entry: url_key(entry.url)),
    })
