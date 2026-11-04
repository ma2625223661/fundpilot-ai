"""Responses-compatible provider adapter; no retries or provider fallbacks."""
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from research_service import API_URL, ProviderError as BaseProviderError
from research_transport import fetch_bytes

RESPONSES_MODEL = 'gpt-6.1-sol'
RESPONSES_TIMEOUTS = {'medium':300, 'xhigh':600}


class ProviderError(BaseProviderError):
    provider = 'responses'


def is_responses(config):
    return config.get('model') == RESPONSES_MODEL


def validate_base_url(value):
    if not isinstance(value, str) or len(value) > 512:
        raise ValueError('服务商接口地址无效')
    value = value.strip().rstrip('/')
    if not value:
        return ''
    parsed = urlsplit(value)
    try:
        valid = parsed.port is None or 1 <= parsed.port <= 65535
    except ValueError:
        valid = False
    if (not valid or parsed.scheme not in ('http', 'https') or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or any(c.isspace() or not c.isprintable() for c in value)):
        raise ValueError('服务商接口地址无效')
    return value


def cache_identity(config):
    if not is_responses(config):
        return config.get('model') or 'deepseek-flash'
    return json.dumps({'model':RESPONSES_MODEL, 'provider':'responses',
        'base_url':validate_base_url(config.get('responses_base_url', '')), 
        # Legacy callers without the new field retain the historical medium wire format.
        'reasoning_effort':config.get('reasoning_effort') or 'medium'}, sort_keys=True)


def build_payload(config, messages, max_tokens=6500):
    if not is_responses(config):
        return {'model':config.get('model') or 'deepseek-flash', 'stream':False,
            'max_tokens':max_tokens, 'thinking':{'type':'disabled'},
            'response_format':{'type':'json_object'}, 'messages':messages}
    return {'model':RESPONSES_MODEL, 'stream':True, 'store':False,
        'max_output_tokens':max_tokens, 'reasoning':{'effort':config.get('reasoning_effort') or 'medium'},
        'text':{'format':{'type':'json_object'}}, 'input':messages}


def _error(status):
    return ProviderError({401:'API Key 无效，请重新配置', 402:'AI 服务商余额不足',
        429:'请求频率过高，请稍后重试'}.get(status, f'AI 服务商错误（{status}）'), status)


def probe_responses_key(key, base_url, model=RESPONSES_MODEL):
    base = validate_base_url(base_url)
    if not base:
        raise ProviderError('请先配置服务商接口地址')
    request = urllib.request.Request(base + '/models', headers={
        'Authorization':'Bearer ' + key, 'Accept':'application/json'}, method='GET')
    try:
        result = json.loads(fetch_bytes(request, timeout=15, max_bytes=200000))
        rows = result.get('data') if isinstance(result, dict) else None
        if not isinstance(rows, list) or len(rows) > 200:
            raise ValueError()
        models = [row['id'] for row in rows if isinstance(row, dict) and isinstance(row.get('id'), str)]
        if len(models) != len(rows):
            raise ValueError()
        return {'models':models, 'model_available':model in models}
    except urllib.error.HTTPError as error:
        error.close()
        raise _error(error.code) from None
    except (TimeoutError, urllib.error.URLError, OSError):
        raise ProviderError('AI 服务商连接失败或超时') from None
    except (ValueError, KeyError, UnicodeError):
        raise ProviderError('AI 服务商返回的数据格式无效') from None


def normalize_response(response):
    if not isinstance(response, dict):
        raise ProviderError('AI 服务商返回的数据格式无效')
    parts, refused = [], False
    for item in response.get('output', []):
        if not isinstance(item, dict) or item.get('type') != 'message':
            continue
        for part in item.get('content', []):
            if not isinstance(part, dict):
                continue
            refused = refused or part.get('type') == 'refusal'
            if part.get('type') == 'output_text' and isinstance(part.get('text'), str):
                parts.append(part['text'])
    raw = response.get('usage') or {}
    if not isinstance(raw, dict):
        raw = {}
    usage = {'prompt_tokens':raw.get('input_tokens'), 'completion_tokens':raw.get('output_tokens'),
             'total_tokens':raw.get('total_tokens')}
    details = raw.get('input_tokens_details')
    if isinstance(details, dict):
        usage['prompt_tokens_details'] = {'cached_tokens':details.get('cached_tokens')}
    # output_tokens includes reasoning. Never add details.reasoning_tokens again.
    finish = 'content_filter' if refused else 'stop' if response.get('status') == 'completed' and parts else 'length'
    return {'choices':[{'finish_reason':finish, 'message':{'content':''.join(parts)}}], 'usage':usage}


def decode_wire(raw):
    text = raw.decode('utf-8-sig')
    try:
        return normalize_response(json.loads(text))
    except json.JSONDecodeError:
        pass
    # The final event is authoritative; partial text deltas are never success.
    final = None
    for block in text.replace('\r\n', '\n').replace('\r','\n').split('\n\n'):
        data = '\n'.join(line[5:].lstrip() for line in block.splitlines() if line.startswith('data:'))
        if not data or data == '[DONE]':
            continue
        try:
            event = json.loads(data)
        except ValueError:
            raise ProviderError('AI 服务商返回的数据格式无效') from None
        if not isinstance(event,dict):
            raise ProviderError('AI 服务商返回的数据格式无效')
        if event.get('type') == 'error':
            raise ProviderError('AI 响应未完成，保留预算预留，本轮不自动重试')
        if event.get('type') in ('response.completed', 'response.incomplete', 'response.failed'):
            final = event.get('response')
    if not isinstance(final, dict):
        raise ProviderError('AI 响应未完成，保留预算预留，本轮不自动重试')
    return normalize_response(final)


def send_provider(config, payload, timeout, legacy_sender):
    if not is_responses(config):
        return legacy_sender(API_URL, config['key'], payload, timeout)
    base = validate_base_url(config.get('responses_base_url', ''))
    if not base:
        raise ProviderError('请先配置服务商接口地址')
    request = urllib.request.Request(base + '/responses', data=json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode(),
        headers={'Content-Type':'application/json', 'Accept':'text/event-stream, application/json',
                 'Authorization':'Bearer ' + config['key']}, method='POST')
    try:
        # Reasoning streams can legitimately run for several minutes. This
        # independent wall-clock bound does not widen ordinary data collection.
        deadline = RESPONSES_TIMEOUTS.get(payload.get('reasoning',{}).get('effort'),300)
        return decode_wire(fetch_bytes(request, timeout=deadline, max_bytes=2000000,
                                       responses_stream=True))
    except urllib.error.HTTPError as error:
        error.close()
        raise _error(error.code) from None
    except (TimeoutError, urllib.error.URLError, OSError):
        raise ProviderError('AI 服务商连接失败或超时；本次请求可能已被接收') from None
    except (ValueError, TypeError, UnicodeError):
        raise ProviderError('AI 服务商返回的数据格式无效') from None
