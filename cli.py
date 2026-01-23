#!/usr/bin/env python3
"""
Chomper CLI - Command-line document parsing.

Usage:
    chomper-parse file.pdf                    # Parse and print text
    chomper-parse file.pdf --json             # Output as JSON
    chomper-parse file.pdf --format markdown  # Output as Markdown
    chomper-parse file.pdf --format csv       # Output as CSV
    chomper-parse file.pdf --format xml       # Output as XML
    chomper-parse file.pdf --format template --template my.j2  # Custom template
    chomper-parse file.pdf --metadata         # Show metadata only
    chomper-parse file.pdf --chunk            # Split into chunks
    chomper-parse file.pdf -o output.txt      # Save to file
    chomper-parse --formats                   # List supported formats

Watch Mode:
    chomper-parse --watch ./documents                    # Watch directory
    chomper-parse --watch ./inbox --format json          # Watch with JSON output
    chomper-parse --watch ./docs --pattern "*.pdf"       # Watch only PDFs
    chomper-parse --watch ./docs --output-dir ./parsed   # Save to directory
    chomper-parse --watch ./project --recursive          # Watch subdirectories

Interactive Mode:
    chomper-parse -i                                     # Start interactive REPL
    chomper-parse --interactive                          # Same as above
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Version
__version__ = "1.0.0"

# Valid output formats
OUTPUT_FORMATS = ["text", "json", "csv", "markdown", "xml", "template"]


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="chomper-parse",
        description="Chomp through any document - parse 36+ file formats from the command line.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  chomper-parse document.pdf                Parse PDF and print text
  chomper-parse report.docx --json          Output as JSON
  chomper-parse report.docx -f json         Output as JSON (alternative)
  chomper-parse report.docx -f markdown     Output as Markdown
  chomper-parse report.docx -f csv          Output as CSV
  chomper-parse report.docx -f xml          Output as XML
  chomper-parse doc.pdf -f template -t t.j2 Use custom Jinja2 template
  chomper-parse data.xlsx --metadata        Show metadata only
  chomper-parse book.pdf --chunk            Split into chunks
  chomper-parse file.pdf -o out.txt         Save output to file
  chomper-parse --formats                   List all supported formats

Watch Mode Examples:
  chomper-parse -w ./documents              Watch directory for changes
  chomper-parse -w ./inbox --format json    Watch with JSON output
  chomper-parse -w ./docs --pattern "*.pdf" Watch only PDF files
  chomper-parse -w ./docs --output-dir ./out Save output to directory
  chomper-parse -w ./project --recursive    Watch subdirectories

Interactive Mode Examples:
  chomper-parse -i                          Start interactive REPL
  chomper-parse --interactive               Same as -i

Output Formats:
  text      Plain text output (default)
  json      JSON with metadata and content
  csv       CSV format (one row per document/chunk)
  markdown  Markdown with headers and tables
  xml       XML with proper element structure
  template  Custom Jinja2 template

For MCP server usage, run: chomper
For Python library usage: import chomper
        """,
    )

    parser.add_argument(
        "file",
        nargs="?",
        help="Path to the document to parse",
    )

    parser.add_argument(
        "-o", "--output",
        help="Output file path (default: stdout)",
    )

    # Output format options
    parser.add_argument(
        "-f", "--format",
        choices=OUTPUT_FORMATS,
        default="text",
        help="Output format (default: text). Options: text, json, csv, markdown, xml, template",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON (shortcut for --format json)",
    )

    parser.add_argument(
        "--template",
        metavar="FILE",
        help="Jinja2 template file (requires --format template)",
    )

    parser.add_argument(
        "--metadata",
        action="store_true",
        help="Show metadata only (no content)",
    )

    parser.add_argument(
        "--chunk",
        action="store_true",
        help="Split document into chunks",
    )

    parser.add_argument(
        "--chunk-size",
        type=int,
        default=1000,
        help="Target words per chunk (default: 1000)",
    )

    parser.add_argument(
        "--strategy",
        choices=["auto", "semantic", "fixed"],
        default="auto",
        help="Chunking strategy (default: auto)",
    )

    parser.add_argument(
        "--max-chars",
        type=int,
        help="Maximum characters to output",
    )

    parser.add_argument(
        "--formats",
        action="store_true",
        help="List all supported formats and exit",
    )

    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress progress messages",
    )

    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Start interactive REPL mode",
    )

    # Watch mode arguments
    watch_group = parser.add_argument_group("Watch Mode")
    watch_group.add_argument(
        "-w", "--watch",
        metavar="DIR",
        help="Watch directory for new/changed files",
    )
    watch_group.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Watch interval in seconds (default: 2)",
    )
    watch_group.add_argument(
        "--output-dir",
        metavar="DIR",
        help="Save parsed output to this directory (one file per document)",
    )
    watch_group.add_argument(
        "--pattern",
        help="File pattern to watch (e.g., '*.pdf' or '.pdf,.docx')",
    )
    watch_group.add_argument(
        "--recursive",
        action="store_true",
        help="Watch subdirectories",
    )

    return parser.parse_args()


def print_formats() -> None:
    """Print all supported formats."""
    import chomper

    formats = chomper.list_formats()

    print("Supported Document Formats:")
    print("=" * 60)

    # Group by availability
    available = {k: v for k, v in formats.items() if v["available"]}
    unavailable = {k: v for k, v in formats.items() if not v["available"]}

    print(f"\nAvailable ({len(available)} formats):")
    print("-" * 40)
    for ext, info in sorted(available.items()):
        print(f"  {ext:8} {info['description']}")

    if unavailable:
        print(f"\nUnavailable ({len(unavailable)} formats - install optional dependencies):")
        print("-" * 40)
        for ext, info in sorted(unavailable.items()):
            print(f"  {ext:8} {info['description']}")


def run_watch_mode(args: argparse.Namespace) -> int:
    """Run the CLI in watch mode."""
    from src.cli.formatters import get_formatter
    from src.cli.watcher import DirectoryWatcher, get_supported_extensions, parse_patterns

    watch_dir = Path(args.watch).expanduser().resolve()
    if not watch_dir.is_dir():
        print(f"Error: Not a directory: {watch_dir}", file=sys.stderr)
        return 1

    # Set up output directory if specified
    output_dir = None
    if args.output_dir:
        output_dir = Path(args.output_dir).expanduser().resolve()
        if not output_dir.exists():
            try:
                output_dir.mkdir(parents=True)
                if not args.quiet:
                    print(f"Created output directory: {output_dir}", file=sys.stderr)
            except OSError as e:
                print(f"Error: Cannot create output directory: {e}", file=sys.stderr)
                return 1
        elif not output_dir.is_dir():
            print(f"Error: Output path is not a directory: {output_dir}", file=sys.stderr)
            return 1

    # Get patterns to watch
    if args.pattern:
        patterns = parse_patterns(args.pattern)
    else:
        # Default to all supported formats
        patterns = get_supported_extensions()

    # Determine output format
    output_format = args.format
    if args.json:
        output_format = "json"

    # Validate template if needed
    if output_format == "template" and not args.template:
        print("Error: --template FILE is required when using --format template", file=sys.stderr)
        return 1

    # Get formatter
    try:
        formatter = get_formatter(
            output_format,
            template_path=args.template,
            max_chars=args.max_chars,
        )
    except (ValueError, ImportError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Import chomper for parsing
    import chomper

    # File extension for output files
    format_extensions = {
        "text": ".txt",
        "json": ".json",
        "csv": ".csv",
        "markdown": ".md",
        "xml": ".xml",
        "template": ".txt",
    }
    output_ext = format_extensions.get(output_format, ".txt")

    def process_file(file_path: Path) -> None:
        """Parse a file and output the result."""
        try:
            # Check if format is supported
            if not chomper.is_supported(file_path):
                if not args.quiet:
                    print(f"Skipping unsupported format: {file_path}", file=sys.stderr)
                return

            # Parse the document
            if args.metadata:
                meta = chomper.extract_metadata(file_path)
                output_text = formatter.format_metadata(meta)
            elif args.chunk:
                chunks = chomper.chunk(
                    file_path,
                    strategy=args.strategy,
                    chunk_size=args.chunk_size,
                )
                output_text = formatter.format_chunks(chunks, str(file_path), args.strategy)
            else:
                result = chomper.parse(file_path, max_chars=args.max_chars)
                output_text = formatter.format_parse_result(result)

            # Output the result
            if output_dir:
                # Save to output directory
                output_filename = file_path.stem + output_ext
                output_path = output_dir / output_filename

                # Handle duplicate filenames
                counter = 1
                while output_path.exists():
                    output_filename = f"{file_path.stem}_{counter}{output_ext}"
                    output_path = output_dir / output_filename
                    counter += 1

                output_path.write_text(output_text)
                if not args.quiet:
                    print(f"Saved: {output_path}", file=sys.stderr)
            else:
                # Print to stdout
                print(f"\n{'=' * 60}")
                print(f"File: {file_path}")
                print("=" * 60)
                print(output_text)

        except chomper.ChomperError as e:
            print(f"Error parsing {file_path}: {e}", file=sys.stderr)
        except Exception as e:
            print(f"Unexpected error parsing {file_path}: {e}", file=sys.stderr)

    # Create and start watcher
    watcher = DirectoryWatcher(
        directory=watch_dir,
        callback=process_file,
        interval=args.interval,
        patterns=patterns,
        recursive=args.recursive,
        quiet=args.quiet,
    )

    if not args.quiet:
        print(f"Watching: {watch_dir}", file=sys.stderr)
        if args.recursive:
            print("Mode: Recursive (including subdirectories)", file=sys.stderr)
        if patterns:
            pattern_list = ", ".join(sorted(patterns)[:10])
            if len(patterns) > 10:
                pattern_list += f", ... ({len(patterns)} total)"
            print(f"Patterns: {pattern_list}", file=sys.stderr)
        if output_dir:
            print(f"Output: {output_dir}", file=sys.stderr)
        print("Press Ctrl+C to stop\n", file=sys.stderr)

    try:
        watcher.start()
    except KeyboardInterrupt:
        pass  # Handled by watcher's signal handler

    return 0


def main() -> int:
    """Main CLI entry point."""
    args = parse_args()

    # Handle --formats flag
    if args.formats:
        print_formats()
        return 0

    # Handle watch mode
    if args.watch:
        return run_watch_mode(args)

    # Handle interactive mode
    if args.interactive:
        from src.cli.interactive import run_interactive
        return run_interactive(quiet=args.quiet)

    # Require file argument for parsing
    if not args.file:
        print("Error: Please specify a file to parse.", file=sys.stderr)
        print("Usage: chomper-parse <file> [options]", file=sys.stderr)
        print("       chomper-parse --formats", file=sys.stderr)
        return 1

    # Validate file exists
    file_path = Path(args.file).expanduser().resolve()
    if not file_path.exists():
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        return 1

    # Import chomper here to avoid slow startup for --help/--formats
    import chomper

    # Check format is supported
    if not chomper.is_supported(file_path):
        print(f"Error: Unsupported file format: {file_path.suffix}", file=sys.stderr)
        print("Run 'chomper-parse --formats' to see supported formats.", file=sys.stderr)
        return 1

    # Determine output format (--json is shortcut for --format json)
    output_format = args.format
    if args.json:
        output_format = "json"

    # Validate template requirement
    if output_format == "template" and not args.template:
        print("Error: --template FILE is required when using --format template", file=sys.stderr)
        return 1

    # Validate template file exists if specified
    if args.template:
        template_path = Path(args.template).expanduser().resolve()
        if not template_path.exists():
            print(f"Error: Template file not found: {template_path}", file=sys.stderr)
            return 1

    try:
        # Import formatters
        from src.cli.formatters import get_formatter

        # Get the appropriate formatter
        formatter = get_formatter(
            output_format,
            template_path=args.template,
            max_chars=args.max_chars,
        )

        if args.metadata:
            # Metadata only
            if not args.quiet:
                print(f"Extracting metadata from: {file_path.name}", file=sys.stderr)

            meta = chomper.extract_metadata(file_path)
            output_text = formatter.format_metadata(meta)

        elif args.chunk:
            # Chunking mode
            if not args.quiet:
                print(f"Chunking: {file_path.name} (strategy: {args.strategy})", file=sys.stderr)

            chunks = chomper.chunk(
                file_path,
                strategy=args.strategy,
                chunk_size=args.chunk_size,
            )
            output_text = formatter.format_chunks(chunks, str(file_path), args.strategy)

        else:
            # Standard parsing
            if not args.quiet:
                print(f"Parsing: {file_path.name}", file=sys.stderr)

            result = chomper.parse(file_path, max_chars=args.max_chars)
            output_text = formatter.format_parse_result(result)

        # Output result
        if args.output:
            output_path = Path(args.output)
            output_path.write_text(output_text)
            if not args.quiet:
                print(f"Output saved to: {output_path}", file=sys.stderr)
        else:
            print(output_text)

        return 0

    except ImportError as e:
        print(f"Error: Missing dependency: {e}", file=sys.stderr)
        return 1
    except chomper.ChomperError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
