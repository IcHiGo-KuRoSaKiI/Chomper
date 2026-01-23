"""
Base class for document extractors.

All format-specific extractors inherit from BaseExtractor.
"""
from abc import ABC, abstractmethod
from pathlib import Path

from ..models.document import RawDocument


class BaseExtractor(ABC):
    """
    Abstract base class for document extractors.

    Extractors are responsible for reading a file and extracting
    raw content (text, images, structure) without chunking or analysis.
    """

    @abstractmethod
    def extract(self, file_path: str) -> RawDocument:
        """
        Extract raw content from a file.

        Args:
            file_path: Path to the document file

        Returns:
            RawDocument with extracted content

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file format is invalid
        """
        pass

    def validate_file(self, file_path: str) -> None:
        """
        Validate that file exists and has correct extension.

        Args:
            file_path: Path to validate

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file extension doesn't match expected format
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not path.is_file():
            raise ValueError(f"Not a file: {file_path}")

        # Subclasses can override to check specific extensions
        if hasattr(self, 'SUPPORTED_EXTENSIONS'):
            if path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
                raise ValueError(
                    f"Unsupported file extension: {path.suffix}. "
                    f"Expected: {self.SUPPORTED_EXTENSIONS}"
                )

    def _get_basic_metadata(self, file_path: str) -> dict:
        """
        Extract basic file metadata.

        Args:
            file_path: Path to file

        Returns:
            Dictionary with basic metadata (size, name, type)
        """
        path = Path(file_path)
        return {
            "filename": path.name,
            "file_path": str(path.absolute()),
            "file_size": path.stat().st_size,
            "file_extension": path.suffix.lower()
        }
