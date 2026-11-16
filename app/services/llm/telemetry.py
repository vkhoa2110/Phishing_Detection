"""Bounded response observations: counts and identifiers, never reasoning text."""
import asyncio
from contextvars import ContextVar
import hashlib
import json
from pathlib import Path
import re
import time

import httpx

MAX_BYTES = 512_000
LAST_CLASSIFIER_CALL = ContextVar("focused_classifier_observation", default=None)


def fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _identifier(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", value) else None


def _counts(value):
    if not isinstance(value, dict):
        return {}
    allowed = {"prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens",
               "cached_tokens", "accepted_prediction_tokens", "rejected_prediction_tokens"}
    return {k: v for k, v in value.items() if k in allowed and type(v) is int and v >= 0}


def observe(data, payload, *, http_status, headers=None):
    data = data if isinstance(data, dict) else {}
    body = data if "choices" in data else data.get("data", {})
    body = body if isinstance(body, dict) else {}
    choices = body.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    message = choice.get("message")
    message = message if isinstance(message, dict) else {}
    content, reasoning = message.get("content"), message.get("reasoning_content")
    usage = body.get("usage", data.get("usage", {}))
    usage = usage if isinstance(usage, dict) else {}
    headers = headers or {}
    finish = choice.get("finish_reason")
    thinking = payload.get("thinking")
    mode = thinking.get("type", "default") if isinstance(thinking, dict) else "default"
    if mode not in {"default", "enabled", "disabled"}: mode = "unknown"
    return {"payload_sha256": fingerprint(payload), "http_status": http_status,
        "requested_max_tokens": payload.get("max_tokens"), "thinking_requested": mode,
        "provider_model": _identifier(body.get("model")),
        "request_id": _identifier(headers.get("x-request-id") or headers.get("x-amzn-requestid") or body.get("id")),
        "finish_reason": finish if finish in {"stop", "length", "tool_calls", "content_filter"} else None,
        "content_characters": len(content) if isinstance(content, str) else 0,
        "content_is_string": isinstance(content, str),
        "reasoning_field_present": "reasoning_content" in message,
        "reasoning_characters": len(reasoning) if isinstance(reasoning, str) else 0,
        "usage": _counts(usage),
        "completion_token_details": _counts(usage.get("completion_tokens_details")),
        "prompt_token_details": _counts(usage.get("prompt_tokens_details")),
        "reasoning_text_stored": False}


async def _bounded_read(response):
    chunks, size = [], 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > MAX_BYTES:
            raise ValueError("OUTPUT_TOO_LARGE")
        chunks.append(chunk)
    return b"".join(chunks)


async def collect_once(client, *, payload, endpoint, api_key, timeout):
    started = time.perf_counter()
    row = {"content": None, "http_status": None, "finish_reason": None,
           "provider_model": None, "usage": {}}
    observation = observe({}, payload, http_status=None)
    try:
        async with asyncio.timeout(timeout):
            async with client.stream("POST", endpoint, json=payload,
                    headers={"Authorization": "Bearer " + api_key}, follow_redirects=False) as response:
                row["http_status"] = response.status_code
                packet = await _bounded_read(response)
                try:
                    data = json.loads(packet)
                except (ValueError, UnicodeError):
                    data = {}
                observation = observe(data, payload, http_status=response.status_code, headers=response.headers)
        row.update({k: observation[k] for k in ("finish_reason", "provider_model", "usage")})
        if row["http_status"] == 200:
            body = data if "choices" in data else data.get("data", {})
            row["content"] = body["choices"][0]["message"].get("content")
    except (httpx.TimeoutException, TimeoutError):
        row["transport_error"] = "TIMEOUT"
    except httpx.HTTPError:
        row["transport_error"] = "CONNECTION_ERROR"
    except (ValueError, UnicodeError, TypeError, KeyError, IndexError, AttributeError) as exc:
        row["transport_error"] = "OUTPUT_TOO_LARGE" if str(exc) == "OUTPUT_TOO_LARGE" else "RESPONSE_INVALID"
    row["elapsed_ms"] = round(1000 * (time.perf_counter() - started), 2)
    row["telemetry"] = {**observation, "elapsed_ms": row["elapsed_ms"],
                        "transport_error": row.get("transport_error")}
    return row


class ObservedTransport(httpx.AsyncBaseTransport):
    """Instrument existing frozen runners without changing their source/parser."""
    def __init__(self, path, inner=None):
        self.path = Path(path)
        self.inner = inner or httpx.AsyncHTTPTransport(trust_env=False)

    async def handle_async_request(self, request):
        started = time.perf_counter()
        payload = json.loads(await request.aread())
        observation = observe({}, payload, http_status=None)
        try:
            response = await self.inner.handle_async_request(request)
            try:
                packet = await _bounded_read(response)
                try:
                    data = json.loads(packet)
                except (ValueError, UnicodeError):
                    data = {}
                observation = observe(data, payload, http_status=response.status_code, headers=response.headers)
                # A decoded packet must not retain compression headers.
                headers = [(k, v) for k, v in response.headers.multi_items()
                           if k.lower() not in {"content-encoding", "content-length", "transfer-encoding"}]
                result = httpx.Response(response.status_code, headers=headers, content=packet, request=request)
            finally:
                await response.aclose()
            return result
        except BaseException as exc:
            observation["transport_error"] = ("TIMEOUT" if isinstance(exc, (httpx.TimeoutException, TimeoutError))
                else "OUTPUT_TOO_LARGE" if isinstance(exc, ValueError) and str(exc) == "OUTPUT_TOO_LARGE"
                else "INTERRUPTED_REQUEST" if isinstance(exc, asyncio.CancelledError) else "CONNECTION_ERROR")
            if isinstance(exc, ValueError):
                raise httpx.RemoteProtocolError("Provider response exceeds the diagnostic bound.") from exc
            raise
        finally:
            observation["elapsed_ms"] = round(1000 * (time.perf_counter() - started), 2)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(observation, ensure_ascii=False) + "\n")
                stream.flush()

    async def aclose(self):
        await self.inner.aclose()
