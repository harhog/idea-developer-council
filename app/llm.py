"""LLM bridge — OpenAI-compatible chat completions with offline fallback.

Configuration via environment (or .env):
  LLM_BASE_URL  default https://api.openai.com/v1
  LLM_API_KEY   required for online mode
  LLM_MODEL     default gpt-4o-mini

If no API key is set, `chat()` falls back to offline mode: the council
still runs and produces a structured roadmap, marked as heuristic-only.
"""
import json
import os
from pathlib import Path
import urllib.request
import urllib.error

DEFAULT_BASE = 'https://api.openai.com/v1'
DEFAULT_MODEL = 'gpt-4o-mini'
TIMEOUT = 90


def _load_dotenv():
    env = Path(__file__).resolve().parents[1] / '.env'
    if not env.exists():
        return
    for line in env.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def online() -> bool:
    return bool(os.environ.get('LLM_API_KEY') or os.environ.get('OPENAI_API_KEY'))


def _key() -> str:
    return os.environ.get('LLM_API_KEY') or os.environ.get('OPENAI_API_KEY') or ''


def _base() -> str:
    return (os.environ.get('LLM_BASE_URL') or DEFAULT_BASE).rstrip('/')


def _model() -> str:
    return os.environ.get('LLM_MODEL') or DEFAULT_MODEL


def chat(messages: list, json_mode: bool = False, temperature: float = 0.2) -> str:
    """One chat completion. Raises RuntimeError with a clear message on failure."""
    if not online():
        raise RuntimeError('OFFLINE: no LLM_API_KEY configured')
    payload = {
        'model': _model(),
        'messages': messages,
        'temperature': temperature,
    }
    if json_mode:
        payload['response_format'] = {'type': 'json_object'}
    req = urllib.request.Request(
        _base() + '/chat/completions',
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + _key(),
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')[:500]
        raise RuntimeError(f'LLM HTTP {exc.code}: {detail}') from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f'LLM unreachable: {exc.reason}') from exc
    try:
        return body['choices'][0]['message']['content']
    except (KeyError, IndexError) as exc:
        raise RuntimeError('LLM response missing choices: ' + json.dumps(body)[:500]) from exc
