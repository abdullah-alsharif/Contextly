# AI Provider & Storage Abstractions

## 1. Principle

The RAG business logic depends on two interfaces and nothing else. Vendors live
behind them, selected by environment variables, so NVIDIA, Supabase Storage, or
OpenRouter can be swapped without touching retrieval/chat code.

## 2. `AIProvider`

```python
class AIProvider(Protocol):
    embedding_dims: int                 # must match the pgvector column dim
    embedding_model: str                # for logs/metrics
    chat_model: str

    async def embed(
        self, texts: list[str], *, batch_size: int = 32, input_type: str = "passage"
    ) -> list[list[float]]:
        """Embed texts; order preserved. Raises AIProviderError on failure.

        `input_type` ("passage"|"query") is only meaningful for asymmetric
        embedding models (NVIDIA nv-embedqa-e5-v5); symmetric providers ignore
        it. Documents embed as "passage"; the user's question as "query"
        (services/retrieval.py)."""

    async def generate(
        self,
        messages: list[dict],           # [{"role": "system"|"user"|"assistant", "content": str}]
        *,
        stream: bool = False,
    ) -> str | AsyncIterator[str]:
        """Complete a chat. Returns str when stream=False, token iterator when True."""

    async def count_tokens(self, text: str) -> int: ...
```

Implementations:

| Class | Notes |
|---|---|
| `NvidiaProvider` | NVIDIA Build endpoints: embeddings (`nvidia/nv-embedqa-e5-v5`, 1024 dims — the model routed by the hosted NV-API; `nvidia/bge-m3` was retired there and 404s. Asymmetric: requires `input_type` in the request body, query/passage. **Input cap: 512 tokens per text** — operate at `CHUNK_SIZE_TOKENS=400` with real NVIDIA embeddings), chat (`meta/llama-3.3-70b-instruct` or similar free endpoint). Uses `NVIDIA_API_KEY` |
| `OpenRouterProvider` | `openrouter/…` chat + `openai/…` embeddings; uses `OPENROUTER_API_KEY`. Enabled by `AI_PROVIDER=openrouter` |

Selection:
```python
# config.py
AI_PROVIDER = os.environ["AI_PROVIDER"]            # "nvidia" | "openrouter" | "fake"
provider = {"nvidia": NvidiaProvider, "openrouter": OpenRouterProvider,
            "fake": FakeProvider}[AI_PROVIDER](...)
```

- **FakeProvider** (deterministic embeddings + canned answers) exists for tests and
  offline development — no API key, no cost, no flakiness in CI.
- Contract notes: `embed` batches internally with retry/backoff; `generate(stream=True)`
  yields deltas without trailing state. Errors are raised as `AIProviderError` with
  provider+status attached so logs stay diagnosable.
- Dimensionality: validated at startup — `embedding_dims` must equal the pgvector
  column dim; mismatched providers fail fast with a clear message.

## 3. `StorageProvider`

```python
class StorageProvider(Protocol):
    async def upload(self, *, key: str, data: bytes, content_type: str) -> None: ...
    async def download(self, *, key: str) -> bytes: ...
    async def delete(self, *, key: str) -> None: ...
    async def signed_url(self, *, key: str, expires_in_seconds: int = 300) -> str: ...
```

Implementations: `SupabaseStorageProvider` (MVP), `S3StorageProvider` / `B2StorageProvider`
(future). Selected by `STORAGE_PROVIDER=supabase|s3|local`.

**Local dev:** `LocalStorageProvider` writes to `./data/storage/{user_id}/docs/…` —
zero external deps for offline development and tests.

Key convention (security-critical): every key starts with `{user_id}/…`. Providers must
reject keys that attempt path traversal or omit the tenant prefix.

## 4. Failure policy (both abstractions)

- Network/timeout → raise; callers retry with backoff (2 attempts for chat, 3 for embed).
- 401/403 from vendor → do **not** retry; log and surface `configuration error` — these
  mean a bad key, not a transient failure.
- 429 → exponential backoff honoring `Retry-After` when present.
- All calls emit a metric + structured log with provider, model, latency, and token
  counts where available (see [observability.md](observability.md)).

## 5. What this buys

| Concern | Answer |
|---|---|
| NVIDIA free tier disappears | Set `AI_PROVIDER=openrouter`; no code changes |
| Supabase storage caps | Set `STORAGE_PROVIDER=s3` with any S3-compatible bucket; keys already tenant-prefixed |
| Supabase auth disappears | Swap the JWT verifier to any OIDC-compatible issuer; `profiles` table already decoupled from `auth.users` FKs in a swapable migration |
| CI/offline dev | `AI_PROVIDER=fake`, `STORAGE_PROVIDER=local` |
