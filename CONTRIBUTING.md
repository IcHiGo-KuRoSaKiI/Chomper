# Contributing to Parser-MCP

Thank you for your interest in contributing to Parser-MCP! This document provides guidelines and information for contributors.

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
- Use type hints for all function signatures
- Format code with `black .`
- Lint with `ruff check .`
- Maximum line length: 100 characters

**Testing:**
- Add tests for new features
- Ensure all existing tests pass: `pytest`
- For lightweight testing: `python src/tests/test_lightweight.py`

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
   from .base_extractor import BaseExtractor
   from ..models import RawDocument

   class NewFormatExtractor(BaseExtractor):
       SUPPORTED_EXTENSIONS = [".ext"]

       def extract(self, file_path: str) -> RawDocument:
           # Implementation
           pass
   ```

2. **Handle optional dependencies** gracefully:
   ```python
   try:
       import optional_library
       HAS_OPTIONAL = True
   except ImportError:
       HAS_OPTIONAL = False
   ```

3. **Register in `src/extractors/__init__.py`**

4. **Add to server.py**:
   - Import with try/except
   - Add to `FORMAT_DESCRIPTIONS`
   - Register in `_initialize_extractors()`

5. **Update requirements.txt** with optional dependency

6. **Add tests** in `src/tests/`

7. **Update documentation**:
   - README.md supported formats table
   - CLAUDE.md conventions section

## Adding New Chunking Strategies

1. Create in `src/chunking/strategies/`
2. Inherit from `BaseChunker`
3. Implement `chunk()` method
4. Register in `__init__.py`
5. Add to server.py `parse_document_chunked` tool

## Project Structure

```
src/
├── extractors/      # Add new format extractors here
├── chunking/        # Chunking strategies
├── enrichment/      # Content enrichers (keywords, sections)
├── formatters/      # Output formatters (JSON, TOON)
├── prompts/         # MCP prompt definitions
├── models/          # Data models
└── tests/           # Test suites
```

## Questions?

- Open a [Discussion](https://github.com/IcHiGo-KuRoSaKiI/Chomper/discussions)
- Tag maintainers in your issue/PR

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
