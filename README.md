# MuniGPT

Asistente de inteligencia artificial local para municipios chilenos. Funciona completamente sin conexión a internet para la operación principal. Ningún dato institucional sale del equipo.

Desarrollado por **Instituto Igualdad** en el contexto del cumplimiento de la Ley 21.663 (Marco de Ciberseguridad).

---

## Requisitos

- Windows 10/11 (64 bits)
- 8 GB RAM mínimo (16 GB recomendado)
- 8 GB de espacio libre en disco
- [Ollama](https://ollama.com/download) instalado
- Python 3.12+ con PyManager o instalación directa

## Instalación (desarrollo)

```powershell
git clone https://github.com/fcarvajalbrown/munigpt
cd munigpt
python -m venv venv
venv\Scripts\activate
pip install -r backend/requirements.txt
```

Instalar modelos en Ollama:

```powershell
ollama pull qwen2.5:3b
ollama pull nomic-embed-text
```

Descargar corpus legal (requiere internet, solo una vez):

```powershell
cd backend
python corpus_fetcher.py
```

O bien copiar PDFs manualmente en `backend/corpus/` desde [leychile.cl](https://www.bcn.cl/leychile/).

Ingestar corpus en LanceDB:

```powershell
python ingest.py --reset
```

Iniciar servidor:

```powershell
uvicorn main:app --port 8000
```

Abrir en el navegador: [http://localhost:8000](http://localhost:8000)

---

## Estructura

```
munigpt/
├── backend/
│   ├── main.py            # FastAPI — endpoints /chat /search /status /config
│   ├── rag.py             # Búsqueda híbrida LanceDB (vector + BM-25)
│   ├── ingest.py          # Ingesta de corpus en LanceDB
│   ├── corpus_fetcher.py  # Descarga automática desde BCN
│   ├── corpus/            # PDFs y TXTs del corpus legal (no en git)
│   └── db/                # Base de datos LanceDB (no en git)
├── frontend/              # React + Vite (por construir)
├── munigpt.py             # Lanzador — inicia backend y abre navegador
├── config.json            # Configuración por municipio
└── requirements.txt
```

## Corpus legal incluido

| Tier | Contenido |
|------|-----------|
| Tier 0 | Constitución, Ley 18.575, Ley 19.880, Ley 20.285, Ley 20.500, Ley 21.663, Ley 21.180 |
| Tier 1 | LOC Municipalidades, Estatuto Funcionarios, Rentas Municipales, Compras Públicas, DS 250, LGUC, Ley 19.378, Ley 20.730 |
| Tier 2 | Estatuto Docentes, Ley 21.040, Royalty Minero, Código del Trabajo, Ley 19.925, Ley 20.965 |
| Tier 3 | Documentos propios del municipio (ordenanza, reglamento, PLADECO) — cargados por IT en instalación |

## Modelo

- **Chat:** `qwen2.5:3b` vía Ollama (CPU-only, sin GPU requerida)
- **Embeddings:** `nomic-embed-text` vía Ollama
- **Vector DB:** LanceDB embedded (sin servidor separado)

## Licencia

Distribuido por Instituto Igualdad bajo modelo de licenciamiento no comercial.  
Modelos y dependencias open source: Qwen 2.5 (Tongyi Qianwen License 2.0), Ollama (MIT), LanceDB (Apache 2.0), FastAPI (MIT).

> **Nota v1.0:** Ollama será reemplazado por llama.cpp embebido para instalador completamente autocontenido sin dependencias externas.