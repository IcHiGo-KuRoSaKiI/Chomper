# Chomper Documentation

Welcome to the Chomper documentation. This folder contains detailed technical documentation for developers and contributors.

## Documentation Index

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Complete system architecture, data flow, and component relationships |
| [COMPONENTS.md](COMPONENTS.md) | Detailed breakdown of extractors, chunkers, formatters, and handlers |
| [API.md](API.md) | MCP tool reference with examples |

## Quick Links

- **Main README**: [../README.md](../README.md)
- **Contributing Guide**: [../CONTRIBUTING.md](../CONTRIBUTING.md)
- **License**: [../LICENSE](../LICENSE)

## Architecture Overview

Chomper is built on a **modular, layered architecture**:

```
┌─────────────────────────────────────────────────────────────┐
│                     MCP Server Layer                        │
│                      (server.py)                            │
├─────────────────────────────────────────────────────────────┤
│                     Handler Layer                           │
│                   (src/handlers/)                           │
├─────────────────────────────────────────────────────────────┤
│                  Processing Pipeline                        │
│   ┌───────────┬───────────┬───────────┬───────────┐        │
│   │ Extractors│  Chunkers │ Enrichers │ Formatters│        │
│   └───────────┴───────────┴───────────┴───────────┘        │
├─────────────────────────────────────────────────────────────┤
│                    Data Models                              │
│        (RawDocument → Chunk → EnrichedChunk)               │
└─────────────────────────────────────────────────────────────┘
```

## Key Design Principles

1. **Modular Design**: Each component has a single responsibility
2. **Graceful Degradation**: Optional dependencies don't break core functionality
3. **Token Efficiency**: TOON format reduces LLM token usage by ~40%
4. **Extensibility**: Easy to add new formats, chunking strategies, or output formats
5. **MCP Native**: Built specifically for Model Context Protocol integration

## Getting Started

For development setup, see [CONTRIBUTING.md](../CONTRIBUTING.md).

For architecture deep-dive, start with [ARCHITECTURE.md](ARCHITECTURE.md).
