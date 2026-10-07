"""LLM bridge — OpenAI-compatible chat completions with offline fallback.

Configuration via environment (or .env):
  LLM_API_KEY  / CLINE_API_KEY    required for online mode
  LLM_BASE_URL / CLINE_BASE_URL   default: Cline API (vid CLINE-nyckel) annars OpenAI
  LLM_MODEL    / CLINE_MODEL      default openrouter/free (dokumenterad gratismodell)

Om ingen API-nyckel satt är `online()` False och rådet kör offline-heuristik.
Stöd för Cline API (som idea-council): OpenAI-kompatibelt, svar kan vara
wrapperade i {"data": {...}} och gratismodeller har id-suffixet ":free".
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE = 'https://api.cline.bot/api/v1'
CLINE_BASE = 'https://api.cline.bot/api/v1'
OPENAI_BASE = 'https://api.openai.com/v1'
DEFAULT_MODEL = 'openrouter/free'
TIMEOUT = 75  # gratisa modeller kan vara långsamma; två försök per medlem → max ~2,5 min
MODELS_TTL_SECONDS = 600

# Används om API:et inte går att nå (offline CI, nätverksfel).
CURATED_MODELS = [
    {'id': 'openrouter/free', 'free': True},
    {'id': 'google/gemma-4-31b-it:free', 'free': True},
    {'id': 'google/gemma-4-26b-a4b-it:free', 'free': True},
    {'id': 'nvidia/nemotron-3-super-120b-a12b:free', 'free': True},
    {'id': 'deepseek/deepseek-chat', 'free': False},
]


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
    return bool(_key())


def _key() -> str:
    return (os.environ.get('LLM_API_KEY') or os.environ.get('OPENAI_API_KEY')
            or os.environ.get('CLINE_API_KEY') or '')


def _base() -> str:
    if os.environ.get('LLM_BASE_URL'):
        return os.environ['LLM_BASE_URL'].rstrip('/')
    if os.environ.get('CLINE_BASE_URL'):
        return os.environ['CLINE_BASE_URL'].rstrip('/')
    if os.environ.get('CLINE_API_KEY'):
        return CLINE_BASE
    if os.environ.get('LLM_API_KEY') or os.environ.get('OPENAI_API_KEY'):
        return OPENAI_BASE
    return DEFAULT_BASE


def _model() -> str:
    return (os.environ.get('LLM_MODEL') or os.environ.get('CLINE_MODEL')
            or DEFAULT_MODEL)


def _post(path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode('utf-8')
    last_exc: RuntimeError | None = None
    # Upp till 3 försök vid rate-limit/5xx/timeout — gratisa modeller är ostadiga
    # ("empty response content", läs-timeouts) och behöver fler chanser.
    for attempt in range(3):
        req = urllib.request.Request(
            _base() + path,
            data=data,
            headers={'Content-Type': 'application/json',
                     'Authorization': 'Bearer ' + _key()},
            method='POST',
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', 'replace')[:500]
            last_exc = RuntimeError(f'LLM HTTP {exc.code}: {detail}')
            if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise last_exc from exc
        except (TimeoutError, ConnectionError) as exc:
            last_exc = RuntimeError(f'LLM timeout/anslutning: {exc}')
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise last_exc from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, 'reason', exc)
            last_exc = RuntimeError(f'LLM unreachable: {reason}')
            if isinstance(reason, (TimeoutError, ConnectionError, OSError)) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise last_exc from exc
        except (OSError, ValueError) as exc:
            # timeout/socket-fel/ogiltig JSON — bli aldrig ett opåhållat undantag
            raise RuntimeError(f'LLM failed: {type(exc).__name__}: {exc}') from exc
    raise last_exc or RuntimeError('LLM failed')


def _content(body: dict) -> str:
    # Cline API wrappar ibland OpenAI-svaret i {"data": {...}}.
    if isinstance(body, dict) and 'choices' not in body and isinstance(body.get('data'), dict):
        body = body['data']
    try:
        content = body['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError('LLM response missing choices: '
                           + json.dumps(body)[:500]) from exc
    if isinstance(content, list):  # provider returnerar block
        content = ''.join(b.get('text', '') if isinstance(b, dict) else str(b)
                          for b in content)
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError('LLM returnerade tomt meddelande.')
    return content.strip()


def chat(messages: list, json_mode: bool = False, temperature: float = 0.3,
         model: str | None = None) -> str:
    """One chat completion. Raises RuntimeError with a clear message on failure."""
    if not online():
        raise RuntimeError('OFFLINE: no API key configured')
    payload = {'model': model or _model(), 'messages': messages,
               'temperature': temperature, 'stream': False,
               'max_tokens': 4000}  # begränsa så svar inte blir orimligt långa
    if json_mode:
        payload['response_format'] = {'type': 'json_object'}
    try:
        body = _post('/chat/completions', payload)
    except RuntimeError as exc:
        # Vissa modeller stödjer inte response_format — prova utan.
        if json_mode and 'response_format' in payload and '400' in str(exc):
            payload.pop('response_format')
            body = _post('/chat/completions', payload)
        else:
            raise
    content = _content(body)
    if json_mode:
        # Gratisrouternar kan svara med skräp ("User Safety: safe") eller
        # tänkarprosa istället för JSON — max 2 nyförsök.
        attempts = 0
        while attempts < 2 and not _looks_like_json(content):
            attempts += 1
            content = _content(_post('/chat/completions', payload))
    return content


def _looks_like_json(content: str) -> bool:
    s = content.strip()
    return s.startswith('{') or s.startswith('```') or '"assessment"' in s


_FENCE_RE = re.compile(r'```(?:json)?\s*(.*?)\s*```', re.DOTALL)


def _close_unterminated(candidate: str) -> str | None:
    """Best-effort: stäng öppna strängar/klamrar i en trunkerad JSON-sträng."""
    in_str, esc = False, False
    stack = []
    for ch in candidate:
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in '{[':
            stack.append('}' if ch == '{' else ']')
        elif ch in '}]':
            if stack and stack[-1] == ch:
                stack.pop()
            else:
                return None  # mismatchat — lita inte på reparationen
    out = candidate
    if esc:  # avslutades mitt i ett escape-tecken
        out = out[:-1]
    if in_str:
        out += '"'
    out += ''.join(reversed(stack))
    return out or None


def extract_json(text: str) -> dict:
    """Parse a JSON object from a model reply — fences, prose and truncation."""
    stripped = text.strip()
    fence = _FENCE_RE.search(stripped)
    if fence:
        stripped = fence.group(1).strip()
    starts = [m.start() for m in re.finditer(r'\{', stripped)][:20]
    if not starts:
        raise RuntimeError(f'Modellen returnerade inte JSON: {text[:200]}')
    best: dict | None = None
    for start in starts:
        end = stripped.rfind('}')
        cands = [stripped[start:end + 1]] if end > start else []
        cands.append(stripped[start:])  # trunkerad variant utan avslutande parentes
        for cand in cands:
            for attempt in (cand, _close_unterminated(cand)):
                if not attempt:
                    continue
                try:
                    parsed = json.loads(attempt)
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(parsed, dict):
                    if 'assessment' in parsed or 'recommendation' in parsed:
                        return parsed  # rådets nyckelfält = rätt objekt
                    best = best or parsed
    if best is not None:
        return best
    raise RuntimeError(f'Kunde inte tolka JSON från modellen: {text[:200]}')


# --- Modellista -------------------------------------------------------------
_MODELS_CACHE: dict = {'at': 0.0, 'data': None}


def parse_models(payload) -> list:
    """Extract [{id, free}] from a Cline/OpenAI /models payload, free first."""
    items = payload.get('data', []) if isinstance(payload, dict) else payload
    models = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not item.get('id'):
            continue
        mid = str(item['id'])
        models.append({'id': mid,
                       'free': mid.endswith(':free') or mid == 'openrouter/free'})
    models.sort(key=lambda m: (not m['free'], m['id'].lower()))
    return models


def list_models(force_refresh: bool = False) -> dict:
    """{models: [{id, free}], default, source: 'live'|'curated'} — cached 10 min."""
    now = time.monotonic()
    if (not force_refresh and _MODELS_CACHE['data'] is not None
            and now - _MODELS_CACHE['at'] < MODELS_TTL_SECONDS):
        return _MODELS_CACHE['data']

    result = {'models': list(CURATED_MODELS), 'default': _model(), 'source': 'curated'}
    if online():
        try:
            req = urllib.request.Request(
                _base() + '/models',
                headers={'Authorization': 'Bearer ' + _key()},
                method='GET')
            with urllib.request.urlopen(req, timeout=30) as resp:
                live = parse_models(json.loads(resp.read().decode('utf-8')))
            if live:
                result = {'models': live, 'default': _model(), 'source': 'live'}
        except (urllib.error.URLError, OSError, ValueError, RuntimeError):
            pass  # curated fallback
    _MODELS_CACHE['at'] = now
    _MODELS_CACHE['data'] = result
    return result

