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
from tqdm import tqdm

# ── PDF export URL pattern ─────────────────────────────────────────────────────
# BCN exposes a direct PDF export endpoint for every norma.
# No authentication required — all public law is freely downloadable.
BCN_PDF_URL = (
    "https://nuevo.leychile.cl/servicios/Consulta/Exportar"
    "?radioExportar=Normas"
    "&exportar_formato=pdf"
    "&exportar_con_notas_bcn=True"
    "&exportar_con_notas_originales=True"
    "&exportar_con_notas_al_pie=True"
    "&nombrearchivo={filename}"
    "&hddResultadoExportar={idNorma}.0.0%23"
)

# Search URL for fetching ordenanzas by municipality name
BCN_SEARCH_URL = (
    "https://nuevo.leychile.cl/servicios/Consulta/script/exportarBSimpleMetas"
    "?cadena={query}"
    "&exacta=0"
    "&tipoviene=1"
    "&orden=2"
    "&npagina=1"
    "&itemsporpagina=20"
    "&seleccionado=0"
)

# ── Corpus definition ──────────────────────────────────────────────────────────

TIER_0_GENERAL = [
    # Constitución y bases del Estado — aplican a todo organismo público
    {
        "idNorma": "22199",
        "filename": "constitucion_politica_1980",
        "desc": "Constitución Política de Chile (Cap. XIV municipios)",
    },
    {
        "idNorma": "27902",
        "filename": "ley_18575_bases_administracion_estado",
        "desc": "Ley 18.575 — Bases Generales Administración del Estado",
    },
    {
        "idNorma": "213004",
        "filename": "ley_19880_procedimientos_administrativos",
        "desc": "Ley 19.880 — Bases Procedimientos Administrativos",
    },
    {
        "idNorma": "259243",
        "filename": "ley_20285_transparencia",
        "desc": "Ley 20.285 — Transparencia y Acceso a Información Pública",
    },
    {
        "idNorma": "1023143",
        "filename": "ley_20500_participacion_ciudadana",
        "desc": "Ley 20.500 — Participación Ciudadana en Gestión Pública",
    },
    {
        "idNorma": "1205964",
        "filename": "ley_21663_ciberseguridad",
        "desc": "Ley 21.663 — Marco de Ciberseguridad",
    },
    {
        "idNorma": "1212409",
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
        "idNorma": "6536",
        "filename": "dl_3063_rentas_municipales",
        "desc": "DL 3.063 — Rentas Municipales",
    },
    {
        "idNorma": "30614",
        "filename": "ley_19418_juntas_vecinos",
        "desc": "Ley 19.418 — Juntas de Vecinos y Organizaciones Comunitarias",
    },
    {
        "idNorma": "27668",
        "filename": "ley_15231_juzgados_policia_local",
        "desc": "Ley 15.231 — Juzgados de Policía Local",
    },
    {
        "idNorma": "213004",
        "filename": "ley_19886_compras_publicas",
        "desc": "Ley 19.886 — Compras y Contratación Pública",
    },
    {
        "idNorma": "236195",
        "filename": "ds250_reglamento_compras",
        "desc": "DS 250/2004 — Reglamento Ley de Compras Públicas",
    },
    {
        "idNorma": "13560",
        "filename": "ds458_lguc_urbanismo_construcciones",
        "desc": "DS 458 — Ley General de Urbanismo y Construcciones",
    },
    {
        "idNorma": "30595",
        "filename": "ley_19378_atencion_primaria_salud",
        "desc": "Ley 19.378 — Estatuto Atención Primaria de Salud Municipal",
    },
    {
        "idNorma": "1121560",
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
        "idNorma": "1067715",
        "filename": "ley_21040_nueva_educacion_publica",
        "desc": "Ley 21.040 — Nueva Educación Pública",
    },
    {
        "idNorma": "1186565",
        "filename": "ley_21591_royalty_minero",
        "desc": "Ley 21.591 — Royalty Minero / Fondo Equidad Territorial",
    },
    {
        "idNorma": "224571",
        "filename": "ds854_clasificaciones_presupuesto",
        "desc": "DS 854 — Clasificaciones Presupuesto Sector Público",
    },
    {
        "idNorma": "220737",
        "filename": "ley_19925_expendio_alcohol",
        "desc": "Ley 19.925 — Expendio y Consumo Bebidas Alcohólicas",
    },
    {
        "idNorma": "1096773",
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

async def download_pdf(
    client: httpx.AsyncClient,
    idNorma: str,
    filename: str,
    dest: Path,
    desc: str,
) -> bool:
    """
    Downloads a single norma PDF from BCN.

    Args:
        client:   Shared httpx async client.
        idNorma:  BCN norma identifier.
        filename: Output filename (without extension).
        dest:     Destination directory.
        desc:     Human-readable description for logging.

    Returns:
        True on success, False on failure.
    """
    out_path = dest / f"{filename}.pdf"
    if out_path.exists():
        print(f"  [skip] {desc} — already downloaded")
        return True

    url = BCN_PDF_URL.format(idNorma=idNorma, filename=filename)

    try:
        response = await client.get(url, timeout=60.0, follow_redirects=True)
        response.raise_for_status()

        # BCN returns HTML error pages with 200 status when a norma doesn't exist.
        # Detect this by checking content type.
        content_type = response.headers.get("content-type", "")
        if "pdf" not in content_type and len(response.content) < 5000:
            print(f"  [warn] {desc} — BCN returned non-PDF (idNorma={idNorma} may be wrong)")
            return False

        out_path.write_bytes(response.content)
        size_kb = len(response.content) // 1024
        print(f"  [ok]   {desc} — {size_kb} KB")
        return True

    except httpx.TimeoutException:
        print(f"  [fail] {desc} — timeout (idNorma={idNorma})")
        return False
    except httpx.HTTPStatusError as e:
        print(f"  [fail] {desc} — HTTP {e.response.status_code}")
        return False
    except Exception as e:
        print(f"  [fail] {desc} — {e}")
        return False


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

    headers = {
        "User-Agent": (
            "MuniGPT/0.1 corpus fetcher - Felipe Carvajal Brown "
            "(fcarvajalbrown@gmail.com)"
        )
    }

    async with httpx.AsyncClient(headers=headers) as client:

        # Download each requested tier
        for tier_num in tiers:
            docs = TIERS[tier_num]
            tier_dir = corpus_dir / TIER_DIRS[tier_num]
            tier_dir.mkdir(parents=True, exist_ok=True)

            print(f"\n── Tier {tier_num}: {TIER_DIRS[tier_num]} ({len(docs)} documentos) ──")

            for doc in docs:
                await download_pdf(
                    client,
                    idNorma=doc["idNorma"],
                    filename=doc["filename"],
                    dest=tier_dir,
                    desc=doc["desc"],
                )
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
                    await download_pdf(
                        client,
                        idNorma=doc["idNorma"],
                        filename=doc["filename"],
                        dest=muni_dir,
                        desc=doc["desc"],
                    )
                    await asyncio.sleep(1.5)

    # Summary
    total = sum(
        len(list((corpus_dir / TIER_DIRS[t]).glob("*.pdf")))
        for t in tiers
        if (corpus_dir / TIER_DIRS[t]).exists()
    )
    if municipio and (corpus_dir / TIER_DIRS["municipio"]).exists():
        total += len(list((corpus_dir / TIER_DIRS["municipio"]).glob("*.pdf")))

    print(f"\n✓ Corpus descargado: {total} PDFs en {corpus_dir}/")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
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