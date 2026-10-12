"""Show a readable briefing from saved, validated AI Signal stories."""

from datetime import datetime, timezone
from html import escape, unescape
import re
from zoneinfo import ZoneInfo

import streamlit as st

from ai_pulse.models import Story
from ai_pulse.branding import artwork_data_uri, mascot_data_uri
from ai_pulse.storage import DEMO_DIGEST, ROOT, load_digest


def safe_prose(value: str) -> str:
    """Show publisher and model text literally instead of interpreting Markdown."""
    decoded = unescape(unescape(value))
    return re.sub(r'([\\`*_{}\[\]()#+.!|><$&-])', r'\\\1', decoded)


def render_story(story: Story, position: int, total: int, et: ZoneInfo,
                 featured: bool = False) -> None:
    """Display a dated story, its takeaway, and a link to its publisher."""
    card_key = 'feature' if featured else ('lead' if position == 1 else str(position))
    with st.container(key=f'story_{card_key}'):
        published = (story.published_at.astimezone(et).strftime('%b %d, %Y')
                     if story.date_precision == 'day' else
                     story.published_at.astimezone(et).strftime('%b %d, %I:%M %p ET'))
        label = 'A human story · AI for Good' if featured else story.category
        badge_style = 'signal-category human' if featured else 'signal-category'
        slot = '' if featured else f'<span class="signal-number">{position:02d} / {total:02d}</span>'
        st.html(f'<div><span class="{badge_style}">{escape(label)}</span>{slot}</div>')
        st.caption(f'{story.source_name}  ·  Published {published}')
        st.subheader(safe_prose(story.title))
        st.markdown(safe_prose(story.simple_explanation))
        with st.container(key=f'takeaway_{card_key}'):
            st.markdown('**Why it matters**')
            st.markdown(safe_prose(story.why_it_matters))
        if story.source_excerpt:
            truncated = story.source_excerpt.rstrip().endswith(('[…]', '[...]'))
            preview = story.source_excerpt.rstrip()
            if truncated:
                preview = preview.rsplit('[', 1)[0].rstrip()
                last_sentence_end = max(preview.rfind(mark) for mark in '.!?')
                if last_sentence_end >= 0:
                    preview = preview[:last_sentence_end + 1]
                else:
                    preview = ''
            if preview:
                with st.expander('Publisher excerpt'):
                    if story.summary_basis == 'rss_preview':
                        st.caption('This summary used the publisher excerpt.')
                    st.markdown(safe_prose(preview))
        st.link_button('Read original article ↗', str(story.source_url))


st.set_page_config(page_title='AI Signal | AI news in plain English', page_icon='⚡',
                   layout='wide', initial_sidebar_state='collapsed')
st.html('<style>' + (ROOT / 'assets' / 'dashboard.css').read_text(encoding='utf-8') + '</style>')
st.html(
    '<header class="signal-hero"><div class="signal-brand">'
    '<div class="signal-identity">'
    f'<img class="signal-mascot" src="{mascot_data_uri()}" '
    'alt="A friendly AI Signal bot waving hello" width="1624" height="1305">'
    '<div class="signal-wordmark">'
    '<p class="signal-kicker">Your AI briefing</p>'
    '<h1>AI Signal<span>.</span></h1></div></div>'
    '<p class="signal-intro">A few AI stories worth your time, '
    'explained in plain English.</p></div>'
    f'<img class="signal-banner" src="{artwork_data_uri()}" '
    'alt="AI Signal banner with breaking news, cybersecurity, AI tools, '
    'AI news, and AI for humanity illustrations." width="1672" height="941"></header>'
)

with st.sidebar:
    show_demo = st.toggle('Show fictional sample stories', value=False)
try:
    digest = load_digest(DEMO_DIGEST) if show_demo else load_digest()
except FileNotFoundError:
    st.info('No digest yet. Turn on fictional sample stories above, or run python main.py generate-local.')
    st.stop()
except ValueError:
    st.error('The saved digest is invalid. Regenerate it or turn on the fictional sample.')
    st.stop()

et = ZoneInfo('America/New_York')
age_hours = max(0, int((datetime.now(timezone.utc) - digest.generated_at).total_seconds() // 3600))
if digest.status == 'demo':
    st.warning('FICTIONAL SAMPLE · These stories are for exploring the dashboard.')
else:
    age_text = ('under an hour' if age_hours == 0 else
                '1 hour' if age_hours == 1 else f'{age_hours} hours')
    feature = digest.featured_story
    feature_age = ((datetime.now(timezone.utc).astimezone(et).date()
                    - feature.published_at.astimezone(et).date()).days
                   if feature else 999)
    show_feature = bool(feature and 0 <= feature_age <= 15)
    st.caption(f'{len(digest.stories) + int(show_feature)} stories  ·  '
               f'Updated {digest.generated_at.astimezone(et):%b %d, %I:%M %p ET}  ·  '
               f'Age: {age_text}')
    if age_hours >= 48:
        st.warning(f'This saved briefing is {age_text} old. Check the feed pipeline before sharing it.')

available_stories = list(digest.stories)
if digest.status == 'live' and show_feature:
    available_stories.append(feature)
topic = st.selectbox('Explore a topic',
                     ['All topics'] + sorted({story.category for story in available_stories}))
visible_stories = [story for story in digest.stories
                   if topic == 'All topics' or story.category == topic]

section_title = 'Inside this issue' if topic == 'All topics' else topic
st.html(f'<div class="signal-section"><h2>{escape(section_title)}</h2>'
        '<span>The news. The context. The human side.</span></div>')

for position, story in enumerate(visible_stories, start=1):
    render_story(story, position, len(visible_stories), et)

if digest.status == 'live' and show_feature and topic in ('All topics', feature.category):
    render_story(feature, 1, 1, et, featured=True)

st.html('<footer class="signal-footer"><strong>AI Signal</strong> · Stay curious. '
        'Read the original.<br>AI-assisted explanations, with publisher links for context.</footer>')
