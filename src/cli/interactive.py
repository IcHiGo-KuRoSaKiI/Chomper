"""
Interactive REPL for document parsing.

Provides a command-line shell for parsing multiple documents in a single session
with configurable output formats and settings.

Usage:
    $ chomper-parse -i
    chomper> parse /path/to/document.pdf
    chomper> set format json
    chomper> metadata /path/to/document.pdf
    chomper> exit
"""

from __future__ import annotations

import atexit
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

# readline may not be available on all platforms
try:
    import readline
    HAS_READLINE = True
except ImportError:
    HAS_READLINE = False


class SessionState:
    """Tracks state across the interactive session."""

    def __init__(self):
        """Initialize session state with defaults."""
        self.output_format: str = "text"
        self.json_mode: bool = False
        self.max_chars: int | None = None
        self.chunk_size: int = 1000
        self.chunk_strategy: str = "auto"
        self.history: list[str] = []  # Files parsed this session
        self.template_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return current settings as dictionary."""
        return {
            "output_format": self.output_format,
            "json_mode": self.json_mode,
            "max_chars": self.max_chars,
            "chunk_size": self.chunk_size,
            "chunk_strategy": self.chunk_strategy,
            "template_path": self.template_path,
            "files_parsed": len(self.history),
        }

    def get_effective_format(self) -> str:
        """Get the effective output format (considering json_mode)."""
        if self.json_mode:
            return "json"
        return self.output_format


class InteractiveShell:
    """Interactive REPL for document parsing."""

    # Command aliases
    ALIASES: dict[str, str] = {
        "q": "exit",
        "quit": "exit",
        ":q": "exit",
        "?": "help",
        "h": "help",
        "cls": "clear",
        "ls": "history",
        "settings": "status",
        "config": "status",
    }

    def __init__(self, quiet: bool = False):
        """
        Initialize the interactive shell.

        Args:
            quiet: If True, suppress startup messages.
        """
        self.state = SessionState()
        self.quiet = quiet
        self._setup_readline()

    def _setup_readline(self) -> None:
        """Configure readline for history and completion."""
        if not HAS_READLINE:
            return

        # Try to load readline init file
        try:
            readline.read_init_file()
        except (FileNotFoundError, OSError):
            pass

        # Set up history file
        history_file = Path.home() / ".chomper_history"
        try:
            readline.read_history_file(str(history_file))
            # Limit history size
            readline.set_history_length(1000)
        except (FileNotFoundError, OSError):
            pass

        # Save history on exit
        atexit.register(self._save_history, str(history_file))

        # Set up tab completion
        readline.set_completer(self._completer)
        readline.parse_and_bind("tab: complete")

    def _save_history(self, history_file: str) -> None:
        """Save readline history to file."""
        if HAS_READLINE:
            try:
                readline.write_history_file(history_file)
            except OSError:
                pass

    def _completer(self, text: str, state: int) -> str | None:
        """Tab completion for commands and file paths."""
        # Get the full line buffer
        if HAS_READLINE:
            line = readline.get_line_buffer()
        else:
            line = text

        # Get completions
        if state == 0:
            # First call - generate completions
            self._completions = self._get_completions(line, text)

        # Return the state-th completion
        if state < len(self._completions):
            return self._completions[state]
        return None

    def _get_completions(self, line: str, text: str) -> list[str]:
        """Generate completions for the current input."""
        completions: list[str] = []

        parts = line.split()
        if not parts or (len(parts) == 1 and not line.endswith(" ")):
            # Complete command names
            commands = [
                "parse", "metadata", "chunk", "formats", "set",
                "history", "status", "clear", "help", "exit"
            ]
            completions = [c for c in commands if c.startswith(text)]
        elif parts[0] == "set" and (len(parts) == 1 or (len(parts) == 2 and not line.endswith(" "))):
            # Complete 'set' subcommands
            settings = ["format", "json", "max-chars", "chunk-size", "strategy", "template"]
            prefix = parts[1] if len(parts) > 1 else ""
            completions = [s for s in settings if s.startswith(prefix)]
        elif parts[0] == "set" and len(parts) >= 2 and parts[1] == "format":
            # Complete format names
            formats = ["text", "json", "csv", "markdown", "xml", "template"]
            prefix = parts[2] if len(parts) > 2 else ""
            completions = [f for f in formats if f.startswith(prefix)]
        elif parts[0] == "set" and len(parts) >= 2 and parts[1] == "json":
            # Complete on/off
            options = ["on", "off"]
            prefix = parts[2] if len(parts) > 2 else ""
            completions = [o for o in options if o.startswith(prefix)]
        elif parts[0] == "set" and len(parts) >= 2 and parts[1] == "strategy":
            # Complete strategies
            strategies = ["auto", "semantic", "fixed"]
            prefix = parts[2] if len(parts) > 2 else ""
            completions = [s for s in strategies if s.startswith(prefix)]
        elif parts[0] in ("parse", "metadata", "chunk"):
            # Complete file paths
            path_prefix = text if text else ""
            completions = self._complete_path(path_prefix)

        return completions

    def _complete_path(self, prefix: str) -> list[str]:
        """Complete file paths."""
        if not prefix:
            prefix = "./"

        # Expand user home
        if prefix.startswith("~"):
            prefix = os.path.expanduser(prefix)

        # Get directory and partial filename
        path = Path(prefix)
        if prefix.endswith(os.sep):
            directory = path
            partial = ""
        else:
            directory = path.parent
            partial = path.name

        try:
            if directory.exists() and directory.is_dir():
                completions = []
                for item in directory.iterdir():
                    if item.name.startswith(partial):
                        if item.is_dir():
                            completions.append(str(item) + os.sep)
                        else:
                            completions.append(str(item))
                return sorted(completions)[:50]  # Limit completions
        except (PermissionError, OSError):
            pass

        return []

    def run(self) -> int:
        """
        Run the interactive REPL.

        Returns:
            Exit code (0 for success).
        """
        if not self.quiet:
            self._print_banner()

        while True:
            try:
                # Get input
                try:
                    line = input("chomper> ").strip()
                except EOFError:
                    # Ctrl+D
                    print()
                    break

                if not line:
                    continue

                # Parse and execute command
                result = self._execute_command(line)
                if result == "exit":
                    if not self.quiet:
                        print("Goodbye!")
                    break

            except KeyboardInterrupt:
                # Ctrl+C - cancel current line, continue REPL
                print("\n(Use 'exit' to quit)")

        return 0

    def _print_banner(self) -> None:
        """Print the startup banner."""
        print("Chomper Interactive Mode")
        print("Type 'help' for available commands, 'exit' to quit.")
        print()

    def _execute_command(self, line: str) -> str | None:
        """
        Execute a command line.

        Args:
            line: The command line to execute.

        Returns:
            "exit" to quit the REPL, None otherwise.
        """
        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Handle aliases
        cmd = self.ALIASES.get(cmd, cmd)

        # Dispatch to command handler
        handlers: dict[str, Callable[[str], str | None]] = {
            "exit": self._cmd_exit,
            "parse": self._cmd_parse,
            "metadata": self._cmd_metadata,
            "chunk": self._cmd_chunk,
            "formats": self._cmd_formats,
            "set": self._cmd_set,
            "history": self._cmd_history,
            "status": self._cmd_status,
            "clear": self._cmd_clear,
            "help": self._cmd_help,
        }

        handler = handlers.get(cmd)
        if handler:
            return handler(args)
        else:
            print(f"Unknown command: {cmd}")
            print("Type 'help' for available commands.")
            return None

    def _cmd_exit(self, args: str) -> str:
        """Handle exit command."""
        return "exit"

    def _cmd_parse(self, args: str) -> None:
        """Parse a document."""
        if not args:
            print("Usage: parse <file_path>")
            return

        file_path = Path(args).expanduser().resolve()
        if not file_path.exists():
            print(f"Error: File not found: {file_path}")
            return

        # Import here to avoid slow startup
        import chomper
        from src.cli.formatters import get_formatter

        # Check format support
        if not chomper.is_supported(file_path):
            print(f"Error: Unsupported format: {file_path.suffix}")
            print("Use 'formats' to see supported formats.")
            return

        try:
            result = chomper.parse(file_path, max_chars=self.state.max_chars)

            # Get formatter
            output_format = self.state.get_effective_format()
            if output_format == "template" and not self.state.template_path:
                print("Error: Template not set. Use 'set template <path>'")
                return

            formatter = get_formatter(
                output_format,
                template_path=self.state.template_path,
                max_chars=self.state.max_chars,
            )

            output = formatter.format_parse_result(result)
            print(output)

            # Add to history
            self.state.history.append(str(file_path))

        except chomper.ChomperError as e:
            print(f"Error: {e}")
        except Exception as e:
            print(f"Unexpected error: {e}")

    def _cmd_metadata(self, args: str) -> None:
        """Get metadata for a document."""
        if not args:
            print("Usage: metadata <file_path>")
            return

        file_path = Path(args).expanduser().resolve()
        if not file_path.exists():
            print(f"Error: File not found: {file_path}")
            return

        import chomper
        from src.cli.formatters import get_formatter

        if not chomper.is_supported(file_path):
            print(f"Error: Unsupported format: {file_path.suffix}")
            return

        try:
            meta = chomper.extract_metadata(file_path)

            output_format = self.state.get_effective_format()
            if output_format == "template" and not self.state.template_path:
                output_format = "text"

            formatter = get_formatter(
                output_format,
                template_path=self.state.template_path,
            )

            output = formatter.format_metadata(meta)
            print(output)

            # Add to history
            if str(file_path) not in self.state.history:
                self.state.history.append(str(file_path))

        except chomper.ChomperError as e:
            print(f"Error: {e}")
        except Exception as e:
            print(f"Unexpected error: {e}")

    def _cmd_chunk(self, args: str) -> None:
        """Chunk a document."""
        if not args:
            print("Usage: chunk <file_path>")
            return

        file_path = Path(args).expanduser().resolve()
        if not file_path.exists():
            print(f"Error: File not found: {file_path}")
            return

        import chomper
        from src.cli.formatters import get_formatter

        if not chomper.is_supported(file_path):
            print(f"Error: Unsupported format: {file_path.suffix}")
            return

        try:
            chunks = chomper.chunk(
                file_path,
                strategy=self.state.chunk_strategy,  # type: ignore
                chunk_size=self.state.chunk_size,
            )

            output_format = self.state.get_effective_format()
            if output_format == "template" and not self.state.template_path:
                output_format = "text"

            formatter = get_formatter(
                output_format,
                template_path=self.state.template_path,
            )

            output = formatter.format_chunks(
                chunks, str(file_path), self.state.chunk_strategy
            )
            print(output)

            # Add to history
            if str(file_path) not in self.state.history:
                self.state.history.append(str(file_path))

        except chomper.ChomperError as e:
            print(f"Error: {e}")
        except Exception as e:
            print(f"Unexpected error: {e}")

    def _cmd_formats(self, args: str) -> None:
        """List supported formats."""
        import chomper

        formats = chomper.list_formats()

        # Group by availability
        available = {k: v for k, v in formats.items() if v["available"]}
        unavailable = {k: v for k, v in formats.items() if not v["available"]}

        print(f"\nAvailable formats ({len(available)}):")
        print("-" * 40)
        for ext, info in sorted(available.items()):
            print(f"  {ext:8} {info['description']}")

        if unavailable:
            print(f"\nUnavailable formats ({len(unavailable)}):")
            print("-" * 40)
            for ext, info in sorted(unavailable.items()):
                print(f"  {ext:8} {info['description']}")
        print()

    def _cmd_set(self, args: str) -> None:
        """Set a session option."""
        if not args:
            print("Usage: set <option> <value>")
            print()
            print("Options:")
            print("  format <name>     Set output format (text, json, csv, markdown, xml, template)")
            print("  json on|off       Toggle JSON output mode")
            print("  max-chars N       Set maximum output characters (0 = unlimited)")
            print("  chunk-size N      Set words per chunk (default: 1000)")
            print("  strategy <name>   Set chunking strategy (auto, semantic, fixed)")
            print("  template <path>   Set Jinja2 template file path")
            return

        parts = args.split(maxsplit=1)
        option = parts[0].lower()
        value = parts[1] if len(parts) > 1 else ""

        if option == "format":
            valid_formats = ["text", "json", "csv", "markdown", "xml", "template"]
            if not value:
                print(f"Current format: {self.state.output_format}")
                print(f"Valid formats: {', '.join(valid_formats)}")
            elif value.lower() in valid_formats:
                self.state.output_format = value.lower()
                self.state.json_mode = False  # Disable json_mode when setting format
                print(f"Output format set to: {value.lower()}")
            else:
                print(f"Invalid format: {value}")
                print(f"Valid formats: {', '.join(valid_formats)}")

        elif option == "json":
            if not value:
                status = "on" if self.state.json_mode else "off"
                print(f"JSON mode: {status}")
            elif value.lower() in ("on", "true", "1", "yes"):
                self.state.json_mode = True
                print("JSON mode: on")
            elif value.lower() in ("off", "false", "0", "no"):
                self.state.json_mode = False
                print("JSON mode: off")
            else:
                print(f"Invalid value: {value}. Use 'on' or 'off'.")

        elif option == "max-chars":
            if not value:
                chars = self.state.max_chars or "unlimited"
                print(f"Max chars: {chars}")
            else:
                try:
                    n = int(value)
                    self.state.max_chars = n if n > 0 else None
                    print(f"Max chars set to: {self.state.max_chars or 'unlimited'}")
                except ValueError:
                    print(f"Invalid number: {value}")

        elif option == "chunk-size":
            if not value:
                print(f"Chunk size: {self.state.chunk_size} words")
            else:
                try:
                    n = int(value)
                    if n > 0:
                        self.state.chunk_size = n
                        print(f"Chunk size set to: {n} words")
                    else:
                        print("Chunk size must be positive.")
                except ValueError:
                    print(f"Invalid number: {value}")

        elif option == "strategy":
            valid_strategies = ["auto", "semantic", "fixed"]
            if not value:
                print(f"Chunking strategy: {self.state.chunk_strategy}")
                print(f"Valid strategies: {', '.join(valid_strategies)}")
            elif value.lower() in valid_strategies:
                self.state.chunk_strategy = value.lower()
                print(f"Chunking strategy set to: {value.lower()}")
            else:
                print(f"Invalid strategy: {value}")
                print(f"Valid strategies: {', '.join(valid_strategies)}")

        elif option == "template":
            if not value:
                template = self.state.template_path or "not set"
                print(f"Template: {template}")
            else:
                template_path = Path(value).expanduser().resolve()
                if template_path.exists():
                    self.state.template_path = str(template_path)
                    print(f"Template set to: {template_path}")
                else:
                    print(f"Template file not found: {template_path}")

        else:
            print(f"Unknown option: {option}")
            print("Use 'set' without arguments to see available options.")

    def _cmd_history(self, args: str) -> None:
        """Show files parsed this session."""
        if not self.state.history:
            print("No files parsed this session.")
            return

        print(f"\nFiles parsed this session ({len(self.state.history)}):")
        print("-" * 40)
        for i, file_path in enumerate(self.state.history, 1):
            print(f"  {i}. {file_path}")
        print()

    def _cmd_status(self, args: str) -> None:
        """Show current session settings."""
        settings = self.state.to_dict()

        print("\nCurrent Settings:")
        print("-" * 40)
        print(f"  Output format:     {settings['output_format']}")
        print(f"  JSON mode:         {'on' if settings['json_mode'] else 'off'}")
        print(f"  Max chars:         {settings['max_chars'] or 'unlimited'}")
        print(f"  Chunk size:        {settings['chunk_size']} words")
        print(f"  Chunk strategy:    {settings['chunk_strategy']}")
        print(f"  Template:          {settings['template_path'] or 'not set'}")
        print(f"  Files parsed:      {settings['files_parsed']}")
        print()

    def _cmd_clear(self, args: str) -> None:
        """Clear the screen."""
        # Cross-platform clear
        os.system("cls" if os.name == "nt" else "clear")

    def _cmd_help(self, args: str) -> None:
        """Show help message."""
        help_text = """
Chomper Interactive Commands
=============================

Document Operations:
  parse <file>        Parse a document and display content
  metadata <file>     Display document metadata only
  chunk <file>        Split document into chunks
  formats             List all supported file formats

Settings:
  set format <name>   Set output format (text, json, csv, markdown, xml, template)
  set json on|off     Toggle JSON output mode
  set max-chars N     Set maximum output characters (0 = unlimited)
  set chunk-size N    Set words per chunk (default: 1000)
  set strategy <name> Set chunking strategy (auto, semantic, fixed)
  set template <path> Set Jinja2 template file
  status              Show current settings

Session:
  history             Show files parsed this session
  clear               Clear the screen
  help                Show this help message
  exit, quit, q       Exit the REPL

Tips:
  - Use Tab for command and file path completion
  - Use Up/Down arrows to navigate command history
  - Press Ctrl+C to cancel current input (not exit)
  - Press Ctrl+D to exit

Examples:
  chomper> parse ~/Documents/report.pdf
  chomper> set format json
  chomper> metadata ~/Documents/report.pdf
  chomper> set strategy semantic
  chomper> chunk ~/Documents/book.pdf
"""
        print(help_text)


def run_interactive(quiet: bool = False) -> int:
    """
    Run the interactive shell.

    Args:
        quiet: If True, suppress startup messages.

    Returns:
        Exit code (0 for success).
    """
    shell = InteractiveShell(quiet=quiet)
    return shell.run()
