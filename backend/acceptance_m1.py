"""
acceptance_m1.py — M1 retrieval acceptance check.

Runs a fixed set of Spanish questions (topics that the bundled legal corpus
actually covers) through rag.retrieve() and asserts that every query returns a
non-empty, cited result set. Prints the citations for each query so a human can
eyeball relevance.

Requires the built DB (backend/db/) and the embedding model present; it starts
the embedded llama.cpp embedding server on first query.

    cd backend
    python acceptance_m1.py

Exits non-zero if any query returns zero cited chunks.
"""

import asyncio
import sys

from rag import retrieve

# Questions map to subjects present in the corpus (ciberseguridad, estatuto
# funcionarios, transparencia, rentas, juntas de vecinos, compras, lobby, etc.).
# They are natural-language queries, not assertions about the law's content.
QUERIES = [
    "¿Qué obligaciones de ciberseguridad tienen las municipalidades?",
    "¿Cómo se regula la transparencia y el acceso a la información pública?",
    "¿Qué derechos tienen los funcionarios municipales según su estatuto?",
    "¿Cómo se aplican las medidas disciplinarias a un funcionario municipal?",
    "¿Qué son las rentas municipales y cómo se determinan las patentes?",
    "¿Cómo se constituye una junta de vecinos?",
    "¿Qué procedimientos rigen las compras públicas del Estado?",
    "¿En qué consiste la ley del lobby y quiénes son sujetos pasivos?",
    "¿Cómo se regula el expendio de bebidas alcohólicas?",
    "¿Qué funciones tiene el consejo comunal de seguridad pública?",
    "¿Qué establece la ley sobre participación ciudadana en la gestión pública?",
    "¿Cómo funciona el procedimiento administrativo ante los órganos del Estado?",
    "¿Qué contempla la transformación digital del Estado?",
    "¿Cuáles son las atribuciones del alcalde y del concejo municipal?",
    "¿Cómo se organizan los juzgados de policía local?",
]


async def main() -> int:
    failures = 0
    for i, q in enumerate(QUERIES, 1):
        context, chunks = await retrieve(q)
        cited = [c for c in chunks if c.get("source")]
        status = "OK" if (context.strip() and cited) else "FAIL"
        if status == "FAIL":
            failures += 1
        print(f"[{i:2d}/{len(QUERIES)}] {status}  {q}")
        for c in cited:
            print(f"        - {c['source']} (chunk {c['chunk_index']})")

    print("\n" + "=" * 60)
    total = len(QUERIES)
    print(f"{total - failures}/{total} queries returned cited results.")
    if failures:
        print(f"[error] {failures} queries returned no cited results.")
        return 1
    print("M1 retrieval acceptance: PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(asyncio.run(main()))
