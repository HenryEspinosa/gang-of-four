# Gang of Four

**Ask one question, get the wisdom of several AI models at once.** Gang of Four
is a desktop chat app (Windows, macOS, Linux) that sends your question to several
leading AI models *simultaneously* — then has another model read all their
answers and write a single combined reply that tells you where they **agree**,
where they **disagree**, and what each one uniquely added.

Think of it as a small panel of experts instead of a single chatbot.

### Why you might want it

- **Answers backed by live web search, with sources.** Built on the
  [Perplexity](https://www.perplexity.ai/) API, every answer can be grounded in
  current web results and shows its citations — so you get up-to-date, checkable
  facts rather than a model guessing from old training data. You can point the
  search at the general web, academic/scholarly sources, or U.S. SEC filings.
- **A built-in second opinion.** Because the same question is answered by
  multiple models, it's much easier to *trust* an answer when they all agree —
  and to *catch* a shaky one when they don't. The combined reply explicitly flags
  contradictions instead of hiding them.
- **Many top models, one key, no extra subscriptions.** Through Perplexity you
  reach models from OpenAI (ChatGPT), Google (Gemini), Anthropic (Claude), xAI
  (Grok), and Perplexity's own Sonar — all from a single API key, without
  separate accounts or monthly plans for each one. You pay only for what you use.
- **Diverse strengths in one go.** Different models are good at different things;
  consulting several at once surfaces insights any single one would miss.
- **It's yours and it's local.** Your conversations are saved on your own
  computer, not locked inside someone else's web account. There's also a
  single-model mode for when you just want a quick answer from one model.

This replicates Perplexity's **Model Council** — a feature normally only in its
consumer app — and goes further by letting you mix models from *different
providers* in one council.

> **The name** — after Susan James, "the Gang of Four," from Peter Watts'
> *Blindsight*: a linguist surgically partitioned into four distinct
> personalities sharing one body. Same idea here — several minds deliberating,
> resolved into one voice.

## How it talks to Perplexity

The app uses **two Perplexity API surfaces**, and routes each model to the right
one automatically (any model id containing `/` goes to the Agent API):

| Surface | Endpoint | Models | Streaming |
|---|---|---|---|
| **Sonar Chat API** | `POST /chat/completions` (OpenAI-compatible) | `sonar`, `sonar-pro`, `sonar-reasoning-pro`, `sonar-deep-research` | yes |
| **Agent API** | `POST /v1/agent` (Responses-style) | provider-prefixed third-party models: `openai/gpt-5.5`, `google/gemini-3.1-pro-preview`, `anthropic/claude-opus-4-8`, `xai/grok-4.3`, … | no (returned as one chunk) |

A few consequences baked into the client (`council.py`):

- The Agent API does **not** accept Sonar sampling params (`temperature`, etc.),
  so they are omitted for those models. Search grounding is expressed as *tools*
  (`web_search`, plus `finance_search` in `sec` mode) rather than a `search_mode`.
- Citations are pulled from whichever shape the response uses — Sonar's
  `citations`/`search_results`, or the Agent API's `search_results` output item
  and content annotations.
- The model list is fetched **live** from `/v1/models` when an API key is set, so
  it stays current; it falls back to the built-in catalogue in `council.py` when
  offline or unconfigured.

## Features

- **Council mode** — fan a query across the models you choose (Sonar *and*
  third-party), run them concurrently, and stream a synthesized answer.
- **Side-by-side panel** — each member's raw answer (with sources) in a
  collapsible card on the right, updating live as members finish.
- **Single-model mode** — toggle the council off to stream from one model picked
  in the top bar.
- **Persistent chat history** — conversations are saved to disk and listed in the
  left sidebar; reopen any chat to continue it across sessions. Each row has a
  checkbox for **multi-select bulk delete** (plus a "All" select-all box).
- **Streaming**, markdown rendering, citations, multi-turn history.
- **Settings** — API key, council members, synthesizer model, single-chat model,
  temperature, search mode (web / academic / sec), and chat font size.

### Where things are stored

The app uses each platform's standard per-user location (resolved via Qt's
`QStandardPaths`), under a `perplexity-council` folder:

| | Config & API key | Conversations |
|---|---|---|
| **Linux** | `~/.config/perplexity-council/config.json` | `~/.local/share/perplexity-council/conversations/` |
| **Windows** | `%LOCALAPPDATA%\perplexity-council\config.json` | `%LOCALAPPDATA%\perplexity-council\conversations\` |
| **macOS** | `~/Library/Preferences/perplexity-council/config.json` | `~/Library/Application Support/perplexity-council/conversations/` |

The API key can also be supplied via the `PERPLEXITY_API_KEY` environment
variable, which is used when no key has been saved. One JSON file per chat.

## Run

```bash
./run.sh
```

The script runs the app directly if `PySide6` + `requests` already import;
otherwise it creates a `.venv`, installs dependencies, and launches. (If
`python3-venv` is unavailable it falls back to a `--user` install.) Or manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

On a fresh Ubuntu box you may also need the Qt runtime libs:

```bash
sudo apt install -y libxcb-cursor0 libegl1
```

## Setup

**This app requires your own Perplexity API key** — it talks directly to
Perplexity on your behalf, so without a key it can't answer anything.

1. **Get a Perplexity API key.** Follow Perplexity's own documentation, which is
   the authoritative, up-to-date source for the exact steps:
   <https://docs.perplexity.ai/>. In short, you'll create a Perplexity account
   and generate an API key (it starts with `pplx-`). Note that the API is
   **pay-as-you-go** — you add billing/credits and pay per question (typically a
   few cents each); it's billed separately from any Perplexity Pro subscription.
2. **Add the key to the app:** launch it → **⚙ Settings** → paste the key →
   **Save**. (The app prompts for this on first launch.) Keep your key private —
   don't share it or commit it anywhere. Advanced users can instead set the
   `PERPLEXITY_API_KEY` environment variable.
3. Type a question and press **Ctrl+Enter** (or click **Send**).

## Project layout

| File | Purpose |
|---|---|
| `app.py` | PySide6 GUI — main window, chat/council/history panels, settings dialog |
| `council.py` | Perplexity API client (Sonar + Agent), model catalogue, council orchestration (members in parallel → streamed synthesis) |
| `config.py` | Load/save settings under `~/.config/perplexity-council/` |
| `store.py` | Persist conversations as JSON under `~/.local/share/perplexity-council/` |
| `run.sh` | Launcher: venv bootstrap + dependency install |
| `gang-of-four.desktop` | Application-menu entry |
| `assets/` | App icons (`icon_*.png`, `icon.svg`) |

## Optional: add to the application menu

```bash
cp gang-of-four.desktop ~/.local/share/applications/
```

Before copying it, edit the `Exec`, `Path`, and `Icon` lines in the `.desktop`
file to point at the folder where you cloned this repo (they ship with a
`/path/to/gang-of-four` placeholder).

## License

[MIT](LICENSE) © Enrique Espinosa
