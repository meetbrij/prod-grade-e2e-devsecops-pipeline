from tests.conftest import PII_DOB, PII_ID, PII_NAME, PNG, FakeExtractor

TEST_API_KEY = "test-key-not-a-secret"  # gitleaks:allow


def _upload(client, document_type="id_document", data=PNG, headers=None):
    return client.post(
        "/documents",
        files={"file": ("scan.png", data, "image/png")},
        data={"document_type": document_type},
        headers=headers or {},
    )


def test_health_and_root(make_client):
    client = make_client()
    with client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/").json()["service"] == "kyc-document-intelligence"


def test_upload_returns_validated_fields(make_client):
    with make_client() as client:
        r = _upload(client)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "extracted" and not body["needs_review"]
    names = {f["name"] for f in body["fields"]}
    assert {"full_name", "date_of_birth", "id_number"} <= names
    assert all(0 <= f["confidence"] <= 1 for f in body["fields"])


def test_low_confidence_fields_are_flagged_and_listed_for_review(make_client):
    with make_client(FakeExtractor(low=("id_number",))) as client:
        doc = _upload(client).json()
        assert doc["status"] == "needs_review"
        flagged = [f["name"] for f in doc["fields"] if f["needs_review"]]
        assert flagged == ["id_number"]
        queue = client.get("/documents", params={"needs_review": "true"}).json()
        assert [d["id"] for d in queue] == [doc["id"]]


def test_reviewer_correction_clears_the_flag(make_client):
    with make_client(FakeExtractor(low=("id_number",))) as client:
        doc = _upload(client).json()
        r = client.patch(f"/documents/{doc['id']}/fields/id_number", json={"value": "AB7654321"})
        assert r.status_code == 200
        body = r.json()
        field = next(f for f in body["fields"] if f["name"] == "id_number")
        assert field["value"] == "AB7654321" and field["reviewed"] and not field["needs_review"]
        assert body["status"] == "reviewed"
        assert client.get("/documents", params={"needs_review": "true"}).json() == []


def test_correction_with_a_malformed_value_is_rejected(make_client):
    with make_client(FakeExtractor(low=("date_of_birth",))) as client:
        doc = _upload(client).json()
        r = client.patch(
            f"/documents/{doc['id']}/fields/date_of_birth", json={"value": "yesterday"}
        )
        assert r.status_code == 422


def test_unknown_document_and_field_are_404(make_client):
    with make_client() as client:
        doc = _upload(client).json()
        assert client.get("/documents/does-not-exist").status_code == 404
        assert (
            client.patch(f"/documents/{doc['id']}/fields/nope", json={"value": "x"}).status_code
            == 404
        )


def test_file_type_is_sniffed_not_trusted(make_client):
    with make_client() as client:
        r = _upload(client, data=b"MZ this is an executable pretending to be a png")
    assert r.status_code == 415


def test_oversized_upload_is_rejected(make_client):
    with make_client(max_upload_bytes=100) as client:
        assert _upload(client, data=PNG + b"0" * 200).status_code == 413


def test_unsupported_document_type_is_a_validation_error(make_client):
    with make_client() as client:
        assert _upload(client, document_type="passport_selfie").status_code == 422


def test_bedrock_failure_is_a_502_with_no_detail_leak(make_client):
    with make_client(FakeExtractor(fail=True)) as client:
        r = _upload(client)
    assert r.status_code == 502 and "Throttling" not in r.text


def test_api_key_is_enforced_when_configured(make_client):
    with make_client(api_key=TEST_API_KEY) as client:
        assert _upload(client).status_code == 401
        assert _upload(client, headers={"X-API-Key": "wrong"}).status_code == 401
        assert _upload(client, headers={"X-API-Key": TEST_API_KEY}).status_code == 201
        assert client.get("/healthz").status_code == 200  # probes stay open


def test_logs_never_contain_personal_data(make_client, capsys):
    # The app installs its own log handler, so read what it actually writes (stderr), which is
    # exactly what Loki receives.
    with make_client(FakeExtractor(low=("id_number",))) as client:
        doc = _upload(client).json()
        client.patch(f"/documents/{doc['id']}/fields/id_number", json={"value": "AB7654321"})
    output = capsys.readouterr().err
    assert "document processed" in output and "field reviewed" in output  # guard: not vacuous
    for secret in (PII_NAME, PII_ID, PII_DOB, "AB7654321", "Fictional Utilities", "Nowhereville"):
        assert secret not in output
    assert doc["id"] in output  # identifiers are logged, values are not


def test_uploaded_bytes_are_not_stored(make_client):
    fake = FakeExtractor()
    with make_client(fake) as client:
        doc = _upload(client).json()
        assert "content" not in doc and PNG.hex() not in str(doc)
    assert fake.calls and fake.calls[0][0] == len(PNG)
