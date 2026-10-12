"""Ask a model on this computer to explain selected public RSS stories."""

import json
import re
from time import monotonic
from urllib.request import ProxyHandler, Request, build_opener

from ai_pulse.models import Digest, SourceItem
from ai_pulse.fetch_news import NoFeedRedirect
from ai_pulse.summarize import SummaryBatch, build_prompt, digest_from_batch


OLLAMA_CHAT_URL = 'http://127.0.0.1:11434/api/chat'
OLLAMA_TAGS_URL = 'http://127.0.0.1:11434/api/tags'


def local_model_identity(model: str, open_url=None) -> str:
    """Read the installed model digest so replacing weights invalidates the cache."""
    if open_url is None:
        open_url = build_opener(ProxyHandler({}), NoFeedRedirect()).open
    with open_url(Request(OLLAMA_TAGS_URL), timeout=5) as response:
        installed = json.load(response)
    entry = next((entry for entry in installed['models']
                  if entry['name'] == model), None)
    if entry is None:
        raise ValueError(f'{model} is not installed locally; no model was downloaded')
    digest = entry.get('digest', '')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('Installed model did not provide a valid cache identity')
    return f'ollama:{model}:{digest}'


def summarize_local_items(items: list[SourceItem], model: str,
                          open_url=None, deadline: float | None = None,
                          request_timeout: int = 120) -> Digest:
    """Summarize and validate items, stopping when a caller's time budget ends."""
    if not items or len(items) > 5:
        raise ValueError('Summarization needs one to five selected items')
    if not model:
        raise ValueError('Configure OLLAMA_MODEL with an installed local model')
    if not 0 < request_timeout <= 600:
        raise ValueError('Local model request timeout must be between 1 and 600 seconds')
    if open_url is None:
        open_url = build_opener(ProxyHandler({}), NoFeedRedirect()).open
    with open_url(Request(OLLAMA_TAGS_URL), timeout=5) as response:
        installed = json.load(response)
    installed_names = {entry['name'] for entry in installed['models']}
    if model not in installed_names:
        raise ValueError(f'{model} is not installed locally; no model was downloaded')
    summaries = []
    for item in items:
        feedback = ''
        for attempt in range(2):
            remaining = request_timeout if deadline is None else deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError('Local summary time budget expired')
            prompt = build_prompt([item]) + ('\n\nReturn JSON matching this schema exactly: '
                                             + json.dumps(SummaryBatch.model_json_schema()))
            prompt += feedback
            payload = {
                'model': model,
                'messages': [{'role': 'user', 'content': prompt}],
                'format': SummaryBatch.model_json_schema(),
                'stream': False,
                'options': {'temperature': 0},
            }
            request = Request(
                OLLAMA_CHAT_URL,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with open_url(request, timeout=min(request_timeout, remaining)) as response:
                result = json.load(response)
            batch = SummaryBatch.model_validate_json(result['message']['content'])
            try:
                digest_from_batch([item], batch)
            except ValueError as exc:
                if attempt == 0 and str(exc).startswith('Draft quality check failed:'):
                    feedback = ('\n\nThe previous explanation repeated the short RSS '
                                'excerpt or failed a copy check. Use a different '
                                'specific fact from the article body. Do not add '
                                'unsupported claims or repeat the excerpt.')
                    continue
                raise
            summaries.extend(batch.stories)
            break
    return digest_from_batch(items, SummaryBatch(stories=summaries))
