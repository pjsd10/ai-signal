# AI Signal sources

The collector uses the nine publisher-owned HTTPS RSS feeds configured in
`ai_pulse/fetch_news.py`. Public RSS collection does not require a news API key.
Feed availability can change, and one feed failing does not stop the others.

| Publisher | Configured RSS feed | Coverage and tradeoffs |
| --- | --- | --- |
| OpenAI News | [News RSS](https://openai.com/news/rss.xml) | Original product, model, research, and safety announcements; first-party perspective. |
| Google DeepMind | [Blog RSS](https://deepmind.google/blog/rss.xml) | Research and model releases; some linked articles use a different Google domain and are excluded by the current allowlist. |
| The Verge | [General RSS](https://www.theverge.com/rss/index.xml) | Independent technology reporting, consumer impact, and policy; the broad feed requires AI filtering. |
| Ars Technica | [Technology Lab RSS](https://feeds.arstechnica.com/arstechnica/technology-lab) | Technical reporting and cybersecurity; the feed includes topics outside AI. |
| Microsoft Security Blog | [Security RSS](https://www.microsoft.com/en-us/security/blog/feed/) | Security research and products; first-party claims need context. |
| Microsoft Research | [Research RSS](https://www.microsoft.com/en-us/research/blog/feed/) | Research methods and model updates; technical content needs plain-English explanation. |
| Microsoft Official Blog | [Official RSS](https://blogs.microsoft.com/feed/) | Product and company announcements; AI relevance must be checked. |
| ImportAI | [Newsletter RSS](https://importai.substack.com/feed) | Research commentary; weekly posts may cover multiple underlying stories. |
| Ben's Bites | [Newsletter RSS](https://www.bensbites.com/feed) | Tools and practical applications; newsletter cadence and restricted articles can limit coverage. |

Recorded HTTPS/XML checks on October 11, 2026 found valid dated AI entries
in the additional feeds: Microsoft Research (7), Microsoft Official Blog (9),
ImportAI (20), and Ben's Bites (9). These are historical check results, not
the number of stories that every future refresh will receive.

The configured article domains are `openai.com`, `deepmind.google`,
`theverge.com`, `arstechnica.com`, `microsoft.com`, `importai.substack.com`,
and `bensbites.com`, together with their subdomains. For example, a DeepMind
feed entry linking to `blog.google` is skipped because that domain is not in
its configured article allowlist. Adding a new publisher requires an explicit
configuration change; a feed cannot expand its own allowed destinations.

## Collection and content rules

- Require HTTPS, valid TLS certificates, and matching hostnames for remote
  reads. Reject redirects rather than following a new destination.
- Treat headlines, excerpts, and article text as untrusted data. Reject
  unsafe links and XML entity declarations, bound responses to 2 MB, and
  never execute publisher scripts or fetch page assets.
- Exclude undated items, normalize tracking parameters, and remove duplicate
  links and headlines. Keep the publisher's original publication date visible.
- Prefer fresh items for the first issue, with a wider window for gaps.
  Repeated runs can search up to five days back, using unseen stories before
  previously shown stories. Older verified saved cards are a last resort.
- Target one AI-and-cybersecurity story, two AI news stories, and two AI tools.
  Fill category gaps with eligible AI news rather than inventing labels.
  Keep AI-for-Good stories in the separate dated human-interest feature.
- Read approved article text before automatic summarization. An unreadable
  article is skipped in that path; the optional manual draft path can use a
  clearly labeled RSS excerpt instead.
- Reuse a complete saved issue when automatic generation cannot produce a
  complete validated replacement. Automated checks reduce detectable errors
  but do not establish that every claim is factually correct.

Source links are available on each dashboard card so readers can consult the
publisher's report and distinguish first-party announcements from independent
coverage. No source mix guarantees five new qualifying stories every day.
