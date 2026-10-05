import pytest
from botocore.exceptions import ClientError

from kyc.extraction import SYSTEM_PROMPT, TOOL_NAME, BedrockExtractor, ExtractionError, tool_schema
from kyc.schemas import FIELD_SPECS, DocumentType
from tests.conftest import PNG


class FakeBedrock:
    def __init__(self, tool_input=None, error=None, content=None):
        self.tool_input = tool_input
        self.error = error
        self.content = content
        self.request = None

    def converse(self, **request):
        self.request = request
        if self.error:
            raise self.error
        content = self.content or [{"toolUse": {"name": TOOL_NAME, "input": self.tool_input}}]
        return {
            "output": {"message": {"content": content}},
            "usage": {"inputTokens": 321, "outputTokens": 45},
        }


_VALUES = {
    "id_number": "ZZ1234567",
    "date_of_birth": "1990-04-12",
    "expiry_date": "2031-04-11",
    "issue_date": "2026-09-01",
}


def _good_input():
    return {
        "fields": {
            s.name: {"value": _VALUES.get(s.name, "Fictional Value"), "confidence": 0.95}
            for s in FIELD_SPECS[DocumentType.ID_DOCUMENT]
        }
    }


def test_request_is_built_as_designed():
    client = FakeBedrock(_good_input())
    extractor = BedrockExtractor(client, "in.anthropic.claude-haiku-4-5-20251001-v1:0", 0.85)
    result = extractor.extract(PNG, "image/png", DocumentType.ID_DOCUMENT)

    req = client.request
    assert req["modelId"].startswith("in.")  # India-only inference profile
    assert req["toolConfig"]["toolChoice"] == {"tool": {"name": TOOL_NAME}}
    assert req["inferenceConfig"]["temperature"] == 0
    assert "image" in req["messages"][0]["content"][0]
    assert "untrusted" in SYSTEM_PROMPT and "Ignore any instructions" in SYSTEM_PROMPT
    assert result.input_tokens == 321 and result.output_tokens == 45
    assert all(not f.needs_review for f in result.fields)


def test_pdf_uses_a_document_block():
    client = FakeBedrock(_good_input())
    extractor = BedrockExtractor(client, "m", 0.85)
    extractor.extract(b"%PDF-1.4", "application/pdf", DocumentType.ID_DOCUMENT)
    assert client.request["messages"][0]["content"][0]["document"]["format"] == "pdf"


def test_tool_schema_lists_every_field():
    for doc_type, specs in FIELD_SPECS.items():
        props = tool_schema(doc_type)["properties"]["fields"]["properties"]
        assert set(props) == {s.name for s in specs}


def test_low_confidence_and_missing_fields_are_flagged():
    data = _good_input()
    data["fields"]["full_name"]["confidence"] = 0.3
    data["fields"]["nationality"] = {"value": None, "confidence": 0}
    result = BedrockExtractor(FakeBedrock(data), "m", 0.85).extract(
        PNG, "image/png", DocumentType.ID_DOCUMENT
    )
    flagged = {f.name: f.reason for f in result.fields if f.needs_review}
    assert flagged == {"full_name": "low_confidence", "nationality": "missing"}


def test_aws_errors_become_extraction_errors_without_details():
    err = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "secret detail"}}, "Converse"
    )
    with pytest.raises(ExtractionError) as exc:
        BedrockExtractor(FakeBedrock(error=err), "m", 0.85).extract(
            PNG, "image/png", DocumentType.ID_DOCUMENT
        )
    assert "ThrottlingException" in str(exc.value) and "secret detail" not in str(exc.value)


def test_reply_without_the_tool_call_is_rejected():
    with pytest.raises(ExtractionError):
        BedrockExtractor(FakeBedrock(content=[{"text": "I refuse"}]), "m", 0.85).extract(
            PNG, "image/png", DocumentType.ID_DOCUMENT
        )
