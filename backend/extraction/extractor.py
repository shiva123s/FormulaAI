"""
FormulaAI — Gemini-Powered Structured Extraction Engine

Uses Google Gemini 2.5 Pro via the google-generativeai SDK with
the Instructor library for Pydantic-validated structured outputs.

Architecture:
  1. Document text → Prompt builder (with few-shot examples)
  2. Prompt → Gemini 2.5 Pro (1M+ context window)
  3. Gemini response → Instructor validates against Pydantic schemas
  4. Validated ExtractionResult → downstream normalization + graph loading

CRITICAL: This module uses Google Gemini exclusively.
          OpenAI is NOT used anywhere in this pipeline.

The 1M+ token context window of Gemini 2.5 Pro allows processing
full agrochemical patents without chunking — a major advantage over
smaller-context models.
"""

from __future__ import annotations

import logging
from typing import Any

from config import get_settings
from extraction.schemas import (
    ExtractionResult,
    ExtractedCompound,
    ExtractedRelationship,
)
from extraction.prompts import (
    build_extraction_prompt,
    build_table_extraction_prompt,
)
from ingestion.base import RawDocument
from parsing.pdf_parser import ParsedDocument

logger = logging.getLogger(__name__)

# ── Conditional imports ──────────────────────────────────────────────────────

try:
    import google.generativeai as genai

    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logger.warning(
        "google-generativeai is not installed. LLM extraction unavailable. "
        "Install with: pip install google-generativeai"
    )

try:
    import instructor

    INSTRUCTOR_AVAILABLE = True
except ImportError:
    INSTRUCTOR_AVAILABLE = False
    logger.warning(
        "instructor is not installed. Structured output validation unavailable. "
        "Install with: pip install instructor"
    )


class GeminiExtractor:
    """
    Structured data extraction engine powered by Google Gemini.

    Uses the Instructor library to enforce Pydantic schema validation
    on Gemini's JSON output, ensuring every extraction result matches
    our strict agrochemical data models.

    Usage:
        extractor = GeminiExtractor()
        result = await extractor.extract_from_document(parsed_doc, source_id, "patent")
        print(result.total_entities, result.total_relationships)

    Or for batch processing:
        results = await extractor.extract_batch(raw_documents)
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str | None = None,
        temperature: float = 0.1,
        max_retries: int = 3,
    ):
        settings = get_settings()
        self._api_key = api_key or settings.google_api_key
        self._model_name = model_name or settings.gemini_model_name
        self._temperature = temperature
        self._max_retries = max_retries
        self._client = None
        self._model = None

        if not self._api_key:
            logger.error(
                "GOOGLE_API_KEY is not set. LLM extraction will not work. "
                "Set it in your .env file."
            )
            return

        if not GEMINI_AVAILABLE:
            logger.error("google-generativeai SDK is not installed.")
            return

        self._initialize_client()

    def _initialize_client(self) -> None:
        """Initialize the Gemini client with Instructor wrapper."""
        genai.configure(api_key=self._api_key)

        self._model = genai.GenerativeModel(
            model_name=self._model_name,
            generation_config=genai.GenerationConfig(
                temperature=self._temperature,
                response_mime_type="application/json",
            ),
        )

        if INSTRUCTOR_AVAILABLE:
            self._client = instructor.from_gemini(
                client=self._model,
                mode=instructor.Mode.GEMINI_JSON,
            )
            logger.info(
                "Gemini extractor initialized: model=%s, instructor=enabled",
                self._model_name,
            )
        else:
            logger.info(
                "Gemini extractor initialized: model=%s, instructor=disabled (raw JSON)",
                self._model_name,
            )

    @property
    def is_available(self) -> bool:
        """Check if the extractor is properly configured."""
        return (
            GEMINI_AVAILABLE
            and bool(self._api_key)
            and self._model is not None
        )

    # ── Core Extraction Methods ──────────────────────────────────────────

    async def extract_from_document(
        self,
        document: ParsedDocument,
        source_id: str,
        source_type: str,
        max_text_length: int | None = None,
    ) -> ExtractionResult:
        """
        Extract entities and relationships from a parsed document.

        Uses Gemini's 1M+ context window to process the full document
        without chunking.

        Args:
            document: Parsed document (from PDFParser or API text).
            source_id: Document identifier (DOI, patent number, PMID).
            source_type: Type of document ("patent", "paper", etc.).
            max_text_length: Optional limit on text sent to LLM.

        Returns:
            ExtractionResult with all entities and relationships.
        """
        if not self.is_available:
            logger.warning("Extractor not available, returning empty result")
            return ExtractionResult(
                source_id=source_id, source_type=source_type
            )

        # Build the document text with inline tables
        doc_text = document.get_text_with_tables(max_length=max_text_length)

        if not doc_text.strip():
            logger.warning("Empty document text for %s", source_id)
            return ExtractionResult(
                source_id=source_id, source_type=source_type
            )

        # Build the prompt
        messages = build_extraction_prompt(doc_text, source_id, source_type)

        # Call Gemini
        result = await self._call_gemini(
            messages=messages,
            response_model=ExtractionResult,
            source_id=source_id,
        )

        if result is None:
            return ExtractionResult(
                source_id=source_id, source_type=source_type
            )

        logger.info(
            "Extracted from %s: %d entities, %d relationships (%d negative)",
            source_id,
            result.total_entities,
            result.total_relationships,
            result.negative_data_count,
        )
        return result

    async def extract_from_raw_document(
        self, raw_doc: RawDocument
    ) -> ExtractionResult:
        """
        Convenience method: extract from a RawDocument (ingestion output).

        Wraps the raw document's text into a ParsedDocument and extracts.
        """
        from parsing.pdf_parser import PDFParser

        parser = PDFParser()

        # Combine available text fields
        text_parts = []
        if raw_doc.title:
            text_parts.append(f"# {raw_doc.title}")
        if raw_doc.abstract:
            text_parts.append(f"## Abstract\n{raw_doc.abstract}")
        if raw_doc.full_text:
            text_parts.append(f"## Full Text\n{raw_doc.full_text}")

        combined_text = "\n\n".join(text_parts)
        parsed = parser.parse_text(combined_text, source_id=raw_doc.source_id)

        return await self.extract_from_document(
            document=parsed,
            source_id=raw_doc.source_id,
            source_type=raw_doc.source_type,
        )

    async def extract_from_table(
        self,
        table_markdown: str,
        table_context: str,
        source_id: str,
    ) -> ExtractionResult:
        """
        Extract entities and relationships from a single chemical table.

        Tables in patents contain the richest formulation data and
        deserve focused extraction with a specialized prompt.

        Args:
            table_markdown: Table in markdown format.
            table_context: Surrounding text for context.
            source_id: Document identifier.

        Returns:
            ExtractionResult with table-specific extractions.
        """
        if not self.is_available:
            return ExtractionResult(source_id=source_id, source_type="patent")

        messages = build_table_extraction_prompt(
            table_markdown=table_markdown,
            table_context=table_context,
            source_id=source_id,
        )

        result = await self._call_gemini(
            messages=messages,
            response_model=ExtractionResult,
            source_id=f"{source_id}:table",
        )

        return result or ExtractionResult(
            source_id=source_id, source_type="patent"
        )

    async def extract_batch(
        self,
        raw_documents: list[RawDocument],
        on_complete: Any = None,
    ) -> list[ExtractionResult]:
        """
        Extract from a batch of documents sequentially.

        For parallel processing, use Celery tasks (Phase 2 Iteration 4).

        Args:
            raw_documents: List of RawDocument objects from ingestion.
            on_complete: Optional callback(source_id, result) per document.

        Returns:
            List of ExtractionResult objects.
        """
        results = []
        for i, doc in enumerate(raw_documents):
            logger.info(
                "Extracting %d/%d: %s",
                i + 1,
                len(raw_documents),
                doc.source_id,
            )
            try:
                result = await self.extract_from_raw_document(doc)
                results.append(result)
                if on_complete:
                    on_complete(doc.source_id, result)
            except Exception:
                logger.exception(
                    "Extraction failed for document: %s", doc.source_id
                )
                results.append(
                    ExtractionResult(
                        source_id=doc.source_id,
                        source_type=doc.source_type,
                    )
                )
        return results

    # ── Gemini API Call ──────────────────────────────────────────────────

    async def _call_gemini(
        self,
        messages: list[dict[str, str]],
        response_model: type[ExtractionResult],
        source_id: str,
    ) -> ExtractionResult | None:
        """
        Call Gemini with Instructor validation and retry logic.

        Uses Instructor's from_gemini wrapper for automatic Pydantic
        validation and retry on schema violations.
        """
        for attempt in range(1, self._max_retries + 1):
            try:
                if self._client and INSTRUCTOR_AVAILABLE:
                    # ── Instructor Path (preferred) ──────────────────────
                    result = self._client.create(
                        response_model=response_model,
                        messages=messages,
                        max_retries=2,
                    )
                    return result
                else:
                    # ── Raw Gemini Path (fallback) ───────────────────────
                    result = await self._call_gemini_raw(messages, source_id)
                    return result

            except Exception as e:
                logger.warning(
                    "Gemini extraction attempt %d/%d failed for %s: %s",
                    attempt,
                    self._max_retries,
                    source_id,
                    str(e),
                )
                if attempt == self._max_retries:
                    logger.error(
                        "All %d extraction attempts failed for %s",
                        self._max_retries,
                        source_id,
                    )
                    return None

        return None

    async def _call_gemini_raw(
        self,
        messages: list[dict[str, str]],
        source_id: str,
    ) -> ExtractionResult | None:
        """
        Call Gemini directly without Instructor and manually parse JSON.

        Fallback path when Instructor is not installed.
        """
        import json

        # Convert messages to Gemini Content format
        contents = []
        for msg in messages:
            role = msg["role"]
            # Gemini uses "user" and "model" roles
            if role == "system":
                role = "user"
            contents.append(
                genai.types.ContentDict(role=role, parts=[msg["content"]])
            )

        response = self._model.generate_content(contents)

        if not response.text:
            logger.warning("Empty Gemini response for %s", source_id)
            return None

        try:
            # Parse the JSON response
            json_text = response.text.strip()
            # Handle markdown code blocks
            if json_text.startswith("```"):
                json_text = json_text.split("\n", 1)[1]
                json_text = json_text.rsplit("```", 1)[0]

            data = json.loads(json_text)

            # Ensure source fields are set
            data["source_id"] = data.get("source_id", source_id)

            return ExtractionResult.model_validate(data)
        except (json.JSONDecodeError, Exception) as e:
            logger.error(
                "Failed to parse Gemini JSON response for %s: %s",
                source_id,
                str(e),
            )
            return None
