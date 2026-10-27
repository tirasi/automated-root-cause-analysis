import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from copilot.agent.llm import LLMError, MockLLM, OllamaLLM, get_llm


def test_mock_echoes_only_the_facts():
    assert MockLLM().complete("Write a summary.\nFACTS:\n- one [ev:001]\n- two [ev:002]") == "- one [ev:001]\n- two [ev:002]"


def test_get_llm_defaults_to_mock_and_switches_on_request(monkeypatch):
    monkeypatch.delenv("RCA_LLM", raising=False)
    assert get_llm().name == "mock"
    monkeypatch.setenv("RCA_LLM", "ollama")
    assert get_llm().name == "ollama"


@pytest.fixture
def fake_ollama():
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.update(path=self.path, body=body)
            out = json.dumps({"response": "  The cause is X [ev:001].  "}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", seen
    server.shutdown()


def test_ollama_client_sends_the_prompt_and_returns_the_text(fake_ollama):
    host, seen = fake_ollama
    text = OllamaLLM(model="tiny", host=host).complete("hello")
    assert text == "The cause is X [ev:001]."
    assert seen["path"] == "/api/generate"
    assert seen["body"]["model"] == "tiny" and seen["body"]["prompt"] == "hello" and seen["body"]["stream"] is False


def test_ollama_down_raises_llm_error():
    with pytest.raises(LLMError):
        OllamaLLM(host="http://127.0.0.1:9", timeout=2).complete("hello")
