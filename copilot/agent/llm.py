"""The language model. It only ever writes WORDS (critique wording, report narrative).
Facts, scores and decisions come from the KB, the tools and plain Python.

MockLLM is deterministic, so everything runs and tests without a model. OllamaLLM talks to a local
Ollama server (set RCA_LLM=ollama and RCA_MODEL=<model name>)."""
import json
import os
import urllib.request


class LLMError(RuntimeError):
    pass


class MockLLM:
    """Echoes the FACTS section of the prompt. Deterministic and it can only repeat real facts."""
    name = "mock"

    def complete(self, prompt: str) -> str:
        _, _, facts = prompt.partition("FACTS:\n")
        return facts.strip() or prompt.strip()[:200]


class OllamaLLM:
    name = "ollama"

    def __init__(self, model=None, host=None, timeout=90):
        self.model = model or os.environ.get("RCA_MODEL", "llama3.1")
        self.host = (host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
        self.timeout = timeout

    def complete(self, prompt: str) -> str:
        body = json.dumps({"model": self.model, "prompt": prompt, "stream": False,
                           "options": {"temperature": 0}}).encode()
        req = urllib.request.Request(f"{self.host}/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())["response"].strip()
        except Exception as exc:  # network down, model missing, bad JSON ...
            raise LLMError(f"ollama call failed: {exc}") from exc


def get_llm(kind=None):
    kind = (kind or os.environ.get("RCA_LLM", "mock")).lower()
    if kind == "ollama":
        return OllamaLLM()
    return MockLLM()
