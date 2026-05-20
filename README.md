# TransitBot v3

US Transportation Career Platform — find jobs, plan career paths, explore role transitions.

## What's in the box

```
transitbot-v3/
├── Dockerfile
├── docker-compose.yml
├── data/
│   └── onet/                    ← place O*NET Excel files here
├── frontend/
│   └── index.html               ← single-file frontend
└── backend/
    ├── main.py                  ← FastAPI app
    ├── requirements.txt
    ├── core/
    │   ├── context.py           ← session state
    │   ├── llm.py               ← OpenAI + Ollama router
    │   └── prompts.py           ← system prompts
    ├── rag/
    │   ├── embedder.py          ← BGE-small / MiniLM
    │   ├── vector_store.py      ← Qdrant client
    │   ├── ingest.py            ← O*NET → Qdrant ingestion
    │   ├── retriever.py         ← all RAG query functions
    │   ├── job_boards.py        ← curated board registry
    │   └── usajobs_codes.py     ← OPM series + search params
    └── services/
        ├── intent.py            ← intent classifier + param extractor
        ├── jobs.py              ← USAJobs fetcher
        ├── resume.py            ← resume parser
        └── sessions.py          ← session store
```

---

## Quick start

### Step 1 — Prerequisites

- Docker Desktop (running)
- OpenAI API key **or** Ollama with Llama 3.2 3B

### Step 2 — Environment

Create `.env` in the project root:

```
# Required for OpenAI models
OPENAI_API_KEY=sk-...

# Optional — increases USAJobs rate limits
USAJOBS_API_KEY=your-key

# Optional — choose embedding model (default: BAAI/bge-small-en-v1.5)
EMBED_MODEL=BAAI/bge-small-en-v1.5
```

### Step 3 — O*NET data (optional but recommended)

Place these files in `data/onet/`:
- `Occupation_Data.xlsx`
- `Skills.xlsx`
- `Task_Statements.xlsx`
- `Technology_Skills.xlsx`
- `Education__Training__and_Experience_Categories.xlsx`

Download from: https://www.onetcenter.org/database.html

The app works without these files but career advice will use fallback data.

### Step 4 — Run

```powershell
docker compose up --build
```

Open http://localhost:8000

---

## Models

### OpenAI (cloud — recommended for best quality)

Enter your API key in the UI after opening the app. The key is stored in your browser only — it never touches our server.

| Model | Speed | Quality | Cost |
|---|---|---|---|
| GPT-4o mini | Fast | Very good | ~$0.001/msg |
| GPT-4o | Medium | Excellent | ~$0.01/msg |

### Cloud alternatives for Llama 3.2 3B (faster than local)

You can run Llama 3.2 3B on cloud infrastructure instead of your machine. All of these expose an OpenAI-compatible API — just set `OLLAMA_BASE_URL` in `.env` to point to them:

**Groq** — fastest, free tier available
```
OLLAMA_BASE_URL=https://api.groq.com/openai/v1
# Also set GROQ_API_KEY and use it as the OpenAI key in the UI
```

**Together AI** — reliable, pay-per-token
```
OLLAMA_BASE_URL=https://api.together.xyz/v1
```

**Fireworks AI** — fast inference
```
OLLAMA_BASE_URL=https://api.fireworks.ai/inference/v1
```

**Replicate** — easy setup
```
OLLAMA_BASE_URL=https://openai-proxy.replicate.com/v1
```

For any of these, select "Llama 3.2 3B" in the model dropdown and enter the cloud provider's API key in the OpenAI key field. The backend routes it to `OLLAMA_BASE_URL` automatically.

### Local Ollama

```powershell
# Install Ollama from ollama.com, then:
ollama pull llama3.2:3b
# Set OLLAMA_HOST=0.0.0.0 if running in Docker
```

---

## Adding O*NET credentials (optional)

Register free at https://services.onetcenter.org/ and add to `.env`:

```
ONET_USERNAME=your-username
ONET_PASSWORD=your-password
```

This enables live O*NET API enrichment on top of the local data.

---

## Health check

```
GET http://localhost:8000/health
```

Returns:
```json
{
  "status": "ok",
  "qdrant_roles": 34,
  "embed_model": "BAAI/bge-small-en-v1.5",
  "openai": true,
  "ollama": false,
  "usajobs_key": false
}
```

---

## Architecture summary

```
User message
    │
    ▼
Intent classifier (keyword fallback, <50ms)
    │
    ├── casual/general → session context only → LLM
    │
    ├── job_search ────► USAJobs API (live, USA only)
    │                         │
    │               ┌─────────┘
    │               ▼
    └── career/map ─► Qdrant vector search
                          roles · skills · certs · career_paths
                          │
                          ▼
                    Context assembly
                    (O*NET data + job listings + boards)
                          │
                          ▼
                    LLM (OpenAI or Ollama)
                          │
                          ▼
                    Grounded reply + job cards + board links
```
