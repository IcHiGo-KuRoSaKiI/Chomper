"""
Image Summary Helper using LangChain for multi-model support with Langfuse observability.
Integrates with Langfuse for prompt management, tracing, and performance monitoring.
"""
import base64
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
import time

from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate

# Langfuse integration using new prompt manager
try:
    from langfuse_helpers.prompt_manager import get_prompt_manager, setup_image_analysis_prompts
    from langfuse_helpers.observability import observe_function
    LANGFUSE_AVAILABLE = True
except ImportError:
    # Fallback if langfuse_helpers is not available
    def observe_function(name=None, **kwargs):
        def decorator(func):
            return func
        return decorator
    LANGFUSE_AVAILABLE = False

    def get_prompt_manager():
        return None

    def get_prompt(name, doc_type="default"):
        try:
            from .prompts.image_analysis_prompts import get_image_analysis_prompt
            return get_image_analysis_prompt(doc_type)
        except ImportError:
            return "Extract all text and meaningful information from this image."

logger = logging.getLogger(__name__)


class ImageSummaryHelper:
    """
    Helper class for image processing using LangChain with Langfuse observability.
    Supports multiple models, providers, and integrated prompt management.
    """

    def __init__(self,
                 model_provider: str = "openai",
                 model_name: Optional[str] = None,
                 config=None,
                 langfuse_enabled: bool = True):
        """
        Initialize the image summary helper with Langfuse integration.

        Args:
            model_provider: Provider to use ("openai", "anthropic", etc.)
            model_name: Specific model name (optional)
            config: Configuration object with Langfuse settings
            langfuse_enabled: Whether to use Langfuse for observability
        """
        self.model_provider = model_provider.lower()
        self.model_name = model_name
        self.config = config
        self.langfuse_enabled = langfuse_enabled and LANGFUSE_AVAILABLE

        # Initialize LangChain client
        self.client = self._initialize_client()

        # Langfuse integration is now handled through the prompt manager
        logger.info(f"🚀 ImageSummaryHelper initialized with Langfuse integration: {self.langfuse_enabled}")

        # Load prompts from centralized location (backward compatibility)
        self.prompts = self._load_prompts()

    def _initialize_client(self):
        """Initialize the LangChain client based on provider."""
        if self.model_provider == "openai":
            model_name = self.model_name or "gpt-4o-mini"
            return ChatOpenAI(
                model=model_name,
                temperature=0.1,
                max_tokens=4000
            )
        elif self.model_provider == "anthropic":
            model_name = self.model_name or "claude-3-sonnet-20240229"
            return ChatAnthropic(
                model=model_name,
                temperature=0.1,
                max_tokens=4000
            )
        else:
            raise ValueError(f"Unsupported model provider: {self.model_provider}")

    def _load_prompts(self) -> Dict[str, str]:
        """Load prompts using the new configuration-based Langfuse prompt manager."""
        try:
            prompt_manager = get_prompt_manager()
            
            # Use configuration-based approach - only request prompts that exist
            return {
                "default": prompt_manager.get_prompt_by_config("image_analysis", "default"),
                "pdf": prompt_manager.get_prompt_by_config("image_analysis", "pdf"),
                "docx": prompt_manager.get_prompt_by_config("image_analysis", "default"),  # Use default for docx
                "pptx": prompt_manager.get_prompt_by_config("image_analysis", "default")   # Use default for pptx
            }
        except Exception as e:
            logger.error(f"Failed to load prompts from Langfuse manager: {e}")
            # Ultimate fallback - no local prompt dependencies
            fallback_prompt = "Extract all text and meaningful information from this image."
            return {
                "default": fallback_prompt,
                "pdf": fallback_prompt,
                "docx": fallback_prompt,
                "pptx": fallback_prompt
            }
    
    @observe_function(name="image_processing")
    def process_image(self,
                     image_data: str,
                     prompt_type: str = "default") -> str:
        """
        Process an image using LangChain client and centralized prompts with Langfuse observability.

        Args:
            image_data: Base64-encoded image data or data URI
            prompt_type: Type of prompt to use ("default", "pdf", "docx", "pptx")

        Returns:
            Extracted text from the image
        """
        start_time = time.time()
        processing_metadata = {
            "model_provider": self.model_provider,
            "model_name": self.model_name,
            "prompt_type": prompt_type,
            "langfuse_enabled": self.langfuse_enabled
        }

        try:
            # Ensure image_data is properly formatted
            if not image_data.startswith("data:"):
                image_data = f"data:image/jpeg;base64,{image_data}"

            # Get the prompt using the centralized Langfuse manager
            prompt = self.prompts.get(prompt_type, self.prompts["default"])
            processing_metadata["prompt_source"] = "langfuse" if self.langfuse_enabled else "local"

            # Create the message
            message = HumanMessage(
                content=[
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_data,
                            "detail": "high"
                        }
                    }
                ]
            )

            # Process with LangChain client
            response = self.client.invoke([message])

            # Extract and clean the response
            raw_text = response.content
            cleaned_text = self._clean_extracted_text(raw_text)

            # Calculate processing metrics
            processing_time = time.time() - start_time
            processing_metadata.update({
                "processing_time_seconds": processing_time,
                "output_length": len(cleaned_text),
                "success": True
            })

            # Log additional metrics if available
            if hasattr(response, 'response_metadata'):
                token_usage = response.response_metadata.get('token_usage', {})
                if token_usage:
                    processing_metadata.update({
                        "input_tokens": token_usage.get('prompt_tokens', 0),
                        "output_tokens": token_usage.get('completion_tokens', 0),
                        "total_tokens": token_usage.get('total_tokens', 0)
                    })

            logger.info(f"Successfully processed image using {self.model_provider} {self.model_name} in {processing_time:.2f}s")

            # Log to Langfuse if available
            if self.langfuse_enabled:
                try:
                    # Add metadata to current trace context (handled by @observe decorator)
                    pass
                except Exception as langfuse_error:
                    logger.debug(f"Langfuse logging failed: {langfuse_error}")

            return cleaned_text

        except Exception as e:
            processing_time = time.time() - start_time
            processing_metadata.update({
                "processing_time_seconds": processing_time,
                "success": False,
                "error": str(e)
            })

            logger.error(f"Error processing image with {self.model_provider}: {str(e)}")

            # Log error to Langfuse if available
            if self.langfuse_enabled:
                try:
                    # Error will be captured by @observe decorator
                    pass
                except Exception as langfuse_error:
                    logger.debug(f"Langfuse error logging failed: {langfuse_error}")

            return f"[Image processing failed: {str(e)}]"
    
    def _clean_extracted_text(self, text: str) -> str:
        """Clean extracted text from model responses."""
        if not text:
            return ""
        
        # Remove common artifacts
        text = text.strip()
        
        # Remove empty responses
        if text.lower() in ["empty response", "no content", "no text found", "no relevant content"]:
            return ""
        
        # Remove common prefixes
        prefixes_to_remove = [
            "Based on the image, ",
            "Looking at this image, ",
            "From the image, ",
            "The image shows ",
            "In this image, "
        ]
        
        for prefix in prefixes_to_remove:
            if text.startswith(prefix):
                text = text[len(prefix):]
                break
        
        return text
    
    def switch_model(self, provider: str, model_name: Optional[str] = None):
        """Switch to a different model provider."""
        self.model_provider = provider.lower()
        self.model_name = model_name
        self.client = self._initialize_client()
        logger.info(f"Switched to {provider} model: {model_name or 'default'}")
    
    def get_available_models(self) -> Dict[str, list]:
        """Get available models for each provider."""
        return {
            "openai": [
                "gpt-4o",
                "gpt-4o-mini", 
                "gpt-4-turbo",
                "gpt-4-vision-preview"
            ],
            "anthropic": [
                "claude-3-opus-20240229",
                "claude-3-sonnet-20240229",
                "claude-3-haiku-20240307"
            ]
        }
    
    
    @observe_function(name="batch_image_processing")
    def process_multiple_images(self,
                               image_batch: List[Dict[str, Any]],
                               prompt_type: str = "default") -> List[str]:
        """
        Process multiple images in a single API call with Langfuse observability.

        Args:
            image_batch: List of dicts with 'image_data' and 'index' keys
            prompt_type: Type of prompt to use ("default", "pdf", "docx", "pptx")

        Returns:
            List of extracted texts in the same order as input
        """
        start_time = time.time()
        batch_size = len(image_batch)
        processing_metadata = {
            "model_provider": self.model_provider,
            "model_name": self.model_name,
            "prompt_type": prompt_type,
            "batch_size": batch_size,
            "langfuse_enabled": self.langfuse_enabled
        }

        try:
            if not image_batch:
                return []

            # Get the prompt using the centralized Langfuse manager
            base_prompt = self.prompts.get(prompt_type, self.prompts["default"])
            processing_metadata["prompt_source"] = "langfuse" if self.langfuse_enabled else "local"

            # Modify prompt for multiple images
            prompt = f"""Process the following {batch_size} images and extract text from each.

{base_prompt}

For each image, provide the extracted text. Separate each image's result with "---IMAGE_SEPARATOR---" so I can map them back correctly."""

            # Build content array with text prompt and all images
            content = [{"type": "text", "text": prompt}]

            for i, item in enumerate(image_batch):
                image_data = item['image_data']
                # Ensure proper format
                if not image_data.startswith("data:"):
                    image_data = f"data:image/png;base64,{image_data}"

                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": image_data,
                        "detail": "high"
                    }
                })

            # Create the message
            message = HumanMessage(content=content)

            # Process with LangChain client
            response = self.client.invoke([message])

            # Parse the response to extract individual results
            raw_text = response.content
            individual_results = self._parse_batch_response(raw_text, batch_size)

            # Calculate processing metrics
            processing_time = time.time() - start_time
            processing_metadata.update({
                "processing_time_seconds": processing_time,
                "average_time_per_image": processing_time / batch_size if batch_size > 0 else 0,
                "total_output_length": sum(len(result) for result in individual_results),
                "success": True,
                "results_count": len(individual_results)
            })

            # Log additional metrics if available
            if hasattr(response, 'response_metadata'):
                token_usage = response.response_metadata.get('token_usage', {})
                if token_usage:
                    processing_metadata.update({
                        "input_tokens": token_usage.get('prompt_tokens', 0),
                        "output_tokens": token_usage.get('completion_tokens', 0),
                        "total_tokens": token_usage.get('total_tokens', 0),
                        "tokens_per_image": token_usage.get('total_tokens', 0) / batch_size if batch_size > 0 else 0
                    })

            logger.info(f"Successfully processed batch of {batch_size} images using {self.model_provider} in {processing_time:.2f}s")
            return individual_results

        except Exception as e:
            processing_time = time.time() - start_time
            processing_metadata.update({
                "processing_time_seconds": processing_time,
                "success": False,
                "error": str(e),
                "batch_size": batch_size
            })

            logger.error(f"Error processing image batch with {self.model_provider}: {str(e)}")

            # Log error to Langfuse if available
            if self.langfuse_enabled:
                try:
                    # Error will be captured by @observe decorator
                    pass
                except Exception as langfuse_error:
                    logger.debug(f"Langfuse error logging failed: {langfuse_error}")

            # Return error placeholders for each image
            return [f"[Image processing failed: {str(e)}]" for _ in image_batch]
    
    def _parse_batch_response(self, response_text: str, expected_count: int) -> List[str]:
        """Parse batch response text into individual image results."""
        if not response_text:
            return ["" for _ in range(expected_count)]
        
        # Split by separator if present
        if "---IMAGE_SEPARATOR---" in response_text:
            parts = response_text.split("---IMAGE_SEPARATOR---")
            results = [part.strip() for part in parts if part.strip()]
        else:
            # Fallback: try to split by numbered sections or similar patterns
            parts = []
            # Look for patterns like "1.", "Image 1:", etc.
            import re
            numbered_sections = re.split(r'\n(?=\d+\.|\bImage\s+\d+:)', response_text)
            if len(numbered_sections) > 1:
                parts = [section.strip() for section in numbered_sections if section.strip()]
            else:
                # If no clear separation, return the whole response for the first image
                parts = [response_text.strip()]
        
        # Clean each result
        cleaned_results = []
        for part in parts:
            cleaned = self._clean_extracted_text(part)
            cleaned_results.append(cleaned)
        
        # Ensure we have the right number of results
        while len(cleaned_results) < expected_count:
            cleaned_results.append("")
        
        return cleaned_results[:expected_count]
    


# Factory function for easy creation
def create_image_helper(provider: str = "openai", model: Optional[str] = None) -> ImageSummaryHelper:
    """Create an ImageSummaryHelper instance."""
    return ImageSummaryHelper(provider, model)

