# Changelog

All notable changes to **Gang of Four** are recorded here. This project aims to
follow [Semantic Versioning](https://semver.org/).

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
