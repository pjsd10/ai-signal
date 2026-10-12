# AI Signal

Discover AI, without the jargon. A GenAcademy Python project.

AI Signal is a **local AI news briefing app**: Python collects approved publisher
RSS feeds, Ollama summarizes readable article text on your computer, and
Streamlit displays a saved issue with source links and publication dates.
The dashboard can display the included saved issue without an AI key or Ollama.
Generating a new issue requires internet access and the installed local model.

This MVP runs locally; public hosting, scheduled refreshes, and live Gemini
integration are not demonstrated.

## Quick start

With Python 3.12 installed, run these commands from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe main.py validate
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address=127.0.0.1
```

Open the local URL printed by Streamlit. No `.env` is required to view the
saved issue. Its original dates and saved timestamp are retained. It is a
real saved issue, not a live fetch each time the page opens.

To generate a new issue, first start Ollama with `qwen2:7b` already installed,
then run `python main.py refresh-local` using the virtual environment. New
summaries can take several minutes, depending on the available hardware. The
app preserves the last complete issue if generation fails. It never installs
a model automatically.

The nine configured RSS feeds and their coverage tradeoffs are documented in
[SOURCE_OPTIONS.md](SOURCE_OPTIONS.md).

## Project layout

Use the project folder as the GitHub repository root.

```text
ai-signal/
├── ai_pulse/              Reusable Python code: settings, models, storage
├── assets/                Bundled AI Signal artwork and dashboard styling
├── data/                  Saved digest JSON for the dashboard
├── tests/                 Offline checks and clearly labeled sample data
│   └── fixtures/
├── app.py                 Streamlit dashboard entry point
├── main.py                Command-line entry point
├── requirements.txt       App dependencies
├── requirements-dev.txt   App dependencies plus pytest
├── .env.example           Configuration template, with no real secrets
└── .gitignore             Keeps local secrets and virtual environments out of Git
```

`data/latest_digest.json` currently contains five live-news stories generated
locally and reviewed against available publisher text, plus one dated,
human-reviewed feature. Separate fictional demo data
remains available in `tests/fixtures/`.

## Current progress

Implemented: validated data models, atomic JSON storage, clearly labeled
fictional fixtures, topic filtering, publisher excerpts and source links,
approved-feed retrieval, freshness and duplicate checks, bounded article-text
reading, local Ollama summarization, and summary caching.
The five-story daily target is one cybersecurity item, two AI news items, and
two AI tools; eligible AI news fills gaps. A separately curated, dated
human-interest feature expires after 15 days. `refresh-local` publishes a
complete validated issue automatically when invoked; it is not scheduled.
The optional Gemini workflow and hosted deployment remain
unverified. The dashboard displays the saved issue without contacting either
model provider.

## Run locally (Windows PowerShell)

Run these commands from the repository root after creating the Python 3.12
virtual environment in Quick start. You can use it without activation:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe main.py validate
.\.venv\Scripts\python.exe main.py fetch-news
.\.venv\Scripts\python.exe main.py refresh-local
# Optional: bypass the buffer and check approved feeds again.
.\.venv\Scripts\python.exe main.py fetch-news --refresh-feeds
.\.venv\Scripts\python.exe main.py probe-articles
.\.venv\Scripts\python.exe main.py add-feature
# Optional draft/review path: Ollama must be running with the installed model.
.\.venv\Scripts\python.exe main.py generate-local
# Only if you intentionally want to replace an unreviewed draft:
.\.venv\Scripts\python.exe main.py generate-local --force
.\.venv\Scripts\python.exe main.py validate --draft
.\.venv\Scripts\python.exe main.py review-draft
# Only after checking each claim against the original publisher article:
.\.venv\Scripts\python.exe main.py approve-draft --reviewed
# Optional Gemini path, once your key/model and live feeds work:
.\.venv\Scripts\python.exe main.py generate
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open the localhost URL printed by Streamlit to see the saved live digest.
The main-page switch can show a two-story fictional sample, which is always labeled.

For a new machine with Python 3.11+ installed:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
# Optional activation; direct commands above avoid execution-policy issues.
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
```

macOS/Linux: `python3 -m venv .venv`, then `source .venv/bin/activate`,
`python -m pip install -r requirements-dev.txt`, and `python -m streamlit run app.py`.
Keys belong only in local .env or GitHub Secrets. Offline demo and tests need no keys.
Dependencies use bounded compatible ranges; a reproducible lock can follow after MVP validation.

For the local demo, set `OLLAMA_MODEL` in `.env` to a model already installed
in Ollama. The configuration template defaults to `qwen2:7b`.
`generate-local` fetches recent feed metadata and attempts to read selected
publisher article text. It sends that text, or a clearly labeled RSS fallback,
to the Ollama server at `127.0.0.1` one story at a
time, checks every JSON reply and story ID, then saves an ignored draft. It
checks that the model is already installed and never pulls one automatically.
An unreviewed draft is protected: another generation exits before calling
feeds or Ollama. Review and approve that draft first. Then you can run
`generate-local` again, even on the same day. `--force` explicitly replaces
an unreviewed draft; it still produces only a draft. Reapproving identical
content makes no change. A correction to an approved draft needs review again.
No cloud AI key is needed. Start the
Ollama app first; `ollama list` should show `qwen2:7b`. A failed run keeps
the previous visible digest. The model may still infer details that source
text does not prove. The automatic path checks detectable issues and retains
the prior issue on failure; it cannot guarantee every sentence is true.
The optional `review-draft` prints each source link, excerpt, explanation, and takeaway
side by side. Open each original article, check every factual claim, and edit
the draft if needed. `approve-draft --reviewed` copies the checked draft to
`data/latest_digest.json`, which the dashboard reads. The flag records an
intentional human review; it cannot prove that a claim is true.
Approval also saves the links that readers have already seen, with the last
approval time and number of appearances. A draft does not count as shown.
`refresh-local` publishes without manual approval. It uses unseen stories in
the saved buffer first. After that buffer is exhausted, every further refresh
checks the approved feeds again and accepts newly found AI stories regardless
of category. It reuses saved explanations for repeated links, so Ollama only
sees new links. The buffer is Git-ignored `data/story_pool.json`: RSS metadata
only, no article HTML or model prompt. Five distinct cards, publisher fields,
unsupported numbers/names/quotes, injected links, and copy defects are
checked before atomic publication. A failed check keeps the previous issue.
The automatic local refresh prints its per-story progress and has a five-minute
time budget. If that budget expires, the previous complete issue stays visible.
The first issue can still be slow because each new article is read and summarized
by the installed 7B model; subsequent repeats reuse saved summaries.
News fetching still requires internet.

### Summary cache

`refresh-local` saves each passing new summary immediately in the Git-ignored
`data/summary_cache.json`. If the third article times out after two successful
summaries, the next attempt can reuse those first two. A cache entry does not
count as a story shown to the reader; display history changes only when a full
digest is published. The optional draft commands continue to generate normally.

For new candidate cards, Python first reads the article through the approved
HTTPS reader and computes a fingerprint of the exact text, publisher metadata,
prompt, JSON schema, installed Ollama model's weight digest, and summary-policy
version. A matching entry avoids the slow model call. Changed article text,
prompt, or model weights cause a cache miss. Current source and copy-quality
checks run again on cache hits. Previously published cards reused as repeats
still follow the existing saved-digest reuse policy.

The file contains short cards, fingerprints, and save times, never full article
bodies, prompts, or credentials. Entries expire after seven days; at most 200
entries and 2 MB are retained. Corrupt caches are ignored with a terminal note,
and atomic writes protect the previous file from partial replacement. As with
the rest of this local MVP, run one refresh at a time; concurrent cache writers
can lose reusable entries and cause extra generation. No database or dependency
was added. This cache avoids repeated inference; a completely new story still
needs its first model call, and article reads still require internet.

To test cache behavior offline:
`python -m pytest -q tests/test_summary_cache.py tests/test_automatic.py`.
During a normal `python main.py refresh-local`, look for `Used saved summary`
and the final counts of reused, newly needed, and saved summaries. The cache
starts empty and fills with future passing results; old failed runs cannot be
recovered retroactively. Deleting only `data/summary_cache.json` resets the
optimization without deleting the visible digest or display history.

### Model configuration

Set `OLLAMA_MODEL` to an already installed model. The default is `qwen2:7b`.
The application does not install or download model weights. Before switching
models, compare factual support, JSON validity, and generation speed on the
same article inputs. Cached summaries are separated by model identity.

### Feed and download safety

The collector contacts only the nine verified publisher RSS endpoints and the
selected article URLs on their matching approved publisher domains. It uses
the operating system's trusted certificates with TLS chain and hostname
verification, requires HTTPS, rejects feed redirects, and limits each RSS
response to 2 MB. Feed XML with DOCTYPE or ENTITY declarations is rejected.
Only dated AI entries with approved publisher-owned HTTPS article URLs enter
the digest or buffer. The article reader accepts only HTML, rejects redirects, limits
each page to 2 MB, and extracts visible article paragraphs without running
scripts or loading assets. It does not download attachments, installers, or
executables. RSS and HTML bytes necessarily arrive in memory during a fetch;
they are not saved as downloaded files or executed. Article links are shown
for a deliberate user click. The local summarizer talks
only to `127.0.0.1` with proxy use disabled. These measures reduce exposure;
no software can promise that external content is absolutely risk-free.

### Where the summaries live

AI Signal sends a selected headline plus up to 12,000 characters of readable
article text to the already installed Ollama model at `127.0.0.1`. If the
publisher page cannot be read, the optional draft path can use the short RSS
preview and label that fallback. Automatic publication instead tries another
approved article and keeps the old issue if five readable stories are unavailable.
It does not create an Ollama chat history or send the local prompt
to a cloud model. Full article text stays in memory and is not saved.
`refresh-local` writes `data/latest_digest.json` automatically after its
checks. The optional draft path saves ignored `data/draft_digest.json` for
manual review. The dashboard reads only the visible file.
The digest JSON is intended to be committed to a future GitHub repository, so
its public-feed text would then become visible in that repository.

The model weights are a separate local Ollama installation, usually under
`C:\Users\<username>\.ollama\models` on Windows unless `OLLAMA_MODELS` was
changed. [Ollama's FAQ](https://docs.ollama.com/faq#where-are-models-stored)
documents that path, and [its privacy policy](https://ollama.com/privacy)
says local prompts and responses are not collected or transmitted to Ollama.
This project does not inspect or control Ollama's diagnostic logging settings.

The optional `generate` command uses Gemini instead. To try it later, add a
Google AI Studio API key to `GEMINI_API_KEY` in `.env` and set `GEMINI_MODEL`
to a supported model. Do not paste keys into chat. This path also saves JSON
only after validation.

### Gemini key setup and safety

1. Open Google's [Gemini API key guide](https://ai.google.dev/gemini-api/docs/api-key)
   and follow its **Create or view a Gemini API Key** link to Google AI Studio.
   Sign in, accept the terms, and create or copy a key in your project. A new
   account may already have a default project and key.
2. In AI Studio **Projects**, check that the key's project says **Free Tier** if
   you want to avoid paid API usage. Check the [model pricing page](https://ai.google.dev/gemini-api/docs/pricing)
   and your project's model limits. For example, Google's current documentation
   lists `gemini-3.5-flash-lite` with a free tier and structured-output support;
   confirm it is available to your own project before using it.
3. From the repository root in PowerShell, run `Copy-Item .env.example .env`.
   Open the new `.env` locally and replace `your_key_here` with your key. Set
   `GEMINI_MODEL=gemini-3.5-flash-lite` if AI Studio offers that model to you.
4. Run `main.py fetch-news`, then `main.py generate`, then `main.py validate`
   using the `.venv` Python commands above. The first command tests the selected
   feeds; generation needs at least one qualifying current item.

Treat the key like a password: never paste it in chat, place it in code, commit
`.env`, or expose it in a browser page. This repository ignores `.env`; the
Streamlit app reads saved JSON and does not need the Gemini key. When the
repository exists, use a GitHub Actions **Secret** named `GEMINI_API_KEY`.
If a key is exposed, replace it in AI Studio, disable the old one, and review
usage. [Google's key guidance](https://ai.google.dev/gemini-api/docs/api-key)
explains these controls.

The optional Gemini path now sends selected public publisher article text when
readable, up to 12,000 characters per item, or the RSS preview when unavailable.
Do not use it if you do not want article text sent to Google's cloud API. The
app does not put your API key in the prompt. Free-tier prompts and
responses may be used by Google to improve its services and may be reviewed by
humans, so never put private or confidential data into these feeds or prompts.
The [Gemini API terms](https://ai.google.dev/gemini-api/terms) explain this
tradeoff. Free-tier capacity is limited by model and project; check your
[billing tier](https://ai.google.dev/gemini-api/docs/billing/) and usage in AI
Studio. No internet service can be promised risk-free, and generated summaries
still need a human spot-check for factual accuracy.

## Architecture

Local automatic workflow: approved RSS → saved candidate buffer → unseen-first
selection → approved article text for new links → local Ollama → mechanical
checks → atomic dashboard JSON → Streamlit dashboard.
Python handles collection, validation, storage, and presentation. The model only explains
source-provided article text or a labeled RSS fallback. Source URLs and dates stay under Python's control.
The published JSON drives the dashboard; opening the page does not call Ollama.

The first digest uses the usual 48-hour window, with up to 72 hours for gaps
and cybersecurity. Later runs use saved unseen links up to five days old
before repeating anything. While this buffer has unseen eligible links, no
feed request is needed. Once it is exhausted, each refresh fetches approved
feeds again and takes newly found AI stories by recency without a category
requirement. If fewer than five unseen stories exist, the remaining slots use
least recently shown links. Previously published cards may fill a shortage
beyond five days as a last resort, showing their true publication dates. The
current five-card issue remains visible if five distinct verified cards cannot
be assembled. A draft does not count as shown. The separately curated feature
may repeat within its verified fifteen-day age window.

`ai_pulse/models.py` describes allowed data and rejects unsafe URLs.
`ai_pulse/article_text.py` reads only bounded HTML on each item's approved
publisher domain. `ai_pulse/featured_story.py` holds a dated editorial feature;
it is not a dynamically discovered RSS item and ages out after 15 days.
`ai_pulse/storage.py` checks data before replacing a saved file.
`ai_pulse/quality.py` catches repeated or visibly broken model prose before
a draft or automatic issue is shown. Mechanical checks cannot verify every
factual claim, so each card still links to the original publisher article.
`main.py` provides explicit local commands. `ai_pulse/ollama.py` contacts only
the local Ollama server, with proxies disabled for that request. `app.py` only reads data.
Each Python function has a short plain-English docstring explaining its job.
The dashboard uses Streamlit's built-in light theme and controls, with no
third-party fonts or browser scripts. It puts the story and reader takeaway
first, with the original source link in every card. The RSS preview is behind
an optional expander; cut-off publisher excerpts stop at the last full sentence.
If a future summary uses only an RSS excerpt, that is noted inside its source
expander. Topic filtering and
fictional sample stories are available on the page.

The daily target is one AI/cybersecurity story, two other AI news stories,
and two AI tool stories. Missing categories are filled with other eligible AI
news without invented labels. Once the same-day buffer is exhausted, category
targets are relaxed for newly fetched articles. The visible issue keeps five
distinct cards; if five verified cards do not exist yet, it keeps the last
complete issue.

## GitHub setup after you create the repository

Upload the contents of the project folder as the repository root. Do not
commit `.env`. The optional
[workflow](.github/workflows/daily-digest.yml) is manual-only; scheduled
refreshes are not configured. If you choose to try its Gemini path, add
`GEMINI_API_KEY` as a repository Secret and `GEMINI_MODEL` as a Variable. The
job runs offline tests, generates a draft in its temporary runner, and validates
it. Its temporary draft and history changes are not saved by GitHub Actions.
It has read-only repository permission and does not commit or publish
model output. The `refresh-local` command publishes automatically
on a computer running Ollama; connecting it to a daily scheduler and a
persistent hosted dashboard remains a separate setup step. Automatic checks
cannot guarantee every model-written sentence is factually correct.

## Tests and limitations

Run `python -m pytest -q` for the offline test suite. It covers JSON storage,
unsafe links, previous-issue preservation, dashboard filtering, RSS selection,
repeat history, summary caching, and category boundaries. The release snapshot
passed all 87 tests, and its included five-story issue validated successfully.
Run `python main.py validate` to check the saved issue on your own machine.

- Opening the dashboard reads saved JSON; it does not refresh the news.
- Fresh local generation needs internet access and a running Ollama instance.
- A timeout or incomplete automatic refresh keeps the previous complete issue.
- Automated checks cannot prove every model-written claim is accurate.
- The human-interest feature is curated separately and expires after 15 days.
- Gemini integration, GitHub Actions dispatch, and public deployment require
  separate live verification. Scheduling is not configured.
