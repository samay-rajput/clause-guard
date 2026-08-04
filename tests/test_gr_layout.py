"""Authentic GR renderer harness — geometry, digit policy, links, fonts,
pipeline separation, and the flat-text round trip. PyMuPDF is a TEST-ONLY
dependency (never imported by the app).

Run:  python tests/test_gr_layout.py
"""
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src" / "export"))
sys.path.append(str(ROOT / "src" / "draftgen"))
sys.path.append(str(ROOT / "src" / "compliance"))

import fitz  # noqa: E402
from gr_layout import gr_docx, gr_pdf, parse_draft, to_devanagari_digits  # noqa: E402
from generate import SAMPLE, build_draft, unique_code  # noqa: E402
from scorecard import score  # noqa: E402

COPY_TO = [f"प्रत क्रमांक {i} — चाचणीसाठी लांब वितरण नोंद, मंत्रालय, मुंबई"
           for i in range(1, 15)]


def main():
    fields = dict(SAMPLE["mr"], date=date(2026, 8, 4))
    form = dict(fields, topic="", copy_to=COPY_TO)

    data = gr_pdf(form)
    doc = fitz.open(stream=data, filetype="pdf")

    # 1. geometry: US Letter, multi-page under the long प्रत list
    assert (round(doc[0].rect.width), round(doc[0].rect.height)) == (612, 792)
    assert doc.page_count >= 2, doc.page_count

    # 2. running header + footer on pages 2+ ONLY. The embedded subset font's
    # ToUnicode map leaks control chars inside ligatures — strip before probing.
    def clean(s):
        return re.sub(r"[\x00-\x1f]", "", s)

    p1, p2 = clean(doc[0].get_text()), clean(doc[1].get_text())
    total_dev = to_devanagari_digits(str(doc.page_count))
    assert "पृष्ठ" not in p1 and "क्रमांकः" not in p1
    assert "पृष्ठ" in p2 and "क्रमांकः" in p2
    assert f"पृष्ठ {total_dev} पैकी" in p2, p2[-120:]

    # 3. digit policy. The subset font's ToUnicode map leaks single junk ASCII
    # chars inside ligatures (visual render verified separately), so the real
    # test is: no ASCII digit RUN survives, and the known numbers extract in
    # Devanagari (PIN, year, the full 18-digit code).
    all_text = "".join(p.get_text() for p in doc)
    assert not re.search(r"[0-9]{2,}", all_text), \
        re.findall(r".{12}[0-9]{2,}.{6}", all_text)
    code_dev = to_devanagari_digits(unique_code(fields["date"],
                                                fields["subject"]))
    assert "४०० ०३२" in all_text and code_dev in all_text

    # 4. clickable URL on page 1
    assert any(l.get("uri") == "https://www.maharashtra.gov.in"
               for l in doc[0].get_links())

    # 5. subject block sits top-right; a Bold face is embedded
    subj_spans = [s for b in doc[0].get_text("dict")["blocks"] if "lines" in b
                  for l in b["lines"] for s in l["spans"]
                  if s["origin"][1] < 120]
    assert subj_spans and min(s["origin"][0] for s in subj_spans) > 300, \
        [round(s["origin"][0]) for s in subj_spans]
    assert any("Bold" in f[3] for f in doc[0].get_fonts()), doc[0].get_fonts()

    # 6. SEPARATION: the renderer never feeds text back into the pipeline —
    # the ASCII canonical draft is what the scorecard sees, and it stays 100%
    draft = build_draft(fields)
    assert score(draft)["pct"] == 100
    assert re.search(r"[0-9]", draft) and not re.search(r"[०-९]", draft)

    # 7. flat-text round trip: scaffold → parse_draft → authentic export
    parsed = parse_draft(draft)
    assert parsed["lang"] == "mr"
    assert parsed["subject"] == fields["subject"].replace("\n", " ")
    assert parsed["gr_number"] == fields["gr_number"]
    assert parsed["date"] == fields["date"]
    assert len(parsed["references"]) == len(fields["references"])
    # build_draft appends the financial clause → +1
    assert len(parsed["clauses"]) == len(fields["clauses"]) + 1, parsed["clauses"]
    assert parsed["code"] == unique_code(fields["date"], fields["subject"])
    assert parsed["signatory"] == fields["signatory"]
    assert parsed["designation"] == fields["designation"]
    rt = fitz.open(stream=gr_pdf(parsed), filetype="pdf")
    assert rt.page_count >= 1

    # 8. English render: same geometry, ASCII digits, zero Devanagari
    en = fitz.open(stream=gr_pdf(dict(SAMPLE["en"], date=date(2026, 8, 4),
                                      topic="", copy_to=["Select file, TE-2."])),
                   filetype="pdf")
    en_text = "".join(p.get_text() for p in en)
    assert not re.search(r"[०-९]", en_text)

    # 9. DOCX parity builds and re-reads
    from docx import Document
    import io
    d = Document(io.BytesIO(gr_docx(form)))
    body = "\n".join(p.text for p in d.paragraphs)
    assert "महाराष्ट्र शासन" in body and "प्रत," in body
    sec = d.sections[0]
    assert round(sec.page_width.pt) == 612 and sec.different_first_page_header_footer

    print("test_gr_layout OK — geometry, header/footer policy, digit policy, "
          "link, fonts, separation, round trip, en, docx")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
