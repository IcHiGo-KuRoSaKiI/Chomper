# Contributing to Chomper

Thank you for your interest in contributing to Chomper! This document provides guidelines and information for contributors.

## Code of Conduct

By participating in this project, you agree to maintain a respectful and inclusive environment for everyone.

## How to Contribute

### Reporting Bugs

1. Check if the bug has already been reported in [Issues](https://github.com/IcHiGo-KuRoSaKiI/Chomper/issues)
2. If not, create a new issue with:
   - Clear, descriptive title
   - Steps to reproduce
   - Expected vs actual behavior
   - Environment details (Python version, OS, dependencies)
   - Sample file (if applicable and non-sensitive)

### Suggesting Features

1. Open an issue with the `enhancement` label
2. Describe the feature and its use case
3. Explain why it would benefit the project

### Pull Requests

#### Before Starting

1. Fork the repository
2. Create a new branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. Set up your development environment:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -e ".[dev]"
   ```

#### Development Guidelines

**Code Style:**
- Follow PEP 8 guidelines
- Use type hints for all function signatures (PEP 585 style: `list`, `dict`, `str | None`)
- Format code with `black .`
- Lint with `ruff check .`
- Type check with `mypy` (`disallow_untyped_defs` everywhere except extractors, chunkers and formatters)
- Maximum line length: 100 characters
- Chain exceptions (`raise ValueError(...) from e`); error messages should say what was wrong and what to pass instead
- Keep heavy imports (PyMuPDF, pandas, sentence-transformers) inside the functions that need them; `import server` and `import chomper` must stay cheap

**Testing:**
- Add tests for new features in `src/tests/` (pytest's `testpaths`)
- Ensure all existing tests pass: `pytest`
- For lightweight testing: `python src/tests/test_lightweight.py`
- PDF fixtures are generated, not checked in: `python src/tests/fixtures/make_pdf_fixtures.py --list`

**Documentation:**
- Update README.md if adding new features
- Add docstrings to all public functions
- Include usage examples for new extractors/features

#### Commit Messages

Use clear, descriptive commit messages:
```
Add EPUB extractor with TOC support

- Implement EPUBExtractor class
- Add chapter extraction with beautifulsoup4
- Include table of contents parsing
- Add tests for EPUB functionality
```

#### Submitting

1. Push your branch to your fork
2. Open a Pull Request against `main`
3. Fill out the PR template with:
   - Description of changes
   - Related issue (if any)
   - Testing done
   - Screenshots (if UI-related)

## Adding New Extractors

If you want to add support for a new file format:

1. **Create the extractor** in `src/extractors/`:
   ```python
   from ..models.document import RawDocument
   from .base import BaseExtractor

   class NewFormatExtractor(BaseExtractor):
       SUPPORTED_EXTENSIONS = [".ext"]

       def extract(self, file_path: str) -> RawDocument:
           # Implementation: return Markdown text; record images with
           # image_utils.image_record() and mark them with image_marker()
           pass
   ```

2. **Handle optional dependencies** gracefully, with a module-level flag:
   ```python
   try:
       import optional_library
       OPTIONAL_AVAILABLE = True
   except ImportError:
       OPTIONAL_AVAILABLE = False
   ```

3. **Add the class to `_SOURCES`** in `src/extractors/__init__.py` (classes load on first access)

4. **Register in `src/server/config.py`**:
   - Add the extension to `FORMAT_DESCRIPTIONS`
   - Add an `_EXTRACTOR_SPECS` entry: `(module, class name, ("OPTIONAL_AVAILABLE",), "'chomper[ext]'")`; the registry reports the format unavailable, with that install hint, when a flag is false
   - Add a `_CHUNKER_SPECS` entry (e.g. `TextChunker`)

5. **Add the dependency as an extra** in `pyproject.toml` (and include it in `all`), and in `requirements.txt`

6. **Add tests** in `src/tests/`

7. **Update documentation**:
   - README.md supported formats table
   - docs/COMPONENTS.md extractor section

## Adding New Chunking Strategies

1. Create in `src/chunking/strategies/`
2. Inherit from `BaseChunker`; accept `target_size` and `overlap` in the constructor
3. Implement `chunk()` method (use `src/chunking/text_splitter.py` for free text, so chunks stay exact slices and never split code fences or table rows)
4. Register in `src/chunking/strategies/__init__.py`
5. Wire it into `build_chunker()` in `src/server/documents.py` (a format-specific chunker goes in `_CHUNKER_SPECS` in `src/server/config.py`; a new strategy name goes in `CHUNK_STRATEGIES` and the `chunking_strategy` enum in `src/server/tools.py`). The library, CLI and MCP server all pick it up from there.

## Project Structure

```
src/
├── server/          # Config, lazy registries, shared loader, cache, tool schemas
├── handlers/        # MCP tool handlers
├── extractors/      # Add new format extractors here
├── pdf_structure/   # Structural PDF parsing (headings, tables, lists, figures)
├── chunking/        # Chunking strategies and the shared text splitter
├── enrichment/      # Content enrichers (keywords, sections)
├── formatters/      # Output formatters (JSON, TOON)
├── cli/             # chomper-parse formatters, watch mode, REPL
├── prompts/         # MCP prompt definitions
├── models/          # Data models
└── tests/           # Test suites
```

## Questions?

- Open a [Discussion](https://github.com/IcHiGo-KuRoSaKiI/Chomper/discussions)
- Tag maintainers in your issue/PR

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
