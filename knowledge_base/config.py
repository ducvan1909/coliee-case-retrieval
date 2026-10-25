"""No dependencies; dotenv values are never printed."""
import json
import math
import os
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent


def settings(env_file=None):
    values = {}
    path = Path(env_file) if env_file else ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            key, sep, value = line.partition('=')
            if not sep:
                raise ValueError('Invalid dotenv line')
            values[key.strip()] = value.strip().strip('\"\'')
    values.update(os.environ)
    return values


def number(env, key, default, integer=False):
    try:
        value = float(env.get(key, str(default)))
    except (TypeError, ValueError):
        raise ValueError(f'Fill {key} with a positive number') from None
    if not math.isfinite(value) or value <= 0 or (integer and value != int(value)):
        raise ValueError(f'{key} must be a positive finite number')
    return int(value) if integer else value


def budget_limit(env):
    raw = str(env.get('KB_BUDGET_USD', '10')).strip().lower()
    if raw in {'unlimited', 'none', 'off'}:
        return None
    return number(env, 'KB_BUDGET_USD', 10)


def api_config(env):
    url = env.get('KB_ENDPOINT_URL', '')
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.netloc or parts.username or parts.password:
        raise ValueError('KB_ENDPOINT_URL must be a complete HTTPS endpoint URL')
    reader = env.get('KB_READER_MODEL', '').strip()
    if not reader:
        raise ValueError('Fill KB_READER_MODEL')
    repair = env.get('KB_REPAIR_MODEL', '').strip() or reader
    verifier = env.get('KB_VERIFIER_MODEL', '').strip()
    headers = json.loads(env.get('KB_EXTRA_HEADERS_JSON', '{}'))
    if not isinstance(headers, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in headers.items()):
        raise ValueError('KB_EXTRA_HEADERS_JSON must contain string headers')
    try:
        temperature = float(env.get('KB_TEMPERATURE', '0'))
        top_p = float(env.get('KB_TOP_P', '0.9'))
    except ValueError:
        raise ValueError('KB_TEMPERATURE and KB_TOP_P must be numbers') from None
    reasoning_effort = env.get('KB_REASONING_EFFORT', 'none')
    if not math.isfinite(temperature) or temperature < 0 or not 0 < top_p <= 1:
        raise ValueError('KB_TEMPERATURE must be non-negative and KB_TOP_P in (0, 1]')
    if reasoning_effort not in ('none', 'low', 'medium', 'high'):
        raise ValueError('Unsupported KB_REASONING_EFFORT')
    return dict(url=url, reader=reader, repair=repair, verifier=verifier, headers=headers,
                key=env.get('KB_API_KEY', ''),
                reserve=number(env, 'KB_REQUEST_RESERVE_USD', ''),
                budget=budget_limit(env),
                timeout=number(env, 'KB_TIMEOUT_SECONDS', 120),
                startup_wait=number(env, 'KB_STARTUP_WAIT_SECONDS', 900),
                tokens=number(env, 'KB_MAX_OUTPUT_TOKENS', 4096, True),
                temperature=temperature, top_p=top_p,
                reasoning_effort=reasoning_effort)
