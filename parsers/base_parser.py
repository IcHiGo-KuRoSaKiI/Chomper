from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class BaseParser(ABC):
    """
    Abstract base class for document parsers.
    All specific parsers should inherit from this class.
    """
    
    def __init__(self, image_helper, ingester_logger=None):
        """
        Initialize the parser with common dependencies.
        
        Args:
            image_helper: ImageSummaryHelper for image processing
            ingester_logger: Optional logger for ingestion operations
        """
        self.image_helper = image_helper
        self.ingester_logger = ingester_logger
    
    @abstractmethod
    async def parse(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Parse the document at the specified file path.
        
        Args:
            file_path: Path to the document file
            
        Returns:
            List of dictionaries containing extracted content with page numbers
        """
        pass
    
    def clean_text(self, text: str) -> str:
        """
        Clean text by removing unnecessary formatting and standardizing punctuation.
        May be overridden by subclasses for format-specific cleaning.
        
        Args:
            text: Text to clean
            
        Returns:
            Cleaned text
        """
        return text.strip()
    
    def process_image_content(self, image_data: str, prompt_type: str = "default") -> str:
        """
        Process image content using the image helper.
        
        Args:
            image_data: Base64-encoded image data
            prompt_type: Type of prompt to use for processing
            
        Returns:
            Extracted text from the image
        """
        return self.image_helper.process_image(image_data, prompt_type)
    
    def log_success(self, file_path: str, operation_type: str = "parse"):
        """
        Log a successful operation if a logger is available.
        
        Args:
            file_path: Path to the processed file
            operation_type: Type of operation performed
        """
        if self.ingester_logger:
            self.ingester_logger.log_success(
                file_path=file_path,
                schema_name=f"{self.__class__.__name__.lower()}_documents",
                weaviate_uuid="temp_uuid",  # This should be replaced with actual UUID when integrated
                operation_type=operation_type
            )
    
    def log_failure(self, file_path: str, error: str, error_type: str):
        """
        Log a failed operation if a logger is available.
        
        Args:
            file_path: Path to the file that failed processing
            error: Error message
            error_type: Type of error that occurred
        """
        if self.ingester_logger:
            self.ingester_logger.log_failure(
                file_path=file_path,
                error=error,
                error_type=error_type
            )