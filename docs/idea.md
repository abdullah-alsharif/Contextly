# Project Planning Prompt — Contextly

I want to plan and build a professional portfolio project called **Contextly**.

## Project Overview

Contextly is a multi-tenant AI document platform.

Users should be able to:

* Create an account and log in.
* Upload personal documents.
* Store their files securely.
* Have their documents processed asynchronously.
* Extract text from documents.
* Split documents into chunks.
* Generate embeddings for those chunks.
* Store embeddings and metadata for semantic retrieval.
* Create conversations based on their documents.
* Ask questions about their documents using RAG.
* Persist conversations and message history.
* See the sources used to generate each answer, including the document name and page number when available.

Every user's data must be completely isolated from other users.

The goal is to build something that looks and behaves like a real production-oriented SaaS application rather than a simple RAG demo.

---

# Main Technical Goals

The project should demonstrate understanding of:

* Backend architecture
* REST API design
* Authentication
* Authorization
* Multi-tenancy
* PostgreSQL
* pgvector
* Vector search
* RAG
* Embeddings
* LLM integration
* File storage
* Asynchronous document processing
* Security
* Docker
* Deployment
* Error handling
* Logging
* Testing
* RAG evaluation

---

# Cost Constraints

The project should be designed to run with **zero or minimal cost**, especially during development and portfolio demonstration.

Prefer free-tier or self-hosted solutions.

Do not make the architecture dependent on expensive managed services.

Avoid unnecessary infrastructure.

The architecture should also make external services replaceable in case their free tiers change.

---

# Initial Technology Direction

Use the following stack unless there is a strong technical reason to recommend an alternative:

### Frontend

* Next.js
* TypeScript
* Tailwind CSS

### Backend

* FastAPI
* Python

### Database

* PostgreSQL
* pgvector

### Authentication

Prefer Supabase Auth or another free-tier-compatible authentication solution.

### File Storage

Prefer Supabase Storage initially.

### Vector Storage

Use pgvector inside PostgreSQL rather than introducing a separate vector database unless there is a strong reason to do so.

### AI

Use NVIDIA Build / NVIDIA NIM endpoints where suitable free endpoints are available.

However, do not tightly couple the application to NVIDIA.

Create an AI provider abstraction so that NVIDIA can later be replaced with OpenRouter or another provider without changing the RAG business logic.

Example abstraction:

```text
AIProvider
├── embed()
└── generate()

NvidiaProvider
OpenRouterProvider
```

### Local Development

Use Docker where appropriate.

The local development environment should be easy to start with a minimal number of commands.

---

# 1. System Architecture

Design the complete system architecture.

Explain the responsibilities of:

* Frontend
* Backend
* PostgreSQL
* pgvector
* Authentication
* File storage
* AI provider
* Document processing
* RAG pipeline
* Chat system

Create an architecture diagram using Mermaid.

Clearly explain the flow from:

```text
User
→ Upload
→ Storage
→ Document processing
→ Chunking
→ Embeddings
→ pgvector
→ Retrieval
→ LLM
→ Answer
→ Conversation history
```

---

# 2. Database Architecture

Design the PostgreSQL schema.

At minimum consider:

```text
profiles
documents
document_chunks
conversations
messages
```

Define:

* Primary keys
* Foreign keys
* Relationships
* Indexes
* Timestamps
* Status fields
* Metadata
* Soft deletion if appropriate

Explain how embeddings should be stored using pgvector.

Consider whether additional tables are needed.

Do not overengineer the schema.

---

# 3. Multi-Tenancy

Design a secure multi-tenant architecture.

The system must guarantee that:

* User A cannot access User B's documents.
* User A cannot retrieve User B's embeddings.
* User A cannot access User B's conversations.
* User A cannot access User B's messages.
* User A cannot access User B's files.

Explain where authorization should be enforced:

* API layer
* Database layer
* Vector retrieval layer
* Storage layer

Evaluate whether PostgreSQL Row Level Security is appropriate and explain how it should be implemented.

Treat multi-tenancy as a security boundary, not just an application-level filter.

---

# 4. Document Ingestion Pipeline

Design the document ingestion lifecycle:

```text
Upload
→ Store file
→ Create document record
→ Processing
→ Parse
→ Chunk
→ Generate embeddings
→ Store vectors
→ Mark document as ready
```

Define document states such as:

```text
uploaded
processing
ready
failed
deleted
```

Explain:

* Synchronous vs asynchronous processing
* Background jobs
* Retry behavior
* Failure handling
* Duplicate files
* Document deletion
* Re-indexing
* Maximum file size
* Maximum pages
* Supported file types
* Partial processing failures

For the MVP, keep the architecture simple.

Explain when a proper queue/worker system becomes necessary.

---

# 5. RAG Architecture

Design the RAG pipeline in detail:

```text
User Question
→ Query preprocessing
→ Query embedding
→ Vector search
→ Metadata filtering
→ Top-K retrieval
→ Context construction
→ LLM
→ Answer
→ Source attribution
```

Explain the initial choices for:

* Chunk size
* Chunk overlap
* Top-K
* Similarity threshold
* Metadata
* Embedding model
* Prompt structure
* Context size

Start with a simple and reliable retrieval implementation.

Then describe future improvements such as:

* Hybrid search
* Reranking
* Query rewriting
* Parent-child retrieval
* Metadata-aware retrieval

Do not add these to the MVP unless they are necessary.

---

# 6. Source Attribution

Answers should provide citations or source references.

For example:

```text
According to your documents, the refund period is 30 days.

Sources:
- refund-policy.pdf — Page 4
- terms.pdf — Page 8
```

Design how source information should flow through the RAG pipeline.

Explain what metadata should be stored with each chunk.

Consider:

```text
document_id
filename
page_number
chunk_id
section
```

Determine which metadata should be persisted with each assistant message.

---

# 7. Chat Architecture

Design a persistent conversation system.

Users should be able to:

* Create conversations
* Rename conversations
* Delete conversations
* Send messages
* View message history
* Continue previous conversations

Design the data model for:

```text
Conversation
    ↓
Messages
    ├── User message
    └── Assistant message
```

Explain whether retrieved chunks/source references should be stored with assistant messages.

Design an approach for streaming LLM responses if appropriate.

---

# 8. Document Selection

Users should be able to control which documents a conversation can access.

For example:

```text
Chat: Job Applications

Selected documents:
[x] Resume.pdf
[x] Cover Letter.pdf
[x] Portfolio.pdf
[ ] Old Resume.pdf
```

Design the database and retrieval architecture needed to support this.

The retrieval query should effectively enforce:

```text
user_id = current_user
AND document_id IN selected_documents
```

Explain how this interacts with multi-tenancy and authorization.

---

# 9. API Design

Design a clean REST API.

Include endpoints for:

### Authentication

* Register
* Login
* Logout
* Current user

### Documents

* Upload document
* List documents
* Get document
* Delete document
* Reprocess document

### Conversations

* Create conversation
* List conversations
* Get conversation
* Rename conversation
* Delete conversation

### Messages

* Send message
* Get messages
* Stream assistant response if supported

For every endpoint define:

* HTTP method
* URL
* Authentication requirements
* Authorization requirements
* Request body
* Response
* Validation
* Error cases

---

# 10. AI Provider Abstraction

The application must not be tightly coupled to NVIDIA.

Design an interface such as:

```python
class AIProvider:
    def embed(self, texts):
        ...

    def generate(self, messages):
        ...
```

Then implement:

```text
NvidiaProvider
OpenRouterProvider
```

The RAG system should depend on the abstraction rather than a specific provider.

Provider configuration should come from environment variables.

For example:

```text
AI_PROVIDER=nvidia
```

Changing this value should allow switching providers with minimal code changes.

---

# 11. Frontend Architecture

Design the frontend pages:

```text
/login
/register
/dashboard
/documents
/documents/:id
/chat
/chat/:conversation_id
/settings
```

The UI should include:

* Authentication
* Document upload
* Document list
* Processing status
* Document deletion
* Conversation sidebar
* Chat interface
* Selected document management
* Source citations
* Loading states
* Error states
* Empty states

Explain the frontend state management approach.

Avoid unnecessary complexity.

---

# 12. Security

Create a security model for the application.

Analyze:

### Authentication

* Session handling
* Token validation
* Expiration

### Authorization

* User ownership
* Resource access
* Multi-tenancy

### File uploads

* File type validation
* File size limits
* Malicious files
* Filename sanitization
* Storage isolation

### RAG security

Analyze:

* Prompt injection inside uploaded documents
* Data leakage
* Cross-user retrieval
* Malicious document content
* LLM instruction conflicts

### API security

Consider:

* Rate limiting
* CORS
* Input validation
* SQL injection
* Secrets
* API abuse

Prioritize practical security measures suitable for a portfolio project.

---

# 13. Deployment Architecture

Design a deployment architecture that can operate on free tiers where possible.

Evaluate suitable options for:

* Next.js hosting
* FastAPI hosting
* PostgreSQL
* pgvector
* File storage
* AI API
* Domain
* HTTPS

Explain:

* Environment variables
* Secrets
* CORS
* Database migrations
* Production configuration
* Docker
* CI/CD

For every external service, identify a reasonable replacement if the free tier disappears.

Do not assume that a service will remain free forever.

---

# 14. Local Development

Create a local development architecture.

Prefer Docker Compose where appropriate.

The developer should be able to start the project with minimal setup.

Explain:

```text
Frontend
Backend
PostgreSQL
pgvector
```

and any other required services.

Provide the recommended repository structure.

Example:

```text
contextly/
├── frontend/
├── backend/
├── infrastructure/
├── docs/
├── docker-compose.yml
└── README.md
```

Improve this structure if necessary.

---

# 15. Observability

Design lightweight observability.

The system should make it possible to debug:

* API errors
* Document processing failures
* Embedding failures
* Retrieval failures
* LLM failures
* Retrieval latency
* LLM latency
* Token usage where available

Avoid expensive monitoring infrastructure.

Start with structured logging and simple application-level metrics.

---

# 16. Testing Strategy

Design tests for:

### Backend

* Unit tests
* API tests
* Integration tests

### Authentication

* Unauthorized requests
* Invalid tokens
* Expired sessions

### Multi-tenancy

Test that:

* User A cannot read User B's documents.
* User A cannot retrieve User B's chunks.
* User A cannot read User B's conversations.
* User A cannot access User B's files.

### Document processing

Test:

* Valid files
* Invalid files
* Large files
* Failed parsing
* Failed embeddings
* Retry behavior

### RAG

Test:

* Relevant retrieval
* Irrelevant retrieval
* Empty retrieval
* Source attribution
* Context construction

Also propose a simple RAG evaluation dataset for measuring retrieval quality.

---

# 17. MVP Scope

Define a strict MVP.

The MVP should contain only:

```text
Authentication
+
Document upload
+
PDF parsing
+
Chunking
+
Embeddings
+
pgvector
+
RAG retrieval
+
LLM answer
+
Chat history
+
Source citations
+
Multi-tenant security
```

Do not add advanced features until this works reliably.

---

# 18. Development Roadmap

Break development into incremental phases:

```text
Phase 0 — Project Setup
Phase 1 — Authentication
Phase 2 — Database
Phase 3 — Document Upload
Phase 4 — Document Processing
Phase 5 — Embeddings + pgvector
Phase 6 — Basic RAG
Phase 7 — Chat
Phase 8 — Source Citations
Phase 9 — Security Hardening
Phase 10 — Testing
Phase 11 — Deployment
Phase 12 — RAG Evaluation
```

For each phase provide:

* Objective
* Components
* Files/modules involved
* Dependencies
* Database changes
* API changes
* Definition of Done

Each phase should produce a working increment.

---

# 19. Avoid Overengineering

Do NOT introduce:

* Kubernetes
* Microservices
* Kafka
* Redis
* Celery
* Multiple databases
* Separate vector database
* Complex event-driven architecture

unless there is a concrete technical reason.

Start with a modular monolith:

```text
Next.js
+
FastAPI
+
PostgreSQL/pgvector
+
Storage
+
AI Provider
```

Explain when each additional component would become justified at a larger scale.

---

# 20. Final Deliverables

Before writing implementation code, produce:

1. High-level architecture
2. Mermaid architecture diagram
3. Component responsibilities
4. Database ERD
5. PostgreSQL schema
6. pgvector design
7. Multi-tenancy strategy
8. Document ingestion pipeline
9. RAG pipeline
10. Chat architecture
11. API specification
12. AI provider abstraction
13. Security model
14. Deployment architecture
15. Docker/local development architecture
16. Repository structure
17. Testing strategy
18. Observability strategy
19. MVP scope
20. Development roadmap
21. Major trade-offs
22. Major technical risks
23. Future scaling strategy

Do not write implementation code yet.

Do not blindly accept the proposed stack. Challenge architectural decisions where appropriate, especially around free-tier limitations, security, asynchronous processing, pgvector scalability, and AI provider availability.

The final result should be a practical technical blueprint that can be implemented incrementally and presented as a serious software engineering + AI/RAG portfolio project.
