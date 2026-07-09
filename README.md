# MuniGPT

Asistente de inteligencia artificial local para municipios chilenos. La operación
principal (chat, embeddings y búsqueda vectorial) funciona completamente sin
conexión a internet: ningún dato institucional sale del equipo. La única salida
opcional a la red es el endpoint `/search` (búsqueda web vía Brave), donde solo se
envía el texto de la consulta.

Desarrollado por **Felipe Carvajal Brown** en el contexto del cumplimiento de la
Ley 21.663 (Marco de Ciberseguridad).

---

## Arquitectura

```
corpus_fetcher.py  ->  ingest.py  ->  LanceDB  ->  main.py (/chat)  ->  respuesta
   (descarga BCN)      (chunk +        (vector +     (RAG + SSE)         citada
                        embed)          BM-25)
```

Toda la inferencia (chat y embeddings) corre localmente mediante un binario de
**llama.cpp** (`backend/bin/llama-server.exe`) que se incluye con el producto. No
se requiere Ollama ni GPU: el binario hace dispatch de instrucciones de CPU en
tiempo de ejecución y corre en cualquier x86-64.

## Requisitos

- Windows 10/11 (64 bits)
- 8 GB de RAM mínimo (16 GB recomendado). Con menos de 12 GB se selecciona
  automáticamente el modelo de chat más liviano (ver "Modelos").
- Espacio en disco suficiente para los modelos GGUF y el corpus.
- Solo para desarrollo: Python 3.12+ y Node.js 20+.

El usuario final no necesita instalar nada de lo anterior: el instalador empaqueta
el binario de llama.cpp, los modelos, el backend y la interfaz de escritorio.

## Componentes

- **backend/** — API FastAPI + RAG (Python).
- **frontend/** — interfaz de chat en React + Vite + TypeScript.
- **electron/** — shell de escritorio que arranca el backend, espera a `/status`
  y carga la interfaz construida.

## Desarrollo

### Backend

```powershell
git clone https://github.com/fcarvajalbrown/munigpt
cd munigpt
python -m venv .venv
.venv\Scripts\activate
pip install -r backend/requirements.txt
```

Colocar los modelos GGUF en `backend/models/` (nombres configurables en
`config.json`; ver "Modelos"). Descargar el corpus legal desde la BCN (requiere
internet, una sola vez) y construir el índice:

```powershell
cd backend
python corpus_fetcher.py            # todos los tiers
python ingest.py --reset            # chunk + embed en db/
uvicorn main:app --port 8000
```

### Frontend

```powershell
cd frontend
npm install
npm run dev        # servidor de desarrollo con proxy al backend en :8000
npm run build      # build de producción en frontend/dist
```

### Shell de escritorio (Electron)

```powershell
npm install        # en la raíz del repositorio
npm start          # arranca el backend + interfaz
npm run dist:dir   # empaqueta la app desempaquetada (sin instalador)
```

## Endpoints

- `POST /chat` — chat RAG. Responde por SSE: primero un evento `citations`, luego
  eventos `token`, y finalmente `done`.
- `POST /search` — búsqueda web vía Brave (requiere `braveApiKey` en `config.json`;
  responde 503 si no está configurada). Registra cada consulta saliente en un log
  de auditoría local (`backend/logs/search_audit.log`).
- `GET /status` — estado del backend y de los modelos (lo consulta el shell).
- `GET /config` — entrega `config.json` (sin secretos) al frontend.
- `POST /ingest` — reconstruye o actualiza el índice desde `backend/corpus/`.

## Modelos

Definidos en el bloque `models` de `config.json` (ver `config.example.json`), no
en Ollama. Todo corre sobre el binario de llama.cpp incluido:

- **Chat (por defecto):** `Qwen3-4B-Instruct-Q4_K_M.gguf`
- **Chat (equipos con poca RAM):** `Qwen3-1.7B-Q4_K_M.gguf`
- **Embeddings:** `nomic-embed-text-v2-moe.Q4_K_M.gguf`

El modelo de chat se elige automáticamente según la RAM total: bajo el umbral
`lowRamThresholdGb` (12 GB por defecto) se usa el modelo liviano. La búsqueda
vectorial usa **LanceDB** embebido, con índice de texto completo BM-25 (tantivy)
para búsqueda híbrida.

## Corpus legal

El corpus se define en las listas por tier de `backend/corpus_fetcher.py`
(`TIER_0_GENERAL`, `TIER_1_CORE`, `TIER_2_EXTENDED`), donde cada entrada apunta a
un `idNorma` de la BCN (leychile.cl). Para agregar una norma, se añade su
`idNorma`. Los documentos propios del municipio (ordenanzas, reglamentos) se
descubren dinámicamente vía el endpoint CSV de búsqueda de la BCN y se cargan en
la instalación.

## Pruebas

```powershell
cd backend
pip install -r requirements-dev.txt
pytest                       # unidad: dedup/merge de rag y chunking de ingest
python acceptance_m1.py      # 15 consultas de aceptación contra retrieve()
```

## Licencia

Distribuido por Felipe Carvajal Brown. El producto integra software y modelos de
código abierto, cada uno bajo su propia licencia (llama.cpp, LanceDB, FastAPI,
React, Electron, Vite, y los modelos Qwen y nomic-embed-text); consultar la
licencia de cada proyecto original para los términos aplicables.
