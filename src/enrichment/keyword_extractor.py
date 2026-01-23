"""
Keyword extraction enricher.

Extracts important keywords from chunks using:
- TF-IDF (Term Frequency-Inverse Document Frequency)
- RAKE (Rapid Automatic Keyword Extraction)
"""
import re
from collections import Counter

from ..models.document import Chunk, EnrichedChunk
from .base import BaseEnricher


class KeywordExtractor(BaseEnricher):
    """
    Extract keywords from chunks.

    Supports two methods:
    - tfidf: Statistical keyword extraction (requires sklearn)
    - rake: Regex-based keyword extraction (no dependencies)
    """

    def __init__(self, method: str = "rake", top_k: int = 5):
        """
        Initialize keyword extractor.

        Args:
            method: "tfidf" or "rake"
            top_k: Number of top keywords to extract
        """
        self.method = method.lower()
        self.top_k = top_k

        if self.method not in ["tfidf", "rake"]:
            raise ValueError(f"Unknown method: {method}. Use 'tfidf' or 'rake'")

    def enrich(self, chunks: list[Chunk]) -> list[EnrichedChunk]:
        """
        Extract keywords from chunks.

        Args:
            chunks: List of chunks to enrich

        Returns:
            List of enriched chunks with keywords
        """
        enriched_chunks = []

        for chunk in chunks:
            enriched = self._chunk_to_enriched(chunk)

            # Skip code chunks or very short chunks
            if self._should_skip_chunk(chunk):
                enriched_chunks.append(enriched)
                continue

            # Extract keywords
            if self.method == "rake":
                keywords = self._rake_keywords(chunk.text)
            else:  # tfidf
                keywords = self._tfidf_keywords([chunk.text])

            enriched.keywords = keywords[:self.top_k]
            enriched_chunks.append(enriched)

        return enriched_chunks

    def _rake_keywords(self, text: str) -> list[str]:
        """
        RAKE (Rapid Automatic Keyword Extraction) - regex-based.

        Algorithm:
        1. Split text by stopwords and punctuation
        2. Calculate word scores (degree/frequency)
        3. Combine adjacent words into phrases
        4. Rank phrases by score

        Args:
            text: Text to extract keywords from

        Returns:
            List of keywords (phrases)
        """
        # Simple stopwords (extend this list as needed)
        stopwords = {
            'a', 'about', 'above', 'after', 'again', 'against', 'all', 'am', 'an', 'and',
            'any', 'are', 'as', 'at', 'be', 'because', 'been', 'before', 'being', 'below',
            'between', 'both', 'but', 'by', 'could', 'did', 'do', 'does', 'doing', 'down',
            'during', 'each', 'few', 'for', 'from', 'further', 'had', 'has', 'have',
            'having', 'he', 'her', 'here', 'hers', 'herself', 'him', 'himself', 'his',
            'how', 'i', 'if', 'in', 'into', 'is', 'it', 'its', 'itself', 'just', 'me',
            'might', 'more', 'most', 'must', 'my', 'myself', 'no', 'nor', 'not', 'now',
            'of', 'off', 'on', 'once', 'only', 'or', 'other', 'our', 'ours', 'ourselves',
            'out', 'over', 'own', 'same', 'she', 'should', 'so', 'some', 'such', 'than',
            'that', 'the', 'their', 'theirs', 'them', 'themselves', 'then', 'there',
            'these', 'they', 'this', 'those', 'through', 'to', 'too', 'under', 'until',
            'up', 'very', 'was', 'we', 'were', 'what', 'when', 'where', 'which', 'while',
            'who', 'whom', 'why', 'will', 'with', 'would', 'you', 'your', 'yours',
            'yourself', 'yourselves'
        }

        # Convert to lowercase and split into sentences
        text = text.lower()
        sentences = re.split(r'[.!?;]', text)

        # Extract candidate phrases (split by stopwords/punctuation)
        candidates = []
        for sentence in sentences:
            # Split by stopwords and non-word characters
            words = re.findall(r'\b[a-z]+\b', sentence)
            phrase = []

            for word in words:
                if word in stopwords or len(word) < 3:
                    if phrase:
                        candidates.append(' '.join(phrase))
                        phrase = []
                else:
                    phrase.append(word)

            if phrase:
                candidates.append(' '.join(phrase))

        # Calculate word frequencies and degrees
        word_freq = Counter()
        word_degree = Counter()

        for candidate in candidates:
            words = candidate.split()
            degree = len(words) - 1

            for word in words:
                word_freq[word] += 1
                word_degree[word] += degree

        # Calculate phrase scores
        phrase_scores = {}
        for candidate in candidates:
            words = candidate.split()
            score = sum(word_degree[w] / word_freq[w] if word_freq[w] > 0 else 0 for w in words)
            phrase_scores[candidate] = score

        # Sort by score and return top phrases
        sorted_phrases = sorted(phrase_scores.items(), key=lambda x: x[1], reverse=True)
        return [phrase for phrase, score in sorted_phrases if len(phrase.split()) <= 4]

    def _tfidf_keywords(self, texts: list[str]) -> list[str]:
        """
        TF-IDF keyword extraction using sklearn.

        Args:
            texts: List of texts (usually one chunk text)

        Returns:
            List of keywords
        """
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
        except ImportError:
            # Fallback to RAKE if sklearn not available
            return self._rake_keywords(texts[0] if texts else "")

        # Create TF-IDF vectorizer
        vectorizer = TfidfVectorizer(
            max_features=50,
            stop_words='english',
            ngram_range=(1, 3),  # Unigrams, bigrams, trigrams
            min_df=1
        )

        try:
            # Fit and transform
            tfidf_matrix = vectorizer.fit_transform(texts)
            feature_names = vectorizer.get_feature_names_out()

            # Get scores for first document
            scores = tfidf_matrix[0].toarray()[0]

            # Sort by score
            top_indices = scores.argsort()[-self.top_k:][::-1]
            keywords = [feature_names[i] for i in top_indices if scores[i] > 0]

            return keywords
        except Exception:
            # Fallback to RAKE on error
            return self._rake_keywords(texts[0] if texts else "")
