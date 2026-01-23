"""
MCP Prompt definitions for document analysis.

These prompts provide reusable templates for common document analysis tasks.
Users can select these prompts to get pre-configured analysis workflows.
"""
from typing import Any

# Prompt definitions
PROMPTS: dict[str, dict[str, Any]] = {
    "summarize-document": {
        "name": "summarize-document",
        "description": "Generate a comprehensive summary of the document",
        "arguments": [
            {
                "name": "file_path",
                "description": "Path to the document to summarize",
                "required": True
            },
            {
                "name": "length",
                "description": "Summary length: 'short' (1-2 paragraphs), 'medium' (3-5 paragraphs), 'long' (detailed)",
                "required": False
            }
        ],
        "template": """Please analyze and summarize the following document.

## Document Content

{document_content}

## Instructions

Provide a {length} summary that captures:
1. The main topic or purpose of the document
2. Key points and findings
3. Important details or data
4. Conclusions or recommendations (if any)

Format your summary in clear, readable paragraphs."""
    },

    "extract-key-points": {
        "name": "extract-key-points",
        "description": "Extract the main key points and takeaways from the document",
        "arguments": [
            {
                "name": "file_path",
                "description": "Path to the document",
                "required": True
            },
            {
                "name": "max_points",
                "description": "Maximum number of key points to extract (default: 10)",
                "required": False
            }
        ],
        "template": """Please analyze the following document and extract the key points.

## Document Content

{document_content}

## Instructions

Extract up to {max_points} key points from this document. For each point:
- State the key point clearly and concisely
- Provide brief context if needed
- Note any supporting evidence or data

Format as a numbered list with clear, actionable takeaways."""
    },

    "explain-document": {
        "name": "explain-document",
        "description": "Explain the document content in simple, accessible terms",
        "arguments": [
            {
                "name": "file_path",
                "description": "Path to the document",
                "required": True
            },
            {
                "name": "audience",
                "description": "Target audience: 'child' (very simple), 'general' (average reader), 'expert' (technical detail)",
                "required": False
            }
        ],
        "template": """Please explain the following document for a {audience} audience.

## Document Content

{document_content}

## Instructions

Explain this document's content in terms appropriate for a {audience} audience:
- Use appropriate vocabulary and complexity
- Break down complex concepts
- Use analogies or examples where helpful
- Highlight the most important information

Make the explanation clear, engaging, and easy to understand."""
    },

    "extract-entities": {
        "name": "extract-entities",
        "description": "Extract named entities (people, organizations, locations, dates, etc.) from the document",
        "arguments": [
            {
                "name": "file_path",
                "description": "Path to the document",
                "required": True
            },
            {
                "name": "entity_types",
                "description": "Comma-separated entity types to extract: 'people', 'organizations', 'locations', 'dates', 'numbers', 'all'",
                "required": False
            }
        ],
        "template": """Please extract named entities from the following document.

## Document Content

{document_content}

## Instructions

Extract the following types of entities: {entity_types}

For each entity found:
- Identify the entity type
- Provide the exact text from the document
- Note any relevant context

Format as organized lists grouped by entity type."""
    },

    "document-qa": {
        "name": "document-qa",
        "description": "Set up a Q&A context for asking questions about the document",
        "arguments": [
            {
                "name": "file_path",
                "description": "Path to the document",
                "required": True
            }
        ],
        "template": """I have loaded the following document for you to answer questions about.

## Document Information

**File:** {file_name}
**Type:** {doc_type}
**Size:** {word_count} words

## Document Content

{document_content}

## Instructions

I am ready to answer questions about this document. You can ask me:
- Specific questions about the content
- Clarifications on any section
- Comparisons or analysis requests
- Requests to find specific information

What would you like to know about this document?"""
    },
}


def get_prompt_template(name: str) -> dict[str, Any]:
    """Get a prompt definition by name."""
    return PROMPTS.get(name)


def list_prompts() -> list[dict[str, Any]]:
    """Get list of all available prompts."""
    return [
        {
            "name": p["name"],
            "description": p["description"],
            "arguments": p["arguments"]
        }
        for p in PROMPTS.values()
    ]


def format_prompt(
    name: str,
    document_content: str,
    file_name: str = "",
    doc_type: str = "",
    word_count: int = 0,
    **kwargs
) -> str:
    """
    Format a prompt template with document content and arguments.

    Args:
        name: Prompt name
        document_content: Extracted document text
        file_name: Name of the document file
        doc_type: Document type/format
        word_count: Document word count
        **kwargs: Additional prompt-specific arguments

    Returns:
        Formatted prompt string
    """
    prompt_def = PROMPTS.get(name)
    if not prompt_def:
        raise ValueError(f"Unknown prompt: {name}")

    template = prompt_def["template"]

    # Set defaults for optional arguments
    defaults = {
        "length": "medium",
        "max_points": "10",
        "audience": "general",
        "entity_types": "all",
        "file_name": file_name,
        "doc_type": doc_type,
        "word_count": word_count,
        "document_content": document_content,
    }

    # Merge with provided kwargs
    format_args = {**defaults, **kwargs}

    # Format the template
    try:
        return template.format(**format_args)
    except KeyError as e:
        raise ValueError(f"Missing required argument for prompt '{name}': {e}") from e
