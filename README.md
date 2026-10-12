# AI Signal

**AI news, explained in plain English.** A Python and Streamlit project that turns approved publisher articles into a readable briefing using local Ollama summarization.

## What it does

- **Collects relevant stories:** reads approved publisher RSS feeds, checks publication dates, and retrieves readable article text for the automatic briefing.
- **Explains the news:** uses local Ollama to write a plain-English summary and a “Why it matters” takeaway for each story.
- **Builds a focused briefing:** presents five news cards across AI, cybersecurity, and tools, plus a separately curated, dated AI-for-Good feature.
- **Keeps sources accessible:** shows the publisher and publication date, with an expandable RSS excerpt and a link to the original article.
- **Supports quick browsing:** lets readers filter by topic and see when the displayed issue was generated.
- **Makes repeat runs practical:** checks for duplicate stories, caches passing summaries, and preserves the last complete issue when a refresh cannot finish successfully.

## Run the dashboard

With Python 3.12 installed, run from the repository root in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe main.py validate
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The included saved issue works without an API key or Ollama. Opening or reloading the dashboard displays that issue; it does not generate fresh news.

## Generate a new issue

Start Ollama with `qwen2:7b` already installed, then run:

```powershell
.\.venv\Scripts\python.exe main.py refresh-local
```

Generation needs internet access and may take several minutes. The app does not install models automatically. Daily scheduling is not configured.

## How it works

AI Signal separates **batch generation** from **dashboard rendering**. `main.py refresh-local` runs the Python pipeline; `app.py` displays its saved output without invoking the model.

**RSS → candidate selection → article extraction → LLM inference → validation/cache → JSON → Streamlit**

1. **Ingest and select.** `feedparser` parses approved publisher feeds into Pydantic data models. Python checks publication dates and publisher domains, canonicalizes URLs to remove tracking parameters, and deduplicates candidates. A local JSON story pool and display history support recency, category preferences, and unseen-story selection.

2. **Extract source evidence.** The article reader retrieves HTML over HTTPS with certificate and hostname verification, rejects redirects, and limits responses to 2 MB. It extracts article paragraphs without executing JavaScript or loading page assets, retaining up to 12,000 characters for the model.

3. **Run local inference.** Ollama serves the configured `qwen2:7b` model through its loopback REST API. Each article is summarized with a source-grounded prompt, `temperature=0`, and a JSON Schema specifying the explanation and “Why it matters” fields. Publisher text is explicitly treated as untrusted input.

4. **Validate the response.** Pydantic checks the output schema and story IDs are matched to the inputs. Python supplies titles, URLs, dates, and categories from source metadata rather than model output. Additional heuristic checks reject copied excerpts, broken prose, and detectable unsupported details.

5. **Cache and publish.** Passing summaries are cached using a SHA-256 fingerprint of source evidence, prompt, model identity, schema, and validation-policy version. Cache hits are revalidated. A complete five-story digest is written to `data/latest_digest.json` using atomic file replacement; an unsuccessful refresh preserves the previous issue.

6. **Render the briefing.** Streamlit loads the validated JSON and displays topic filters, dated cards, source excerpts, and article links. The AI-for-Good feature is curated separately and expires after 15 days. Browser reloads display the saved issue; they do not trigger ingestion or inference.

The processing modules live in `ai_pulse/`. This design uses local JSON persistence rather than a database, and sends article text directly to the model without RAG or a vector store. Full article bodies are not persisted; secrets and local caches are Git-ignored. Heuristic checks reduce errors but are not a factual-verification guarantee. See [source details](SOURCE_OPTIONS.md).

Run the offline tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
