"""Does ThinnestAI's Add Knowledge Document read a PDF sent as a `url`?

Run inside the workers container:

    python -m scripts.probe_thinnest_pdf_knowledge

The documented API takes `url` ("A web page to fetch and index") or `text`, and says
"Files are uploaded in the console" (docs.thinnest.ai/api-reference/knowledge/
add-knowledge-document.md, read 24 Oct 2026). Whether that `url` fetcher accepts a PDF is
not documented, so this asks the vendor directly instead of guessing.

What it does, in our developer workspace, and undoes at the end whatever happens:
1. creates one throwaway agent (`byok: off`, never published, no number, no channel);
2. stores three PDFs we generate in our object store and adds each to the agent by a
   short-lived presigned link: a PDF with a text layer served `inline`, the same served
   `attachment` (our default disposition for client uploads), and an image-only "scanned"
   PDF; plus one public PDF as a control that does not depend on our store;
3. prints the vendor's answer for each (HTTP status, document status, passages, error);
4. lists the agent's documents, then asks the agent (Test Chat) for a price that exists
   only inside the text PDF, which shows whether the passages are actually searchable;
5. deletes every document, the agent and the stored objects.

Prints vendor statuses and our own probe text only; no client data is touched.
"""

from __future__ import annotations

import asyncio
import io
import json
import uuid
from typing import Any, Final

import httpx
from apps.api.core.settings import get_settings
from apps.api.engine.thinnest import AUTH_HEADER, AUTH_SCHEME, BASE_URL
from apps.workers.storage import delete_objects, presigned_url, store_kb_object
from fpdf import FPDF
from PIL import Image, ImageDraw

#: A fact that exists nowhere but inside the probe PDF, so a correct Test Chat answer can
#: only have come from the indexed passages.
SECRET_PRICE: Final = "4,287"
PRODUCT: Final = "Probe Villa 9Z"
#: W3C's long-standing accessibility test PDF: public, tiny, text layer.
PUBLIC_CONTROL_PDF: Final = (
    "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
)
TIMEOUT: Final = httpx.Timeout(180.0, connect=15.0)


def _text_pdf() -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=14)
    pdf.cell(0, 10, "Calevate probe price list", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=12)
    rows = (("Probe Flat 2A", "1,150"), (PRODUCT, SECRET_PRICE), ("Probe Plot 7", "880"))
    for name, price in rows:
        pdf.cell(80, 9, name, border=1)
        pdf.cell(50, 9, f"Rs {price} per sq ft", border=1, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def _scanned_pdf() -> bytes:
    """One page that is a picture of text, with no text layer, like a phone scan."""
    image = Image.new("RGB", (1240, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.text((60, 80), f"{PRODUCT} costs Rs {SECRET_PRICE} per sq ft", fill="black")
    draw.text((60, 160), "Scanned probe page: no text layer", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    pdf = FPDF()
    pdf.add_page()
    pdf.image(io.BytesIO(buffer.getvalue()), x=10, y=10, w=190)
    return bytes(pdf.output())


def _show(label: str, response: httpx.Response) -> dict[str, Any]:
    try:
        body: Any = response.json()
    except ValueError:
        body = {"raw": response.text[:300]}
    print(f"\n=== {label}: HTTP {response.status_code}")
    print(json.dumps(body, indent=2, ensure_ascii=False)[:1500])
    return body if isinstance(body, dict) else {}


async def main() -> None:
    settings = get_settings()
    if not settings.thinnest_api_key:
        raise SystemExit("THINNEST_API_KEY is not set in this container.")
    headers = {AUTH_HEADER: f"{AUTH_SCHEME} {settings.thinnest_api_key}"}
    run = uuid.uuid4().hex[:8]
    keys = {
        "text": f"probe/thinnest-pdf/{run}/text.pdf",
        "scanned": f"probe/thinnest-pdf/{run}/scanned.pdf",
    }
    await store_kb_object(key=keys["text"], data=_text_pdf(), content_type="application/pdf")
    await store_kb_object(key=keys["scanned"], data=_scanned_pdf(), content_type="application/pdf")
    links = {
        "text PDF, inline": presigned_url(keys["text"], ttl_s=900, disposition="inline"),
        "text PDF, attachment": presigned_url(keys["text"], ttl_s=900),
        "scanned PDF, inline": presigned_url(keys["scanned"], ttl_s=900, disposition="inline"),
        "public control PDF": PUBLIC_CONTROL_PDF,
    }
    agent_id: str | None = None
    documents: list[str] = []
    async with httpx.AsyncClient(base_url=BASE_URL, headers=headers, timeout=TIMEOUT) as client:
        try:
            agent_body = {"name": f"Calevate PDF probe {run}", "byok": "off"}
            created = _show("create throwaway agent", await client.post("/agents", json=agent_body))
            agent_id = created.get("id")
            if not agent_id:
                raise SystemExit("No agent was created; nothing else was tried.")
            knowledge = f"/agents/{agent_id}/knowledge"
            for label, link in links.items():
                if not link:
                    print(f"\n=== {label}: SKIPPED, our object store gave no presigned link")
                    continue
                body = _show(f"add {label}", await client.post(knowledge, json={"url": link}))
                # 201 answers the document; 422 carries the `failed` one as `document`.
                document = body.get("id") or (body.get("document") or {}).get("id")
                if document:
                    documents.append(document)
            _show("list documents", await client.get(knowledge, params={"limit": 25}))
            question = f"What is the price per sq ft of {PRODUCT}? Answer from your documents."
            _show(
                "test chat: price question",
                await client.post(f"/agents/{agent_id}/test-chat", json={"message": question}),
            )
            print(f"\nThe right answer is Rs {SECRET_PRICE} per sq ft.")
        finally:
            if agent_id:
                for document in documents:
                    response = await client.delete(f"/agents/{agent_id}/knowledge/{document}")
                    print(f"cleanup: delete document {document}: HTTP {response.status_code}")
                response = await client.delete(f"/agents/{agent_id}")
                print(f"cleanup: delete agent {agent_id}: HTTP {response.status_code}")
            removed = await delete_objects(list(keys.values()))
            print(f"cleanup: removed {removed} stored probe object(s)")


if __name__ == "__main__":
    asyncio.run(main())
