"""DOCX text extraction walking paragraphs and tables in document order (spec §10.4)."""

from __future__ import annotations

import io

from app.errors import docx_parse_failed

W_P = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
W_TBL = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tbl"
W_T = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
W_TR = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tr"
W_TC = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tc"


def _paragraph_text(element) -> str:
    return "".join(node.text or "" for node in element.iter(W_T)).strip()


def _table_text(table_element) -> str:
    rows: list[str] = []
    for row in table_element.iter(W_TR):
        cells = [_paragraph_text(cell) for cell in row.iter(W_TC)]
        cells = [cell for cell in cells if cell]
        if cells:
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def extract_docx_text(data: bytes) -> tuple[str, dict]:
    """Return ``(text, parse_meta)``; tables are included, headers/footers are not."""
    if not data.startswith(b"PK\x03\x04"):
        raise docx_parse_failed("not a zip container")

    import docx
    from docx.document import Document as DocxDocument
    from docx.opc.exceptions import PackageNotFoundError

    try:
        document = docx.Document(io.BytesIO(data))
    except (PackageNotFoundError, KeyError, ValueError) as exc:
        raise docx_parse_failed(str(exc)[:120]) from exc
    except Exception as exc:  # noqa: BLE001
        raise docx_parse_failed(str(exc)[:120]) from exc

    if not isinstance(document, DocxDocument):
        raise docx_parse_failed("unexpected document type")

    chunks: list[str] = []
    paragraph_count = 0
    table_count = 0

    # Iterate the body in order so paragraphs and tables interleave correctly.
    body = document.element.body
    for child in body:
        if child.tag == W_P:
            text = _paragraph_text(child)
            if text:
                chunks.append(text)
                paragraph_count += 1
        elif child.tag == W_TBL:
            text = _table_text(child)
            if text:
                chunks.append(text)
                table_count += 1

    text = "\n".join(chunks).strip()
    meta = {
        "paragraphs": paragraph_count,
        "tables": table_count,
        "limits_ignored": ["headers", "footers", "textboxes"],
    }
    return text, meta
