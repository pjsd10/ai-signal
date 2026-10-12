# AI Signal

**AI news, explained in plain English.** A Python and Streamlit project that turns approved publisher articles into a readable briefing using local Ollama summarization.

## What it does

- Displays five news cards covering AI, cybersecurity, and tools, plus a separately curated AI-for-Good feature.
- Shows concise explanations, “Why it matters,” publication dates, publisher excerpts, and original article links.
- Filters topics, avoids duplicate stories, and caches checked summaries to reduce repeated model calls.

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

Approved RSS feeds → article text → local Ollama → validation and caching → saved JSON → Streamlit.

`app.py` displays the dashboard; `main.py` runs the pipeline; `ai_pulse/` contains the processing modules. `assets/`, `data/`, and `tests/` hold artwork, the saved issue, and offline tests.

Remote collection requires approved HTTPS sources and TLS verification. Secrets and local caches are Git-ignored. Automated checks reduce errors but cannot guarantee factual accuracy. See [source details](SOURCE_OPTIONS.md).

Run the offline tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
