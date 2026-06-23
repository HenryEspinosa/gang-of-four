# Changelog

All notable changes to **Gang of Four** are recorded here. This project aims to
follow [Semantic Versioning](https://semver.org/).

## [0.3.1] — 2026-06-23

### Fixed
- **`<think>` tag leakage removed** — `sonar-reasoning-pro` and other
  reasoning models embed `<think>…</think>` blocks in their output. These are
  now stripped before text reaches the UI, both in streaming (stateful chunk
  filter) and non-streaming paths.
- **About dialog no longer clips its content** — replaced the fixed 380 px
  width with a 460 px minimum and added `adjustSize()` so the dialog resizes
  to fit its text on all platforms.
- **Stale council model IDs auto-pruned** — on startup, any saved council
  member whose ID is no longer in the live `/v1/models` catalogue is silently
  removed from config so it never causes a query-time API error.
- **Model dropdown now scrollable** — model selectors cap at 20 visible items
  and show a scrollbar when the live catalogue returns more entries than fit.
- **Third-party models under the `perplexity/` prefix now work** — Perplexity
  lists models like GLM 5.2 as `perplexity/glm-5.2` in the catalogue. These
  are now correctly routed to the Agent API instead of being misrouted to the
  Sonar Chat API (which rejected them) or excluded from the list.
- **Agent API model fallback list updated** — the offline/no-key fallback now
  lists conservative, current IDs (`gpt-4o`, `gemini-2.5-pro-preview`, etc.)
  instead of speculative future IDs.
- **Model labels auto-generated** — `display_name()` now derives a readable
  label from any provider-prefixed model ID (e.g. `anthropic/claude-opus-4-8`
  → *Claude Opus 4.8 (Anthropic)*), so new models from the live catalogue
  always show a clean name rather than a raw ID string.

## [0.3.0] — 2026-06-22

### Added
- **Stop button** — the Send button turns red and becomes Stop while a request
  is running. Clicking it cancels the stream, marks the partial response
  *"— stopped —"*, and re-enables the input immediately.
- **AI-generated chat titles** — after the first response in a new conversation,
  the synthesizer model generates a 5–8 word descriptive title that replaces
  the raw truncated question text in the history sidebar.
- **About dialog** — version number, description, GitHub link, and license,
  accessible via the About button in the top bar.

### Fixed
- **Council no longer fails when one model fails** — app-internal message keys
  (introduced for the document-upload UI) were being sent to the Sonar Chat API,
  causing HTTP 400 errors on every Sonar-path member. A new `_api_messages()`
  helper strips non-API keys at the boundary.
- **Synthesis failure now surfaces member answers** — if the synthesis step
  fails after members succeed, the longest individual answer is shown rather
  than a dead-end error.

## [0.2.0] — 2026-06-22

### Added
- **Document upload** — attach a PDF, Word (.docx), Excel (.xlsx), PowerPoint
  (.pptx), or plain-text/CSV/Markdown file to any chat with the new 📎 button.
  The document's text is injected into the conversation so every council member
  and the synthesizer can reason over it.
- **Built-in OCR** — scanned PDFs are recognised automatically and run through
  Tesseract OCR without any extra install step. Tesseract and the English
  language model are bundled inside every platform release.

### Fixed
- **Garbled text / mojibake** (`â€™` instead of `'`) — Perplexity's SSE stream
  was being decoded as ISO-8859-1 because the server omits a `charset` header.
  Forcing UTF-8 before the streaming loop fixes all curly quotes, em-dashes, and
  other non-ASCII characters.

## [0.1.0] — 2026-06-18

First public release: a native, cross-platform desktop app that asks several AI
models the same question at once and synthesizes one combined, web-grounded
answer.

### Features
- **Council mode** — fan a question across several models in parallel, then
  stream a synthesized answer that highlights agreement, disagreement, and each
  model's unique points.
- **Cross-provider councils** — mix Perplexity Sonar with OpenAI (GPT), Google
  (Gemini), Anthropic (Claude), and xAI (Grok) models, all through a single
  Perplexity API key.
- **Web-grounded answers with citations** — choose web, academic, or SEC search
  grounding.
- **Single-model mode** — talk to just one model when that's all you need.
- **Persistent local chat history** — conversations saved on your machine, with
  multi-select delete.
- **Markdown rendering, streaming, adjustable font size.**
- **Cross-platform builds** — single-file `.exe` (Windows), `.app` bundle
  (macOS), and a Linux binary, produced automatically on each release.
- Settings and history are stored in each platform's native per-user location.

### Fixed (pre-release hardening)
- **Chats no longer hang.** Perplexity's live model catalogue now returns its own
  model as `perplexity/sonar`; that prefixed id was being routed to the Agent
  API endpoint, where it hung with no response. It is now correctly routed to the
  Sonar Chat API.
- **Streamed answers no longer come back empty.** Perplexity embeds raw newlines
  inside streamed citation data, which split a single response across lines and
  broke parsing. The stream parser now reassembles split payloads.

[0.1.0]: https://github.com/HenryEspinosa/gang-of-four/releases/tag/v0.1.0
