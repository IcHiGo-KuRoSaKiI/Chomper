"""
Centralized image analysis prompts for all parsers - MINIMAL FALLBACK VERSION
"""

# Simple fallback prompt when Langfuse is not available
FALLBACK_PROMPT = """Extract all text and meaningful information from this image. Focus on:
1. All visible text (titles, labels, annotations)
2. Chart data and values if present
3. Key visual elements and their relationships
4. Main insights or patterns shown

Format your response clearly with appropriate headings."""


def get_image_analysis_prompt(document_type: str = "default") -> str:
    """
    Simple fallback function for when Langfuse prompts are not available.

    Args:
        document_type: Type of document ("pdf", "docx", "pptx", "default")

    Returns:
        Fallback prompt text
    """
    return FALLBACK_PROMPT
