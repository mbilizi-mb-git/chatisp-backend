# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-03-17

### Added

- Initial release of ChatISP AI backend.
- Asynchronous FastAPI application with SQLite database.
- User management via device ID (implicit authentication).
- Multiple conversations per user with pinning, renaming, deletion.
- Streaming chat with Groq LLM.
- RAG using ChromaDB and local embeddings.
- Hybrid search with BM25 and MMR.
- Rate limiting and token quota management.
- Script for document ingestion.
- Comprehensive test suite.
- Docker support and production-ready configuration.
