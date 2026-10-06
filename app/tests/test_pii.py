import logging

from kyc.pii import RedactingFilter, mask, scrub


def test_mask_keeps_only_the_tail():
    assert mask("ZZ1234567") == "*******67"
    assert mask("ab") == "**"
    assert mask(None) == ""


def test_scrub_removes_emails_dates_and_identifiers():
    out = scrub("holder jane@example.com born 1990-04-12 id ZZ1234567 ok")
    assert "jane@example.com" not in out
    assert "1990-04-12" not in out
    assert "ZZ1234567" not in out


def test_scrub_keeps_document_uuids():
    uid = "3f2b8c1e-9d4a-4e7b-8a21-5c6d7e8f9a0b"
    assert uid in scrub(f"document {uid} processed")


def test_filter_scrubs_formatted_messages(caplog):
    logger = logging.getLogger("kyc.test")
    logger.addFilter(RedactingFilter())
    with caplog.at_level(logging.INFO, logger="kyc.test"):
        logger.info("value %s", "ZZ1234567")
    assert "ZZ1234567" not in caplog.text


def test_scrub_stays_fast_on_hostile_input():
    """Log text can contain attacker-controlled content; the patterns must not backtrack badly."""
    import time

    from kyc.pii import scrub

    for hostile in ("a" * 100_000, "a-" * 50_000, "a." * 50_000, "x" * 50_000 + "@"):
        started = time.perf_counter()
        scrub(hostile)
        assert time.perf_counter() - started < 2.0


def test_scrub_masks_tokens_with_digits_but_keeps_plain_words():
    from kyc.pii import scrub

    assert scrub("passport ZZ1234567 issued") == "passport [id] issued"
    assert scrub("document processed successfully") == "document processed successfully"
    assert scrub("mail zed.fake@example.org now") == "mail [email] now"
