"""Small local Ollama adapter. No downloads, external endpoints or automatic retries."""
import json
import math
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class ModelError(RuntimeError):
    pass


class RequestLimit(ModelError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _post(url, payload, timeout):
    request = Request(url, data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    # Ignore proxy environment variables and refuse redirects away from the local service.
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise ModelError("Model response exceeds 2 MB")
    return json.loads(body)


class OllamaClient:
    def __init__(self, model, endpoint="http://127.0.0.1:11434", timeout=60,
                 max_requests=5, max_output_tokens=512, seed=317, post=None, *, cpu=False):
        parts = urlsplit(endpoint)
        if (parts.scheme != "http" or parts.hostname not in ("localhost", "127.0.0.1", "::1")
                or parts.username or parts.password or parts.path not in ("", "/")
                or parts.query or parts.fragment):
            raise ValueError("Use a local HTTP Ollama endpoint without a path or credentials")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("Choose an already installed model explicitly")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        if any(type(n) is not int or n <= 0 for n in (max_requests, max_output_tokens)):
            raise ValueError("Request and output limits must be positive integers")
        self.model, self.endpoint, self.timeout = model, endpoint.rstrip("/"), timeout
        self.max_requests, self.max_output_tokens, self.seed = max_requests, max_output_tokens, seed
        self.cpu = cpu
        self.calls, self.post = 0, post or _post

    def chat(self, messages, *, response_format="json"):
        if self.calls >= self.max_requests:
            raise RequestLimit("Model request limit reached")
        self.calls += 1  # Failed attempts count too; a failure cannot cause unlimited retries.
        payload = {"model": self.model, "messages": messages, "stream": False, "format": response_format,
                   "options": {"temperature": 0, "seed": self.seed, "num_predict": self.max_output_tokens}}
        if self.cpu:
            payload["options"]["num_gpu"] = 0
        try:
            response = self.post(self.endpoint + "/api/chat", payload, self.timeout)
            if not isinstance(response, dict) or response.get("done") is not True:
                raise ModelError("Incomplete model response")
            content = response.get("message", {}).get("content")
            if not isinstance(content, str):
                raise ModelError("Model response has no text content")
            return {"content": content, "model": response.get("model"),
                    "done_reason": response.get("done_reason"),
                    "prompt_tokens": response.get("prompt_eval_count"),
                    "output_tokens": response.get("eval_count")}
        except ModelError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, TypeError, AttributeError) as error:
            # Do not store server error bodies; they may echo the source text.
            raise ModelError(type(error).__name__) from error
