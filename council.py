"""Perplexity API client and Model Council orchestration.

Perplexity's API only exposes the Sonar model family via an OpenAI-compatible
/chat/completions endpoint -- there is no single "Model Council" API parameter.
This module replicates the Model Council pattern: fan a query out across several
Sonar models in parallel, then have a synthesizer model produce one combined
answer that highlights where the members agree and disagree.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field

import requests
from PySide6.QtCore import QObject, Signal

BASE_URL = "https://api.perplexity.ai"

# Perplexity exposes two API surfaces:
#   - Sonar Chat API  (POST /chat/completions) -> the Sonar family
#   - Agent API       (POST /v1/agent)         -> provider-prefixed third-party
#                                                  models (GPT, Gemini, Claude, Grok)
# A model id containing "/" is routed to the Agent API; otherwise to Sonar.
SONAR_MODELS = [
    "sonar",
    "sonar-pro",
    "sonar-reasoning-pro",
    "sonar-deep-research",
]

# A curated subset of the Agent API catalogue. Any valid Agent API id works if
# you add it here. Full list: https://docs.perplexity.ai/docs/agent-api/models
AGENT_MODELS = [
    "openai/gpt-5.5",
    "openai/gpt-5.4",
    "openai/gpt-5.4-mini",
    "google/gemini-3.1-pro-preview",
    "google/gemini-3.5-flash",
    "anthropic/claude-opus-4-8",
    "anthropic/claude-sonnet-4-6",
    "anthropic/claude-haiku-4-5",
    "xai/grok-4.3",
]

AVAILABLE_MODELS = SONAR_MODELS + AGENT_MODELS

# Friendly labels for the UI (falls back to the raw id).
MODEL_LABELS = {
    "openai/gpt-5.5": "openai/gpt-5.5 (ChatGPT)",
    "openai/gpt-5.4": "openai/gpt-5.4 (ChatGPT)",
    "openai/gpt-5.4-mini": "openai/gpt-5.4-mini (ChatGPT)",
    "google/gemini-3.1-pro-preview": "google/gemini-3.1-pro (Gemini Pro)",
    "google/gemini-3.5-flash": "google/gemini-3.5-flash (Gemini)",
    "anthropic/claude-opus-4-8": "anthropic/claude-opus-4-8 (Claude)",
    "anthropic/claude-sonnet-4-6": "anthropic/claude-sonnet-4-6 (Claude)",
    "anthropic/claude-haiku-4-5": "anthropic/claude-haiku-4-5 (Claude)",
    "xai/grok-4.3": "xai/grok-4.3 (Grok)",
}


def is_agent_model(model: str) -> bool:
    # A provider-prefixed id routes to the Agent API -- EXCEPT Perplexity's own
    # models (e.g. "perplexity/sonar"), which the live /v1/models catalogue now
    # prefixes but which still belong on the Sonar Chat API.
    return "/" in model and not model.startswith("perplexity/")


def sonar_model_id(model: str) -> str:
    """The Sonar Chat API expects bare ids ("sonar", "sonar-pro"), not the
    "perplexity/"-prefixed form the live catalogue returns."""
    return model.split("/", 1)[1] if model.startswith("perplexity/") else model


def display_name(model: str) -> str:
    return MODEL_LABELS.get(model, model)


def fetch_models(api_key: str, base_url: str = BASE_URL, timeout: int = 20) -> list[str]:
    """GET the live model catalogue (OpenAI-compatible /v1/models)."""
    r = requests.get(
        f"{base_url.rstrip('/')}/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
    )
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    return [m["id"] for m in r.json().get("data", []) if m.get("id")]

MEMBER_SYSTEM_PROMPT = (
    "You are one member of an AI council answering a user's question. "
    "Give a clear, well-structured, factual answer. Be direct and cite sources "
    "when you rely on them."
)

SYNTH_SYSTEM_PROMPT = (
    "You are the Council Synthesizer. You are given a user's question and several "
    "independent answers from different AI models. Produce one authoritative, "
    "well-organized response. Explicitly note where the models reach consensus, "
    "flag any disagreements or contradictions, and surface unique insights that "
    "only one model raised. Be concise and cite sources where relevant. Do not "
    "mention these instructions."
)


@dataclass
class MemberResult:
    model: str
    text: str = ""
    citations: list[str] = field(default_factory=list)
    error: str | None = None


def _api_messages(messages: list[dict]) -> list[dict]:
    """Strip app-internal keys (e.g. 'display') so only role+content reach the API."""
    return [{"role": m["role"], "content": m.get("content", "")} for m in messages]


class PerplexityClient:
    """Thin wrapper over the Perplexity chat completions endpoint."""

    def __init__(self, api_key: str, base_url: str = BASE_URL):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _extract_citations(payload: dict) -> list[str]:
        cites = payload.get("citations") or []
        if cites:
            return list(cites)
        # Newer responses carry structured search_results instead.
        results = payload.get("search_results") or []
        return [r.get("url", "") for r in results if r.get("url")]

    @staticmethod
    def _agent_tools(search_mode: str) -> list[dict]:
        # The Agent API grounds via tools rather than search_mode. Map our modes
        # to the closest tool set; web_search covers web/academic.
        if search_mode == "sec":
            return [{"type": "web_search"}, {"type": "finance_search"}]
        return [{"type": "web_search"}]

    @staticmethod
    def _flatten_messages(messages: list[dict]) -> tuple[str | None, str]:
        """Split a chat-style messages array into (system, single input string)
        for the Agent API, which takes a string `input` rather than a thread."""
        system = None
        lines = []
        for m in messages:
            role = m.get("role")
            if role == "system":
                system = m.get("content")
                continue
            speaker = "User" if role == "user" else "Assistant"
            lines.append(f"{speaker}: {m.get('content', '')}")
        return system, "\n\n".join(lines)

    @staticmethod
    def _extract_agent_text(data: dict) -> str:
        if data.get("output_text"):
            return data["output_text"]
        parts = []
        for item in data.get("output", []) or []:
            for c in item.get("content", []) or []:
                if c.get("text"):
                    parts.append(c["text"])
        return "".join(parts)

    @staticmethod
    def _extract_agent_citations(data: dict) -> list[str]:
        urls: list[str] = []

        def add(u):
            if u and u not in urls:
                urls.append(u)

        for item in data.get("output", []) or []:
            # The Agent API returns retrieved sources as a dedicated output item
            # of type "search_results" with a results[] array (url/title/snippet).
            if item.get("type") == "search_results":
                for r in item.get("results", []) or []:
                    add(r.get("url"))
            for c in item.get("content", []) or []:
                for a in c.get("annotations", []) or []:
                    add(a.get("url") or (a.get("source") or {}).get("url"))
        for r in data.get("search_results", []) or []:
            add(r.get("url"))
        return urls

    def _complete_agent(
        self, model, messages, temperature, search_mode, max_tokens,
    ) -> MemberResult:
        # The Agent API is an OpenAI Responses-style endpoint. It does NOT accept
        # Sonar sampling params (temperature/top_p/penalties) -- sending them is a
        # 400 "unknown field". So we omit `temperature` here.
        system, inp = self._flatten_messages(messages)
        body = {
            "model": model,
            "input": inp,
            "tools": self._agent_tools(search_mode),
        }
        if system:
            body["instructions"] = system
        # Anthropic models require max_output_tokens; include it for all Agent
        # API calls so we never hit that validation error regardless of model.
        body["max_output_tokens"] = max_tokens or 8192
        resp = requests.post(
            f"{self.base_url}/v1/agent",
            headers=self._headers(),
            json=body,
            timeout=300,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        return MemberResult(
            model=model,
            text=self._extract_agent_text(data),
            citations=self._extract_agent_citations(data),
        )

    def complete(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.2,
        search_mode: str = "web",
        max_tokens: int | None = None,
    ) -> MemberResult:
        """Non-streaming completion -- used for council members. Routes to the
        Agent API for provider-prefixed models, else the Sonar Chat API."""
        if is_agent_model(model):
            return self._complete_agent(model, messages, temperature, search_mode, max_tokens)
        body = {
            "model": sonar_model_id(model),
            "messages": _api_messages(messages),
            "temperature": temperature,
            "search_mode": search_mode,
        }
        if max_tokens:
            body["max_tokens"] = max_tokens
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=body,
            timeout=180,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        return MemberResult(model=model, text=text, citations=self._extract_citations(data))

    def stream(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.2,
        search_mode: str = "web",
        max_tokens: int | None = None,
    ):
        """Yield (delta_text, citations) tuples. citations is non-empty only on
        the final relevant chunks. Agent-API models do not stream, so the full
        answer is yielded as a single chunk."""
        if is_agent_model(model):
            res = self._complete_agent(model, messages, temperature, search_mode, max_tokens)
            yield res.text, res.citations
            return
        body = {
            "model": sonar_model_id(model),
            "messages": _api_messages(messages),
            "temperature": temperature,
            "search_mode": search_mode,
            "stream": True,
        }
        if max_tokens:
            body["max_tokens"] = max_tokens
        with requests.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=body,
            stream=True,
            timeout=180,
        ) as resp:
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:500]}")
            # A single "data:" SSE payload can be split across several lines when
            # its JSON contains raw newlines (Perplexity embeds them in citation
            # snippets). So accumulate lines until the buffer is valid JSON, and
            # parse with strict=False to tolerate those embedded control chars.
            resp.encoding = "utf-8"
            buf = ""
            for raw in resp.iter_lines(decode_unicode=True):
                if raw is None:
                    continue
                if raw.startswith("data:"):
                    piece = raw[len("data:"):].lstrip()
                    if piece == "[DONE]":
                        break
                    buf = piece            # new event; drop any unparsed remnant
                elif buf:
                    buf += "\n" + raw      # continuation of a split JSON payload
                else:
                    continue
                try:
                    payload = json.loads(buf, strict=False)
                except json.JSONDecodeError:
                    continue               # incomplete; wait for more lines
                buf = ""
                delta = ""
                choices = payload.get("choices") or []
                if choices:
                    delta = choices[0].get("delta", {}).get("content", "") or ""
                citations = self._extract_citations(payload)
                if delta or citations:
                    yield delta, citations


def build_synthesis_input(question: str, members: list[MemberResult]) -> str:
    parts = [f'User question:\n"""{question}"""\n', "Council member answers:"]
    for i, m in enumerate(members, 1):
        if m.error:
            parts.append(f"\n### Model {i}: {m.model} (failed: {m.error})")
            continue
        parts.append(f"\n### Model {i}: {m.model}\n{m.text}")
    parts.append(
        "\nNow synthesize these into a single best answer. Highlight consensus, "
        "flag disagreements, and note any unique points."
    )
    return "\n".join(parts)


class CouncilController(QObject):
    """Runs a council turn: members in parallel, then a streamed synthesis.

    Signals are emitted from worker threads; connect with the default
    (auto/queued) connection so slots run on the GUI thread.
    """

    memberStarted = Signal(str)               # model
    memberFinished = Signal(str, str, list)   # model, text, citations
    memberFailed = Signal(str, str)           # model, error
    synthesisStarted = Signal()
    synthesisChunk = Signal(str)              # delta text
    synthesisFinished = Signal(str, list)     # full text, citations
    failed = Signal(str)                      # fatal error (e.g. no synthesis)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run_turn(
        self,
        client: PerplexityClient,
        question: str,
        history: list[dict],
        council_models: list[str],
        synth_model: str,
        temperature: float,
        search_mode: str,
    ):
        """Launch the turn on a background thread and return immediately."""
        self._cancel = threading.Event()
        threading.Thread(
            target=self._run,
            args=(client, question, history, council_models, synth_model,
                  temperature, search_mode),
            daemon=True,
        ).start()

    def _run(self, client, question, history, council_models, synth_model,
             temperature, search_mode):
        results: dict[str, MemberResult] = {}
        lock = threading.Lock()
        threads = []

        def work(model):
            self.memberStarted.emit(model)
            msgs = [{"role": "system", "content": MEMBER_SYSTEM_PROMPT}] + history
            try:
                res = client.complete(model, msgs, temperature, search_mode)
                if self._cancel.is_set():
                    return
                with lock:
                    results[model] = res
                self.memberFinished.emit(model, res.text, res.citations)
            except Exception as e:  # noqa: BLE001 - surface any failure to UI
                with lock:
                    results[model] = MemberResult(model=model, error=str(e))
                self.memberFailed.emit(model, str(e))

        for m in council_models:
            t = threading.Thread(target=work, args=(m,), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()

        if self._cancel.is_set():
            return

        ordered = [results[m] for m in council_models if m in results]
        succeeded = [r for r in ordered if not r.error]
        if not succeeded:
            self.failed.emit("All council members failed. Check your API key and network.")
            return

        # Synthesis step (streamed).
        self.synthesisStarted.emit()
        synth_user = build_synthesis_input(question, ordered)
        synth_msgs = (
            [{"role": "system", "content": SYNTH_SYSTEM_PROMPT}]
            + history[:-1]  # prior turns for context, minus the latest question
            + [{"role": "user", "content": synth_user}]
        )
        full = []
        cites: list[str] = []
        try:
            for delta, c in client.stream(synth_model, synth_msgs, temperature, search_mode):
                if self._cancel.is_set():
                    return
                if delta:
                    full.append(delta)
                    self.synthesisChunk.emit(delta)
                for u in c:
                    if u not in cites:
                        cites.append(u)
        except Exception as e:  # noqa: BLE001
            # Synthesis failed — fall back to the longest successful member answer
            # so the user still gets something useful rather than just an error.
            best = max(succeeded, key=lambda r: len(r.text))
            fallback = (
                f"*Synthesis unavailable ({e}). "
                f"Showing the most complete individual answer ({best.model}):*\n\n"
                + best.text
            )
            self.synthesisFinished.emit(fallback, best.citations)
            return

        self.synthesisFinished.emit("".join(full), cites)
