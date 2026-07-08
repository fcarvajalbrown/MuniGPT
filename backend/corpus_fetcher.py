"""
corpus_fetcher.py
=================
Downloads the MuniGPT legal corpus from BCN (leychile.cl).

Usage:
    # Download base corpus (Tier 0 + Tier 1 + Tier 2):
    python corpus_fetcher.py

    # Also fetch ordenanzas for a specific municipality:
    python corpus_fetcher.py --municipio "Municipalidad de Chillán"

    # Download only specific tiers:
    python corpus_fetcher.py --tiers 0 1

Output:
    corpus/
    ├── tier0_general/
    ├── tier1_core/
    ├── tier2_extended/
    └── municipio/          (if --municipio is specified)

Dependencies:
    pip install httpx tqdm
"""

import httpx
import asyncio
import argparse
import sys
from pathlib import Path

# ── BCN XML API ─────────────────────────────────────────────────────────────────
# BCN's PDF export endpoint was discontinued; the stable interface is the norma
# XML API (opt=7), which returns the full structured text of any norma. No auth
# required, but a browser-like User-Agent is mandatory or BCN returns empty.
# We extract plain text from the <Texto> elements and save .txt directly (no PDF).
BCN_XML_URL = "https://www.bcn.cl/leychile/consulta/obtxml?opt=7&idNorma={idNorma}"

# XML namespace used by the leychile schema.
BCN_NS = "{http://www.leychile.cl/esquemas}"

# ── Corpus definition ──────────────────────────────────────────────────────────

TIER_0_GENERAL = [
    # Constitución y bases del Estado — aplican a todo organismo público
    {
        "idNorma": "242302",
        "filename": "constitucion_politica_1980",
        "desc": "Constitución Política de Chile (Cap. XIV municipios)",
    },
    {
        "idNorma": "191865",
        "filename": "ley_18575_bases_administracion_estado",
        "desc": "Ley 18.575 — Bases Generales Administración del Estado",
    },
    {
        "idNorma": "210676",
        "filename": "ley_19880_procedimientos_administrativos",
        "desc": "Ley 19.880 — Bases Procedimientos Administrativos",
    },
    {
        "idNorma": "276363",
        "filename": "ley_20285_transparencia",
        "desc": "Ley 20.285 — Transparencia y Acceso a Información Pública",
    },
    {
        "idNorma": "1023143",
        "filename": "ley_20500_participacion_ciudadana",
        "desc": "Ley 20.500 — Participación Ciudadana en Gestión Pública",
    },
    {
        "idNorma": "1202434",
        "filename": "ley_21663_ciberseguridad",
        "desc": "Ley 21.663 — Marco de Ciberseguridad",
    },
    {
        "idNorma": "1138479",
        "filename": "ley_21180_transformacion_digital",
        "desc": "Ley 21.180 — Transformación Digital del Estado",
    },
]

TIER_1_CORE = [
    # Normativa municipal directa — lo que un funcionario usa a diario
    {
        "idNorma": "251693",
        "filename": "dfl1_2006_locm_18695",
        "desc": "DFL 1/2006 — LOC Municipalidades 18.695 (texto refundido)",
    },
    {
        "idNorma": "30256",
        "filename": "ley_18883_estatuto_funcionarios_municipales",
        "desc": "Ley 18.883 — Estatuto Funcionarios Municipales",
    },
    {
        "idNorma": "7054",
        "filename": "dl_3063_rentas_municipales",
        "desc": "DL 3.063 — Rentas Municipales",
    },
    {
        "idNorma": "70040",
        "filename": "ley_19418_juntas_vecinos",
        "desc": "Ley 19.418 — Juntas de Vecinos y Organizaciones Comunitarias",
    },
    {
        "idNorma": "28104",
        "filename": "ley_15231_juzgados_policia_local",
        "desc": "Ley 15.231 — Juzgados de Policía Local",
    },
    {
        "idNorma": "213004",
        "filename": "ley_19886_compras_publicas",
        "desc": "Ley 19.886 — Compras y Contratación Pública",
    },
    {
        "idNorma": "230608",
        "filename": "ds250_reglamento_compras",
        "desc": "DS 250/2004 — Reglamento Ley de Compras Públicas",
    },
    {
        "idNorma": "13560",
        "filename": "ds458_lguc_urbanismo_construcciones",
        "desc": "DS 458 — Ley General de Urbanismo y Construcciones",
    },
    {
        "idNorma": "30745",
        "filename": "ley_19378_atencion_primaria_salud",
        "desc": "Ley 19.378 — Estatuto Atención Primaria de Salud Municipal",
    },
    {
        "idNorma": "1060115",
        "filename": "ley_20730_lobby",
        "desc": "Ley 20.730 — Lobby y Gestión de Intereses",
    },
]

TIER_2_EXTENDED = [
    # Normativa complementaria — según perfil del municipio
    {
        "idNorma": "60439",
        "filename": "dfl1_1997_estatuto_docentes_19070",
        "desc": "DFL 1/1997 — Estatuto Docentes (Ley 19.070)",
    },
    {
        "idNorma": "1111237",
        "filename": "ley_21040_nueva_educacion_publica",
        "desc": "Ley 21.040 — Nueva Educación Pública",
    },
    {
        "idNorma": "1194982",
        "filename": "ley_21591_royalty_minero",
        "desc": "Ley 21.591 — Royalty Minero / Fondo Equidad Territorial",
    },
    {
        "idNorma": "233184",
        "filename": "ds854_clasificaciones_presupuesto",
        "desc": "DS 854 — Clasificaciones Presupuesto Sector Público",
    },
    {
        "idNorma": "220208",
        "filename": "ley_19925_expendio_alcohol",
        "desc": "Ley 19.925 — Expendio y Consumo Bebidas Alcohólicas",
    },
    {
        "idNorma": "1096337",
        "filename": "ley_20965_consejo_seguridad_comunal",
        "desc": "Ley 20.965 — Consejo Comunal de Seguridad Pública",
    },
    {
        "idNorma": "207436",
        "filename": "dfl1_2003_codigo_trabajo",
        "desc": "DFL 1/2003 — Código del Trabajo (aplicable a honorarios municipales)",
    },
]

TIERS = {
    0: TIER_0_GENERAL,
    1: TIER_1_CORE,
    2: TIER_2_EXTENDED,
}

TIER_DIRS = {
    0: "tier0_general",
    1: "tier1_core",
    2: "tier2_extended",
    "municipio": "municipio",
}

# ── Downloader ─────────────────────────────────────────────────────────────────

def _extract_norma(xml_bytes: bytes) -> tuple[str, str, str, str]:
    """Parses BCN norma XML into (tipo, numero, titulo, full_text)."""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml_bytes)

    def _first_text(tag: str) -> str:
        el = root.find(f".//{BCN_NS}{tag}")
        return (el.text or "").strip() if el is not None and el.text else ""

    tipo   = _first_text("Tipo")
    numero = _first_text("Numero")
    titulo = _first_text("TituloNorma")

    # Concatenate every <Texto> element in document order — that is the law body.
    parts = [(el.text or "").strip() for el in root.iter(f"{BCN_NS}Texto")]
    full_text = "\n".join(p for p in parts if p)
    return tipo, numero, titulo, full_text


async def fetch_and_save_norma(
    client: httpx.AsyncClient,
    idNorma: str,
    filename: str,
    dest: Path,
    desc: str,
) -> dict:
    """
    Fetches a norma from BCN's XML API and saves its plain text as {filename}.txt.

    Returns a dict: {ok, tipo, numero, chars} (ok=False on failure/empty).
    """
    out_path = dest / f"{filename}.txt"
    if out_path.exists():
        print(f"  [skip] {desc} — already downloaded")
        return {"ok": True, "skipped": True}

    url = BCN_XML_URL.format(idNorma=idNorma)

    # BCN rate-limits bursts, returning HTTP 429 or a small HTML page instead of
    # XML. Retry with backoff; a real norma always starts with the XML prolog.
    last_reason = "unknown"
    for attempt in range(1, 6):
        try:
            response = await client.get(url, timeout=60.0, follow_redirects=True)
            if response.status_code == 429:
                last_reason = "HTTP 429 (throttled)"
                await asyncio.sleep(10 * attempt)
                continue
            response.raise_for_status()

            content = response.content
            if not content.lstrip().startswith(b"<?xml"):
                last_reason = f"non-XML response ({len(content)} bytes, likely throttled)"
                await asyncio.sleep(10 * attempt)
                continue

            tipo, numero, titulo, text = _extract_norma(content)
            if len(text) < 200:
                print(f"  [warn] {desc} — little text extracted ({len(text)} chars)")
                return {"ok": False}

            # Prepend the law identity so it appears in RAG context and citations.
            header = f"{tipo} {numero} — {titulo}\n\n"
            out_path.write_text(header + text, encoding="utf-8")
            print(f"  [ok]   {desc} — {tipo} {numero}, {len(text):,} chars")
            return {"ok": True, "tipo": tipo, "numero": numero, "chars": len(text)}

        except httpx.TimeoutException:
            last_reason = "timeout"
            await asyncio.sleep(5 * attempt)
        except httpx.HTTPStatusError as e:
            last_reason = f"HTTP {e.response.status_code}"
            break
        except Exception as e:
            last_reason = str(e)
            break

    print(f"  [fail] {desc} — {last_reason} (idNorma={idNorma})")
    return {"ok": False}


async def fetch_municipio_normas(
    client: httpx.AsyncClient,
    municipio: str,
) -> list[dict]:
    """
    Searches BCN for ordenanzas and reglamentos published by a municipality.

    Args:
        client:    Shared httpx async client.
        municipio: Municipality name, e.g. "Municipalidad de Chillán".

    Returns:
        List of dicts with idNorma, filename, desc for each matching norma.
    """
    import csv
    import io

    url = BCN_SEARCH_URL.format(query=httpx.URL(municipio).raw_path.decode())
    # Use the CSV export endpoint which is more reliable than HTML scraping
    csv_url = (
        "https://nuevo.leychile.cl/servicios/Consulta/script/exportarBSimpleMetas"
        f"?cadena={municipio.replace(' ', '+')}"
        "&exacta=0&tipoviene=1&orden=2&npagina=1&itemsporpagina=50"
        "&seleccionado=0&_=&exportar_formato=csv"
    )

    try:
        response = await client.get(csv_url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
    except Exception as e:
        print(f"  [fail] Could not search for {municipio}: {e}")
        return []

    normas = []
    try:
        # BCN CSV uses semicolons and has a header row
        reader = csv.DictReader(
            io.StringIO(response.text),
            delimiter=";",
        )
        for row in reader:
            id_norma = row.get("Identificación de la Norma", "").strip()
            tipo = row.get("Tipo Norma", "").strip()
            titulo = row.get("Título de la Norma", "").strip()
            organismo = row.get("Organismos", "").strip()

            # Only include ordenanzas and reglamentos from this municipality
            if not id_norma:
                continue
            if municipio.lower() not in organismo.lower():
                continue
            if tipo.lower() not in ("ordenanza", "decreto", "reglamento"):
                continue

            safe_title = titulo[:60].lower().replace(" ", "_").replace("/", "-")
            normas.append({
                "idNorma": id_norma,
                "filename": f"municipio_{id_norma}_{safe_title}",
                "desc": f"{tipo}: {titulo[:80]}",
            })
    except Exception as e:
        print(f"  [warn] Could not parse search results: {e}")

    return normas


async def run(tiers: list[int], municipio: str | None, corpus_dir: Path):
    """
    Main download orchestrator.

    Args:
        tiers:       List of tier numbers to download (0, 1, 2).
        municipio:   Optional municipality name for ordenanzas.
        corpus_dir:  Root output directory.
    """
    corpus_dir.mkdir(parents=True, exist_ok=True)

    # BCN's XML API returns an empty body unless the User-Agent looks like a browser.
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        )
    }

    validation: list[tuple[str, dict]] = []

    async with httpx.AsyncClient(headers=headers) as client:

        # Download each requested tier
        for tier_num in tiers:
            docs = TIERS[tier_num]
            tier_dir = corpus_dir / TIER_DIRS[tier_num]
            tier_dir.mkdir(parents=True, exist_ok=True)

            print(f"\n── Tier {tier_num}: {TIER_DIRS[tier_num]} ({len(docs)} documentos) ──")

            for doc in docs:
                result = await fetch_and_save_norma(
                    client,
                    idNorma=doc["idNorma"],
                    filename=doc["filename"],
                    dest=tier_dir,
                    desc=doc["desc"],
                )
                validation.append((doc["desc"], result))
                # Be polite to BCN — small delay between requests
                await asyncio.sleep(1.5)

        # Fetch municipality-specific ordenanzas if requested
        if municipio:
            muni_dir = corpus_dir / TIER_DIRS["municipio"]
            muni_dir.mkdir(parents=True, exist_ok=True)

            print(f"\n── Municipio: {municipio} ──")
            print("  Buscando ordenanzas y reglamentos en BCN...")

            muni_normas = await fetch_municipio_normas(client, municipio)

            if not muni_normas:
                print(f"  [warn] No se encontraron normas para '{municipio}'")
                print("  Consejo: verifica el nombre exacto en leychile.cl")
            else:
                print(f"  Encontradas {len(muni_normas)} normas")
                for doc in muni_normas:
                    await fetch_and_save_norma(
                        client,
                        idNorma=doc["idNorma"],
                        filename=doc["filename"],
                        dest=muni_dir,
                        desc=doc["desc"],
                    )
                    await asyncio.sleep(1.5)

    # Validation summary — flags any norma that failed or whose extracted
    # Tipo/Numero looks inconsistent with the expected description.
    print(f"\n{'='*60}\nValidacion de normas descargadas:")
    ok = 0
    for desc, res in validation:
        if not res.get("ok"):
            print(f"  [FALLO] {desc}")
            continue
        ok += 1
        if res.get("skipped"):
            print(f"  [existe] {desc}")
        else:
            print(f"  [ok] {res.get('tipo','?')} {res.get('numero','?'):>7}  ← {desc}")
    print(f"\n✓ {ok}/{len(validation)} normas OK en {corpus_dir}/")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    # Force UTF-8 stdout so box-drawing/accented output doesn't crash on the
    # Windows cp1252 console or when stdout is a piped subprocess (installer/Electron).
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="Descarga el corpus legal chileno para MuniGPT desde BCN."
    )
    parser.add_argument(
        "--tiers",
        nargs="+",
        type=int,
        choices=[0, 1, 2],
        default=[0, 1, 2],
        help="Tiers a descargar (0=general, 1=core municipal, 2=extendido). Default: todos.",
    )
    parser.add_argument(
        "--municipio",
        type=str,
        default=None,
        help='Nombre del municipio para buscar ordenanzas. Ej: "Municipalidad de Chillán"',
    )
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=Path("corpus"),
        help="Directorio de salida. Default: ./corpus",
    )

    args = parser.parse_args()

    print("MuniGPT — corpus_fetcher.py")
    print(f"Tiers: {args.tiers}")
    if args.municipio:
        print(f"Municipio: {args.municipio}")
    print(f"Destino: {args.corpus_dir}/")
    print()

    asyncio.run(run(
        tiers=args.tiers,
        municipio=args.municipio,
        corpus_dir=args.corpus_dir,
    ))


if __name__ == "__main__":
    main()