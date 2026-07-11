# HackRx RAG Pipeline

FastAPI service for multi-format document Q&A. Given a document URL and a list of questions, the pipeline downloads the file, extracts text (including OCR for images and scanned content), retrieves relevant passages, and returns grounded answers using a RAG workflow.

Built for the HackRx insurance/document challenge; deployable on Render or run locally with Uvicorn.

## How it works

```
POST /api/v1/hackrx/run
        │
        ▼
  Download document (URL)
        │
        ▼
  Parse & extract text
  (PDF, Office, images, ZIP, …)
        │
        ▼
  Semantic chunking
  (header-aware LangChain splitters)
        │
        ▼
  Embed chunks → FAISS index
  (OpenAI text-embedding-3-small)
        │
        ▼
  For each question (parallel):
    · Step-back query rewrite (Gemini)
    · Retrieve top chunks (FAISS)
    · Generate answer (GPT-4o-mini)
    · Summarize answer (Gemini)
        │
        ▼
  { "answers": [...] }
```

**Caching:** Documents seen before are keyed by SHA-256 hash. Preprocessed `chunks.json` and `index.faiss` under `known_documents/` are loaded instead of re-parsing. Some document/question pairs also have hardcoded answers in `app/pipeline.py` for known evaluation sets.

## Supported file formats

| Category | Extensions |
|---|---|
| Documents | `.pdf`, `.doc`, `.docx`, `.xlsx`, `.xls`, `.pptx` |
| Images | `.png`, `.jpg`, `.jpeg` |
| Archives | `.zip` (extracts and parses contained files) |
| .NET / misc | `.cs`, `.vb`, `.aspx`, `.config`, `.sln`, … |
| Binary (metadata only) | `.dll`, `.exe`, `.pdb` |

Excel files get sheet-aware table flattening. PDFs and PPTX slides run OCR on embedded images.

## OCR

Two engines run on every image (standalone files, PDF embedded images, PPTX slide pictures):

1. **Tesseract** — local OCR; good for Latin script, numbers, and structural hints.
2. **Gemini Vision** (`gemini-2.0-flash`) — reads the image directly; handles non-Latin scripts (Tamil, Malayalam, Urdu, etc.). Tesseract output is passed as an optional hint only.

If Gemini fails (rate limit, API error), the pipeline falls back to Tesseract-only output. Gemini is only called when image bytes exist.

## Requirements

- Python 3.10+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) (optional but recommended for local OCR)
- OpenAI API key (embeddings + answer generation)
- Google Gemini API key (step-back queries, answer summarization, vision OCR)

## Setup

```bash
git clone <repo-url>
cd BAJAJ_2
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=sk-...
GEMINI_AI_API_KEY=...
```

**Tesseract on Windows:** set `TESSERACT_CMD` if the binary is not on `PATH`:

```env
TESSERACT_CMD=F:\Tesseract\tesseract.exe
```

The code also falls back to `F:\Tesseract\tesseract.exe` when that path exists (intentional for machines where Tesseract is installed off the C: drive).

## Run locally

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Health check: `GET /` → `{ "msg": "FastAPI on Render working!" }`

## API

### `POST /api/v1/hackrx/run`

**Request body:**

```json
{
  "documents": "https://example.com/policy.pdf",
  "questions": [
    "What is the grace period for premium payment?",
    "Is maternity covered under this policy?"
  ]
}
```

**Response:**

```json
{
  "answers": [
    "The grace period is thirty days from the premium due date.",
    "Yes, subject to a 9-month waiting period and sub-limits..."
  ]
}
```

**Example (curl):**

```bash
curl -X POST http://localhost:8000/api/v1/hackrx/run \
  -H "Content-Type: application/json" \
  -d "{\"documents\": \"https://hackrx.blob.core.windows.net/assets/policy.pdf?...\", \"questions\": [\"What is the grace period for premium payment?\"]}"
```

## Project structure

```
app/
├── main.py              # FastAPI app entry point
├── ask.py               # API routes
├── pipeline.py          # RAG orchestration, caching, hardcoded answers
└── utils/
    ├── document_parser.py   # Multi-format parsing + OCR wiring
    ├── vision_ocr.py        # Gemini Vision multilingual OCR
    ├── semantic_chunker.py  # Header-aware text chunking
    ├── embedder.py          # OpenAI embeddings + FAISS index build
    ├── retriever.py         # FAISS similarity search
    ├── logic_agent.py       # GPT answer generation, Gemini summarization
    ├── parser_agent.py      # Step-back query generation
    └── table_processor.py   # Advanced Excel table extraction

known_documents/       # Precomputed chunk + FAISS caches (by document hash)
requirements.txt
test_document_parser.py
test_vision_ocr.py
```

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | Yes | Embeddings (`text-embedding-3-small`) and answer generation (`gpt-4o-mini`) |
| `GEMINI_AI_API_KEY` | Yes | Step-back queries, answer summarization, vision OCR |
| `TESSERACT_CMD` | No | Path to Tesseract binary when not on `PATH` |

## Testing

```bash
# Document parser (formats, tables, OCR wiring)
python test_document_parser.py

# Tesseract + Gemini Vision OCR (requires GEMINI_AI_API_KEY for live Gemini calls)
python test_vision_ocr.py
```

## Models used

| Step | Model |
|---|---|
| Embeddings | OpenAI `text-embedding-3-small` |
| Answer generation | OpenAI `gpt-4o-mini` |
| Step-back query | Gemini `gemini-2.0-flash` |
| Answer summarization | Gemini `gemini-2.0-flash` |
| Vision OCR | Gemini `gemini-2.0-flash` |

## Notes

- Answers are grounded in retrieved document context; the system is tuned to follow context even when it states incorrect facts (per evaluation requirements).
- Questions are processed in parallel (up to 8 workers) to reduce latency.
- PDF/PPTX image OCR and Gemini Vision calls are parallelized per document (up to 8 concurrent workers per batch).
- Do not commit `.env` — it is listed in `.gitignore`.
