import logging
from services.extraction.extractor_interface import EntityExtractor
from services.extraction.llm_extractor import LLMEntityExtractor
from services.extraction.regex_extractor import RegexEntityExtractor

# Configure logger
logger = logging.getLogger(__name__)


class ExtractorFactory:
    """Factory for creating entity extractors"""

    @staticmethod
    def create_extractor(extractor_type: str = "llm") -> EntityExtractor:
        """
        Create and return an entity extractor based on the specified type

        Args:
            extractor_type: Type of extractor to create ("llm", "regex", or "hybrid")

        Returns:
            An entity extractor instance
        """
        if extractor_type == "regex":
            logger.info("Creating regex extractor")
            return RegexEntityExtractor()

        elif extractor_type == "llm":
            logger.info("Creating LLM extractor")
            return LLMEntityExtractor()

        elif extractor_type == "hybrid":
            logger.info("Creating hybrid extractor (LLM with regex fallback)")
            regex_extractor = RegexEntityExtractor()
            return LLMEntityExtractor(fallback_extractor=regex_extractor)

        else:
            logger.warning(f"Unknown extractor type: {extractor_type}, defaulting to hybrid")
            regex_extractor = RegexEntityExtractor()
            return LLMEntityExtractor(fallback_extractor=regex_extractor)