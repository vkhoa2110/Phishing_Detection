"""Versioned message policies sharing one transport, schema and validator.

Legacy modules stay frozen for reproducing registered experiments. V4 changes
the fraud decision rubric, not the input references or structural validator.
"""
import asyncio
import json
import time

import httpx

from app.services.llm.client import LLMFailure, LLMService, MESSAGE_V3_SYSTEM_PROMPT, MESSAGE_V3_RAG_SYSTEM_PROMPT, SOURCE_SCOPE_FIELDS, approved_ml_metadata, normalize_endpoint, _parse_verdict_with_validation


PROFILE = "message-v4"
FRAUD_RULES = """
CHÍNH SÁCH PHÂN BIỆT HÀNH VI — PHIÊN BẢN 4:
1. Nhiệm vụ là phát hiện dấu hiệu phishing/scam có trong lời yêu cầu. Spam/quảng cáo không mong muốn,
dịch vụ có thu phí, khuyến mãi, cờ bạc hoặc rủi ro tiêu dùng không tự đồng nghĩa với hành vi lừa đảo.
Phí được công bố hoặc mời đăng ký dịch vụ không tự chứng minh có lừa dối/chiếm đoạt.
Nhãn QC/TB cũng không miễn trừ: nếu thực sự xin bí mật hoặc đòi phí để giải ngân/rút tiền/nhận việc thì vẫn cảnh báo.
2. Không bịa rằng người gửi 'mạo danh', 'không mời mà đến', link cài mã độc, đầu số tính phí cao hay website giả
khi đầu vào không chứng minh điều đó. Nhắc tên một thương hiệu không đủ chứng minh mạo danh.
HTTP, TLD, link rút gọn, chưa xác minh được người gửi, số điện thoại đã che hoặc điểm URL cao không đủ làm bằng chứng lừa đảo trong nội dung.
3. HIGH/WARNING cần dấu hiệu cụ thể, chẳng hạn yêu cầu gửi bí mật cho bên liên hệ; cung cấp mã xác thực
để người khác đăng nhập; trả tiền trước để được rút tiền/giải ngân/nhận việc; giao quyền điều khiển thiết bị;
hoặc một yêu cầu nguy hiểm gắn với hành vi lừa dối/đe dọa/giấu giếm được nêu thực sự trong văn bản.
WARNING không phải cách nói 'mọi thứ đều có thể là lừa đảo'. Đừng nâng mức vì suy đoán một bước nguy hiểm chưa được yêu cầu.
4. Thông báo đơn hàng, thay đổi tài khoản, hủy đặt chỗ, liên hệ hỗ trợ hoặc quảng cáo thông thường,
nếu không có dấu hiệu trên, có thể LOW với context_kind routine/legitimate_workflow.
LOW chỉ là chưa thấy hành vi lừa đảo qua lời yêu cầu, không xác minh người gửi, URL hoặc dịch vụ.
UNKNOWN dùng khi thiếu ngữ cảnh quyết định để hiểu yêu cầu thực sự; không dùng để thay mọi thông điệp quảng cáo bằng thiếu thông tin.
5. Phân biệt người nhận tự nhập OTP vào quy trình do họ khởi tạo với việc gửi OTP cho người nhắn.
Phân biệt trích dẫn thủ đoạn/cảnh báo 'không gửi mã' với lời yêu cầu gửi mã thật. Nhãn tự xưng bài học không xóa yêu cầu lấy bí mật.
6. Đánh giá hành vi độc lập với cảnh báo URL. Mọi URL vẫn được kiểm tra và hiển thị riêng; LOW nội dung không xóa cảnh báo URL.
Không dùng nguồn RAG để suy ra người gửi cụ thể giả mạo. Nêu điểm giống và khác với thủ đoạn trong nguồn;
chỉ dẫn nguồn khi đầu vào thực sự chứa cơ chế liên quan, không vì retriever đã trả về bài cảnh báo.
7. Trích nguyên văn bằng copy từ text; giữ nguyên dấu, cách viết và token che dữ liệu. Không sửa tiếng Việt không dấu thành có dấu trong quote.
Giải thích ngắn, phân biệt điều nhìn thấy với điều chưa xác minh. Nếu chỉ cần lưu ý cước phí, nêu việc đọc điều kiện dịch vụ;
không biến lưu ý tiêu dùng thành kết luận scam hoặc hướng dẫn người dùng làm theo yêu cầu chưa xác minh.
"""
PROMPTS = {
    "message-v3": (MESSAGE_V3_SYSTEM_PROMPT, MESSAGE_V3_RAG_SYSTEM_PROMPT),
    "message-v4": (MESSAGE_V3_SYSTEM_PROMPT + FRAUD_RULES, MESSAGE_V3_RAG_SYSTEM_PROMPT + FRAUD_RULES),
}


def payload_for(*, text, urls, include_ml, sources, model, max_tokens, profile):
    if profile not in PROMPTS:
        raise ValueError("Unknown message policy.")
    data = {"input_type": "text", "text": text, "assessment_target": "message_actions_not_url_reputation"}
    ml = approved_ml_metadata(text, urls) if include_ml else []
    if include_ml:
        data["url_results"] = ml
    if sources:
        data["reference_documents"] = [{k: s[k] for k in
            ("document_id", "title", "text", "context_note", "publisher", "published_at", *SOURCE_SCOPE_FIELDS) if k in s} for s in sources]
    return {"model": model, "messages": [{"role": "system", "content": PROMPTS[profile][bool(sources)]},
        {"role": "user", "content": json.dumps(data, ensure_ascii=False)}], "temperature": .1, "top_p": 1,
        "top_k": 40, "max_tokens": max_tokens, "stream": False}, bool(ml)


async def call_message(client, *, endpoint, api_key, payload, text, sources, timeout):
    """Return durable success/error data, preserving usage even on invalid output."""
    started = time.perf_counter()
    result = {"status": "error", "code": "RESPONSE_INVALID", "usage": {}}
    try:
        async with asyncio.timeout(timeout):
            async with client.stream("POST", endpoint, headers={"Authorization": "Bearer " + api_key}, json=payload,
                                     follow_redirects=False) as response:
                result["http_status"] = response.status_code
                if response.status_code != 200:
                    result["code"] = f"HTTP_{response.status_code}"
                    return result
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 256_000:
                        result["code"] = "OUTPUT_TOO_LARGE"
                        return result
                    chunks.append(chunk)
        data = json.loads(b"".join(chunks))
        body = data if "choices" in data else data.get("data", {})
        usage = body.get("usage", data.get("usage", {}))
        result["usage"] = {k: v for k, v in usage.items() if k in {"prompt_tokens", "completion_tokens", "total_tokens"}
                           and type(v) is int and v >= 0} if isinstance(usage, dict) else {}
        choice = body["choices"][0]
        raw = choice["message"].get("content")
        result.update(raw_content=raw, finish_reason=choice.get("finish_reason"), provider_model=body.get("model"))
        if choice.get("finish_reason") == "length":
            result["code"] = "OUTPUT_TRUNCATED"
            return result
        if not isinstance(raw, str) or not raw.strip():
            return result
        try:
            verdict, warnings, validation = _parse_verdict_with_validation(raw, text, sources or None, "message-v3")
        except LLMFailure as exc:
            result["code"] = exc.code
            return result
        result.pop("code")
        result.update(status="ok", verdict=verdict.model_dump(), warnings=warnings, validation=validation)
    except (httpx.TimeoutException, TimeoutError):
        result["code"] = "TIMEOUT"
    except httpx.HTTPError:
        result["code"] = "CONNECTION_ERROR"
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        result["code"] = "RESPONSE_INVALID"
    finally:
        result["elapsed_ms"] = round(1000 * (time.perf_counter() - started), 2)
    return result


class MessageService(LLMService):
    """Drop-in message-schema compatibility; policy selected by the service.

    The legacy analysis service requests the v3 schema. Both policies use that
    exact schema/validator; returned prompt_profile records the actual policy.
    URL-only analysis continues to use the original URL service.
    """
    def __init__(self, settings, client, profile=PROFILE):
        super().__init__(settings, client)
        if profile not in PROMPTS:
            raise ValueError("Unknown message policy.")
        self.profile = profile

    async def analyze(self, *, text, mode, urls, include_ml, endpoint, model, api_key, rag_sources=None, prompt_profile="legacy"):
        if mode != "text":
            return await super().analyze(text=text, mode=mode, urls=urls, include_ml=include_ml,
                endpoint=endpoint, model=model, api_key=api_key, rag_sources=rag_sources, prompt_profile="legacy")
        if prompt_profile not in {"message-v3", "message-v4"}:
            raise LLMFailure("INPUT_INVALID", "Phạm vi phân tích thông điệp không hợp lệ.")
        endpoint = normalize_endpoint(endpoint or self.settings.endpoint, self.settings)
        key = api_key.strip() or self.settings.api_key
        if not key or any(c in key for c in "\r\n"):
            raise LLMFailure("API_KEY_MISSING" if not key else "API_KEY_INVALID", "Chưa có API key hợp lệ.")
        model = model.strip() or self.settings.llm_model
        sources = rag_sources or []
        payload, included_ml = payload_for(text=text, urls=urls, include_ml=include_ml, sources=sources,
            model=model, max_tokens=self.settings.max_tokens, profile=self.profile)
        async with self.slots:
            result = await call_message(self.client, endpoint=endpoint, api_key=key, payload=payload, text=text,
                                        sources=sources, timeout=self.settings.timeout_seconds)
        if result["status"] != "ok":
            failure = LLMFailure(result["code"], "Chưa phân tích được nội dung bằng AI; kết quả URL vẫn được giữ riêng.")
            raise failure
        # Raw provider content is kept in evaluation checkpoints, not exposed in app responses.
        result.pop("raw_content", None); result.pop("http_status", None); result.pop("finish_reason", None)
        result.update(model=model, endpoint=endpoint, input_used=text, included_ml=included_ml, rag=bool(sources),
            prompt_profile=self.profile, prompt_version="message-4.0" if self.profile == PROFILE else "message-3.0",
            assessment_scope="message")
        return result
