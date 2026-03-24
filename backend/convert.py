import fitz
from pathlib import Path

for pdf in Path("corpus").rglob("*.pdf"):
    doc = fitz.open(str(pdf))
    text = "\n".join(page.get_text() for page in doc)
    doc.close()
    txt_path = pdf.with_suffix(".txt")
    txt_path.write_text(text, encoding="utf-8")
    print(f"Converted: {pdf.name}")
    pdf.unlink()  # delete the PDF after converting