"""
Backwards compatibility shim for old ParserFactory.

Redirects old imports to new integration adapter.
This keeps knowledge_backbone working while using the new modular parser system.
"""
from parsers.integration import ParserFactoryAdapter


class ParserFactory:
    """
    Backwards-compatible factory that wraps the new modular parser system.

    Maintains the same API as the old factory while using new DocumentPipeline internally.
    """

    @classmethod
    def create_parser(cls, file_path: str, image_helper=None, ingester_logger=None):
        """
        Create parser for file (backwards compatible).

        Args:
            file_path: Path to file
            image_helper: Image helper (ignored in new system)
            ingester_logger: Logger (ignored in new system)

        Returns:
            Parser instance
        """
        return ParserFactoryAdapter.create_parser(file_path, image_helper)

    @classmethod
    def create_image_helper(cls, provider: str = "openai", model: str = None, config=None):
        """
        Create image helper (backwards compatible).

        Returns the old ImageSummaryHelper for compatibility.

        Args:
            provider: Model provider
            model: Model name
            config: Config object

        Returns:
            ImageSummaryHelper instance
        """
        # Import old helper for compatibility
        try:
            import sys
            import os
            parsers_old_path = os.path.join(os.path.dirname(__file__), '..', 'parsers_old')
            if parsers_old_path not in sys.path:
                sys.path.insert(0, parsers_old_path)

            from image_summary_helper import ImageSummaryHelper
            return ImageSummaryHelper(provider, model, config=config)
        except ImportError:
            # Fallback if parsers_old not available
            return None

    @classmethod
    def get_supported_extensions(cls):
        """
        Get supported file extensions.

        Returns:
            List of extensions
        """
        return ParserFactoryAdapter.get_supported_formats()

    @classmethod
    def register_parser(cls, extension: str, parser_class, is_fallback: bool = False):
        """
        Register parser (compatibility stub).

        Note: Not implemented in new system - parsers are auto-detected.
        """
        pass


__all__ = ['ParserFactory']
