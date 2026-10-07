"""The Anthropic API provider: same prompt, schema and scoring as Bedrock, different transport."""

import base64
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from kyc.extraction import (
    SYSTEM_PROMPT,
    TOOL_NAME,
    AnthropicExtractor,
    BedrockExtractor,
    ExtractionError,
    build_extractor,
    tool_schema,
)
from kyc.schemas import FIELD_SPECS, DocumentType
from tests.conftest import PNG, make_settings
from tests.test_extraction import _good_input


class FakeAnthropic:
    """Stands in for anthropic.Anthropic: records the request, returns a canned reply."""

    def __init__(self, tool_input=None, error=None, content=None):
        self.request = None
        self._tool_input = tool_input
        self._error = error
        self._content = content
        self.messages = self  # the SDK exposes client.messages.create

    def create(self, **request):
        self.request = request
        if self._error:
            raise self._error
        content = self._content or [
            SimpleNamespace(type="tool_use", name=TOOL_NAME, input=self._tool_input)
        ]
        return SimpleNamespace(
            content=content, usage=SimpleNamespace(input_tokens=210, output_tokens=33)
        )


def _extract(client, content_type="image/png", data=PNG):
    extractor = AnthropicExtractor(client, "claude-haiku-4-5", 0.85)
    return extractor.extract(data, content_type, DocumentType.ID_DOCUMENT)


def test_request_matches_the_bedrock_design():
    client = FakeAnthropic(_good_input())
    result = _extract(client)

    req = client.request
    assert req["model"] == "claude-haiku-4-5"
    assert req["system"] == SYSTEM_PROMPT
    assert req["tool_choice"] == {"type": "tool", "name": TOOL_NAME}
    assert req["tools"][0]["input_schema"] == tool_schema(DocumentType.ID_DOCUMENT)
    image = req["messages"][0]["content"][0]
    assert image["type"] == "image"
    assert image["source"]["media_type"] == "image/png"
    assert base64.b64decode(image["source"]["data"]) == PNG
    assert result.model_id == "claude-haiku-4-5"
    assert result.input_tokens == 210 and result.output_tokens == 33
    assert all(not f.needs_review for f in result.fields)


def test_pdf_is_sent_as_a_document_block():
    client = FakeAnthropic(_good_input())
    _extract(client, "application/pdf", b"%PDF-1.4 fake")
    block = client.request["messages"][0]["content"][0]
    assert block["type"] == "document"
    assert block["source"]["media_type"] == "application/pdf"


def test_unsupported_type_is_rejected_before_any_call():
    client = FakeAnthropic(_good_input())
    with pytest.raises(ExtractionError, match="unsupported content type"):
        _extract(client, "text/plain", b"hello")
    assert client.request is None


def test_scoring_is_shared_with_bedrock():
    data = _good_input()
    data["fields"]["full_name"]["confidence"] = 0.3
    data["fields"]["nationality"] = {"value": None, "confidence": 0}
    result = _extract(FakeAnthropic(data))
    flagged = {f.name: f.reason for f in result.fields if f.needs_review}
    assert flagged == {"full_name": "low_confidence", "nationality": "missing"}
    assert {f.name for f in result.fields} == {
        s.name for s in FIELD_SPECS[DocumentType.ID_DOCUMENT]
    }


def test_api_errors_keep_only_the_error_class():
    secret_body = "Zorblax Quentin Fakeperson ZZ1234567"
    error = anthropic.APIConnectionError(
        message=secret_body, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    with pytest.raises(ExtractionError) as caught:
        _extract(FakeAnthropic(error=error))
    assert str(caught.value) == "anthropic call failed: APIConnectionError"
    assert secret_body not in str(caught.value)


def test_missing_tool_call_is_an_error():
    reply = [SimpleNamespace(type="text", text="I cannot do that")]
    with pytest.raises(ExtractionError, match="expected tool call"):
        _extract(FakeAnthropic(content=reply))


def test_build_extractor_picks_the_provider():
    assert isinstance(build_extractor(make_settings(llm_provider="bedrock")), BedrockExtractor)
    chosen = build_extractor(make_settings(llm_provider="anthropic", anthropic_api_key="sk-test"))
    assert isinstance(chosen, AnthropicExtractor)


def test_anthropic_without_a_key_stops_the_service_at_start():
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        build_extractor(make_settings(llm_provider="anthropic", anthropic_api_key=None))


def test_unknown_provider_is_refused():
    with pytest.raises(ValueError, match="unknown LLM_PROVIDER"):
        build_extractor(make_settings(llm_provider="somewhere-else"))


def test_request_only_uses_parameters_the_real_sdk_accepts():
    """The fake client takes any keyword, so check the request against the SDK's real signature.

    A parameter the SDK does not know raises a TypeError at call time, which is a 500 in
    production and cannot be seen with a permissive fake.
    """
    import inspect

    real = anthropic.Anthropic(api_key="sk-test").messages.create
    accepted = set(inspect.signature(real).parameters)
    client = FakeAnthropic(_good_input())
    _extract(client)
    unknown = set(client.request) - accepted
    assert not unknown, f"parameters the SDK rejects: {sorted(unknown)}"
