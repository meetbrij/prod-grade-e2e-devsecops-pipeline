"""Document types, the fields to extract from each, and the validation rules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class DocumentType(StrEnum):
    ID_DOCUMENT = "id_document"
    PROOF_OF_ADDRESS = "proof_of_address"


@dataclass(frozen=True)
class FieldSpec:
    name: str
    description: str
    kind: str  # "text", "date" or "id_number"


FIELD_SPECS: dict[DocumentType, list[FieldSpec]] = {
    DocumentType.ID_DOCUMENT: [
        FieldSpec("full_name", "Holder's full name exactly as printed", "text"),
        FieldSpec("date_of_birth", "Date of birth, ISO format YYYY-MM-DD", "date"),
        FieldSpec("id_number", "Document or ID number exactly as printed", "id_number"),
        FieldSpec("nationality", "Nationality as printed", "text"),
        FieldSpec("expiry_date", "Expiry date, ISO format YYYY-MM-DD", "date"),
        FieldSpec("issuing_country", "Country that issued the document", "text"),
    ],
    DocumentType.PROOF_OF_ADDRESS: [
        FieldSpec("full_name", "Account holder's full name exactly as printed", "text"),
        FieldSpec("address_line", "Street address line as printed", "text"),
        FieldSpec("city", "City or emirate as printed", "text"),
        FieldSpec("issue_date", "Statement or bill date, ISO format YYYY-MM-DD", "date"),
        FieldSpec("issuer", "Company that issued the document", "text"),
    ],
}

_ID_NUMBER = re.compile(r"^[A-Z0-9][A-Z0-9-]{4,24}$")


def parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def format_problem(kind: str, value: str, today: date) -> str | None:
    """Return a short reason code if the value is malformed for its kind, else None."""
    if kind == "date":
        parsed = parse_iso_date(value)
        if parsed is None:
            return "invalid_format"
        if parsed.year < 1900 or parsed.year > today.year + 30:
            return "implausible_date"
    elif kind == "id_number":
        if not _ID_NUMBER.match(value.upper()):
            return "invalid_format"
    elif kind == "text" and len(value) < 2:
        return "invalid_format"
    return None
