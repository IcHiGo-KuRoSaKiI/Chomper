"""
Setup script for the parsers module.

Install with:
    pip install .              # Install package
    pip install -e .           # Install in development mode
    pip install -e ".[dev]"    # Install with dev dependencies
"""
from setuptools import setup, find_packages
from pathlib import Path

# Read README
readme_file = Path(__file__).parent / "README.md"
long_description = readme_file.read_text(encoding="utf-8") if readme_file.exists() else ""

# Read version
version = "2.0.0"  # Updated for Excel/CSV/HTML support

# Core dependencies (always required)
core_requirements = [
    "dataclasses-json>=0.6.0",
    "pydantic>=2.0.0",
    "nltk>=3.8.0",
    "python-magic>=0.4.27",
    "chardet>=5.2.0",
]

# PDF dependencies
pdf_requirements = [
    "pymupdf>=1.23.0",
    "pillow>=10.1.0",
]

# Office format dependencies (DOCX, PPTX)
office_requirements = [
    "python-docx>=1.1.0",
    "python-pptx>=0.6.23",
]

# Excel/CSV dependencies
excel_requirements = [
    "openpyxl>=3.1.2",
    "pandas>=2.1.0",
]

# HTML dependencies
html_requirements = [
    "beautifulsoup4>=4.12.0",
    "lxml>=5.0.0",
    "trafilatura>=1.6.0",
]

# NLP dependencies (advanced features)
nlp_requirements = [
    "spacy>=3.7.0",
]

# All format dependencies
all_requirements = (
    core_requirements +
    pdf_requirements +
    office_requirements +
    excel_requirements +
    html_requirements +
    nlp_requirements
)

# Development dependencies
dev_requirements = [
    "pytest>=7.4.3",
    "pytest-cov>=4.1.0",
    "black>=23.12.0",
    "flake8>=6.1.0",
    "mypy>=1.7.0",
]

setup(
    name="parsers",
    version=version,
    description="Professional document parsing module supporting 9 formats: PDF, DOCX, PPTX, Code, Text, Markdown, Excel, CSV, HTML",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Your Name",
    author_email="your.email@example.com",
    url="https://github.com/yourusername/parsers",
    packages=find_packages(exclude=["tests", "examples"]),
    python_requires=">=3.9",

    # Installation options
    install_requires=core_requirements,  # Minimal by default

    extras_require={
        # Install specific format support
        "pdf": pdf_requirements,
        "office": office_requirements,
        "excel": excel_requirements,
        "html": html_requirements,
        "nlp": nlp_requirements,

        # Install all formats
        "all": all_requirements,

        # Development dependencies
        "dev": dev_requirements + all_requirements,
    },

    # Package metadata
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Text Processing :: General",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    keywords="parsing document pdf docx pptx excel csv html markdown nlp rag",

    # Include package data
    include_package_data=True,
    zip_safe=False,
)
