"""
Directory watcher for auto-parsing new/changed files.

Monitors a directory for new and modified files matching supported formats,
then invokes a callback to process each changed file.

Usage:
    from src.cli.watcher import DirectoryWatcher

    def process_file(file_path: Path) -> None:
        result = chomper.parse(file_path)
        print(result.text)

    watcher = DirectoryWatcher(
        directory=Path("./documents"),
        callback=process_file,
        interval=2.0,
        patterns={".pdf", ".docx"},
        recursive=True,
    )

    watcher.start()  # Blocks until Ctrl+C
"""

from __future__ import annotations

import os
import signal
import sys
import time
from collections.abc import Callable
from fnmatch import fnmatch
from pathlib import Path


class DirectoryWatcher:
    """Watch a directory for new/changed files and process them."""

    def __init__(
        self,
        directory: Path,
        callback: Callable[[Path], None],
        interval: float = 2.0,
        patterns: set[str] | None = None,
        recursive: bool = False,
        quiet: bool = False,
    ):
        """
        Initialize the directory watcher.

        Args:
            directory: Directory to watch.
            callback: Function to call when a file changes (receives file path).
            interval: Seconds between directory scans (default: 2.0).
            patterns: Set of file extensions (e.g., {".pdf", ".docx"}) or glob
                      patterns (e.g., {"*.pdf"}). If None, all files are watched.
            recursive: Whether to watch subdirectories.
            quiet: Suppress status messages.
        """
        self.directory = Path(directory).expanduser().resolve()
        self.callback = callback
        self.interval = interval
        self.patterns = patterns
        self.recursive = recursive
        self.quiet = quiet

        # State tracking
        self._running = False
        self._file_mtimes: dict[Path, float] = {}
        self._original_sigint = None

    def _log(self, message: str) -> None:
        """Print a status message to stderr."""
        if not self.quiet:
            print(message, file=sys.stderr)

    def _matches_pattern(self, file_path: Path) -> bool:
        """Check if a file matches the configured patterns."""
        if self.patterns is None:
            return True

        filename = file_path.name
        suffix = file_path.suffix.lower()

        for pattern in self.patterns:
            # Check if pattern contains glob characters (* or ?)
            if "*" in pattern or "?" in pattern:
                # Glob pattern (e.g., "*.pdf", "report*.docx")
                if fnmatch(filename.lower(), pattern.lower()):
                    return True
            elif pattern.startswith("."):
                # Extension with dot (e.g., ".pdf")
                if suffix == pattern.lower():
                    return True
            else:
                # Bare extension without dot (e.g., "pdf")
                if suffix == f".{pattern.lower()}":
                    return True

        return False

    def _scan_directory(self) -> dict[Path, float]:
        """
        Scan the directory and return a dict of {file_path: mtime}.

        Returns:
            Dictionary mapping file paths to modification times.
        """
        files: dict[Path, float] = {}

        try:
            if self.recursive:
                # Walk all subdirectories
                for root, _dirs, filenames in os.walk(self.directory):
                    root_path = Path(root)
                    for filename in filenames:
                        file_path = root_path / filename
                        if self._matches_pattern(file_path):
                            try:
                                mtime = file_path.stat().st_mtime
                                files[file_path] = mtime
                            except (OSError, PermissionError):
                                # File may have been deleted or inaccessible
                                pass
            else:
                # Only scan top-level directory
                for entry in os.scandir(self.directory):
                    if entry.is_file():
                        file_path = Path(entry.path)
                        if self._matches_pattern(file_path):
                            try:
                                mtime = entry.stat().st_mtime
                                files[file_path] = mtime
                            except (OSError, PermissionError):
                                pass
        except (OSError, PermissionError) as e:
            self._log(f"Warning: Cannot scan directory: {e}")

        return files

    def _detect_changes(
        self, current_files: dict[Path, float]
    ) -> tuple[list[Path], list[Path]]:
        """
        Detect new and modified files.

        Args:
            current_files: Current state of files from _scan_directory().

        Returns:
            Tuple of (new_files, modified_files).
        """
        new_files: list[Path] = []
        modified_files: list[Path] = []

        for file_path, mtime in current_files.items():
            if file_path not in self._file_mtimes:
                # New file
                new_files.append(file_path)
            elif mtime > self._file_mtimes[file_path]:
                # Modified file
                modified_files.append(file_path)

        return new_files, modified_files

    def _setup_signal_handler(self) -> None:
        """Set up SIGINT handler for graceful shutdown."""
        import threading

        # Only set up signal handlers in main thread
        if threading.current_thread() is not threading.main_thread():
            return

        def signal_handler(signum, frame):
            self._log("\nReceived interrupt signal. Stopping watcher...")
            self._running = False

        try:
            # Store original handler to restore later
            self._original_sigint = signal.signal(signal.SIGINT, signal_handler)

            # Also handle SIGTERM on Unix systems
            if hasattr(signal, "SIGTERM"):
                signal.signal(signal.SIGTERM, signal_handler)
        except ValueError:
            # signal only works in main thread - ignore
            pass

    def _restore_signal_handler(self) -> None:
        """Restore the original signal handler."""
        if self._original_sigint is not None:
            signal.signal(signal.SIGINT, self._original_sigint)

    def start(self) -> None:
        """
        Start watching the directory.

        This method blocks until stop() is called or Ctrl+C is pressed.
        Files that already exist when starting are tracked but not processed.
        """
        if not self.directory.is_dir():
            raise ValueError(f"Not a directory: {self.directory}")

        self._running = True
        self._setup_signal_handler()

        try:
            # Initial scan to establish baseline (don't process existing files)
            self._file_mtimes = self._scan_directory()
            initial_count = len(self._file_mtimes)

            if initial_count > 0:
                self._log(f"Found {initial_count} existing file(s) matching pattern")

            self._log(f"Watching for changes every {self.interval}s...")

            # Main watch loop
            while self._running:
                time.sleep(self.interval)

                if not self._running:
                    break

                # Scan for changes
                current_files = self._scan_directory()
                new_files, modified_files = self._detect_changes(current_files)

                # Process new files
                for file_path in new_files:
                    self._log(f"New file: {file_path}")
                    self._process_file(file_path)

                # Process modified files
                for file_path in modified_files:
                    self._log(f"Modified: {file_path}")
                    self._process_file(file_path)

                # Update state
                self._file_mtimes = current_files

        finally:
            self._restore_signal_handler()
            self._log("Watcher stopped.")

    def _process_file(self, file_path: Path) -> None:
        """
        Process a file by invoking the callback.

        Args:
            file_path: Path to the file to process.
        """
        try:
            self.callback(file_path)
        except Exception as e:
            self._log(f"Error processing {file_path}: {e}")

    def stop(self) -> None:
        """Stop watching the directory."""
        self._running = False


def parse_patterns(pattern_string: str | None) -> set[str] | None:
    """
    Parse a pattern string into a set of patterns.

    Supports:
    - Comma-separated extensions: ".pdf,.docx" or "pdf,docx"
    - Single glob pattern: "*.pdf"
    - Multiple patterns: "*.pdf,*.docx"

    Args:
        pattern_string: Pattern string from CLI argument.

    Returns:
        Set of patterns or None if no pattern specified.
    """
    if not pattern_string:
        return None

    patterns: set[str] = set()

    # Split by comma
    for part in pattern_string.split(","):
        part = part.strip()
        if not part:
            continue

        # Normalize extension patterns
        if part.startswith("."):
            # Already has dot: ".pdf"
            patterns.add(part.lower())
        elif not part.startswith("*"):
            # Bare extension: "pdf" -> ".pdf"
            patterns.add(f".{part.lower()}")
        else:
            # Glob pattern: "*.pdf"
            patterns.add(part)

    return patterns if patterns else None


def get_supported_extensions() -> set[str]:
    """
    Get the set of all supported file extensions from chomper.

    Returns:
        Set of extensions like {".pdf", ".docx", ".md", ...}
    """
    try:
        import chomper
        formats = chomper.list_formats()
        return {ext for ext, info in formats.items() if info["available"]}
    except ImportError:
        # Fallback if chomper not importable
        return {
            ".pdf", ".docx", ".doc", ".pptx", ".ppt",
            ".xlsx", ".xls", ".csv", ".tsv",
            ".html", ".htm", ".xml", ".json", ".yaml", ".yml",
            ".md", ".markdown", ".txt", ".text", ".log",
            ".py", ".js", ".jsx", ".ts", ".tsx", ".java",
            ".cpp", ".c", ".h", ".hpp", ".go", ".rs",
            ".eml", ".msg", ".epub", ".rtf",
        }
