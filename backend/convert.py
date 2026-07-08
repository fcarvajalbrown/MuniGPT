"""
convert.py — convert corpus PDFs to plain-text .txt using PyMuPDF.

The base corpus now arrives as .txt directly from BCN's XML API (see
corpus_fetcher.py), so this is mainly for Tier-3 municipality PDFs that IT drops
into corpus/municipio/ when pypdf extraction is poor.

By default the original PDF is KEPT. Pass --delete to remove each PDF after a
successful conversion.

Usage:
    python convert.py                      # convert PDFs under ./corpus, keep them
    python convert.py --corpus-dir C:/x    # different corpus root
    python convert.py --delete             # remove each PDF after converting
"""

import argparse
from pathlib import Path

import fitz  # pymupdf


def convert(corpus_dir: Path, delete: bool) -> int:
    count = 0
    for pdf in corpus_dir.rglob("*.pdf"):
        doc = fitz.open(str(pdf))
        text = "\n".join(page.get_text() for page in doc)
        doc.close()

        txt_path = pdf.with_suffix(".txt")
        txt_path.write_text(text, encoding="utf-8")
        print(f"Converted: {pdf.name} -> {txt_path.name}")
        count += 1

        if delete:
            pdf.unlink()
            print(f"  deleted original {pdf.name}")
    return count


def main():
    parser = argparse.ArgumentParser(description="Convert corpus PDFs to .txt (PyMuPDF).")
    parser.add_argument("--corpus-dir", type=Path, default=Path("corpus"))
    parser.add_argument("--delete", action="store_true",
                        help="Delete each PDF after successful conversion.")
    args = parser.parse_args()

    if not args.corpus_dir.exists():
        print(f"[error] Corpus directory not found: {args.corpus_dir}")
        return

    n = convert(args.corpus_dir, args.delete)
    print(f"\nDone. Converted {n} PDF(s) in {args.corpus_dir}/.")


if __name__ == "__main__":
    main()
