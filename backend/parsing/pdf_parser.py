"""
FormulaAI — Docling PDF Parser

Converts unstructured PDF documents (patents, TDS, SDS, textbooks)
into structured JSON while preserving:
  • Chemical formulation tables (row/column structure)
  • Ratio tables and composition matrices
  • Figure captions and embedded data
  • Section hierarchy (claims, description, examples)

Uses the Docling library (https://github.com/DS4SD/docling) for
high-fidelity document conversion with table structure preservation.

Gracefully degrades when Docling is not installed, returning
a basic text-only fallback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Conditional Docling import ───────────────────────────────────────────────
try:
    from docling.document_converter import DocumentConverter
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions

    DOCLING_AVAILABLE = True
except ImportError:
    DOCLING_AVAILABLE = False
    logger.warning(
        "Docling is not installed. PDF parsing will be limited to basic text. "
        "Install with: pip install docling"
    )


@dataclass
class ParsedTable:
    """A table extracted from a document with preserved structure."""

    table_id: str
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    caption: str | None = None
    page_number: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def num_rows(self) -> int:
        return len(self.rows)

    @property
    def num_cols(self) -> int:
        return len(self.headers) if self.headers else (
            len(self.rows[0]) if self.rows else 0
        )

    def to_markdown(self) -> str:
        """Convert table to markdown format for LLM consumption."""
        if not self.headers and not self.rows:
            return ""
        lines = []
        if self.caption:
            lines.append(f"**{self.caption}**\n")

        cols = self.headers or [f"Col_{i}" for i in range(self.num_cols)]
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("| " + " | ".join(["---"] * len(cols)) + " |")
        for row in self.rows:
            # Pad row to match column count
            padded = row + [""] * (len(cols) - len(row))
            lines.append("| " + " | ".join(padded[:len(cols)]) + " |")
        return "\n".join(lines)


@dataclass
class ParsedSection:
    """A section of a parsed document with heading hierarchy."""

    heading: str
    level: int  # 1 = top-level, 2 = sub-section, etc.
    text: str
    tables: list[ParsedTable] = field(default_factory=list)
    page_range: tuple[int, int] | None = None


@dataclass
class ParsedDocument:
    """
    Complete parsed output from a document (PDF, DOCX, HTML).

    Contains structured text, tables, and metadata suitable for
    feeding into the LLM extraction pipeline.
    """

    file_path: str
    title: str | None = None
    full_text: str = ""
    sections: list[ParsedSection] = field(default_factory=list)
    tables: list[ParsedTable] = field(default_factory=list)
    num_pages: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tables(self) -> int:
        return len(self.tables)

    def get_text_with_tables(self, max_length: int | None = None) -> str:
        """
        Generate a combined text representation with inline tables.

        This is the primary format fed to the LLM for extraction.
        Tables are rendered as markdown for better LLM comprehension.
        """
        parts = []

        if self.title:
            parts.append(f"# {self.title}\n")

        for section in self.sections:
            heading_prefix = "#" * min(section.level + 1, 4)
            parts.append(f"\n{heading_prefix} {section.heading}\n")
            parts.append(section.text)

            for table in section.tables:
                parts.append(f"\n{table.to_markdown()}\n")

        # Append any standalone tables not in sections
        standalone = [t for t in self.tables if not any(
            t in s.tables for s in self.sections
        )]
        if standalone:
            parts.append("\n## Additional Tables\n")
            for table in standalone:
                parts.append(f"\n{table.to_markdown()}\n")

        result = "\n".join(parts)

        if max_length and len(result) > max_length:
            result = result[:max_length] + "\n\n[... TRUNCATED ...]"

        return result


class PDFParser:
    """
    Parses PDF and document files into structured ParsedDocument objects.

    Uses Docling for high-fidelity conversion with table preservation.
    Falls back to basic text extraction when Docling is unavailable.

    Usage:
        parser = PDFParser()
        doc = parser.parse("path/to/patent.pdf")
        text_for_llm = doc.get_text_with_tables()
    """

    def __init__(
        self,
        ocr_enabled: bool = True,
        table_structure_enabled: bool = True,
    ):
        self._ocr_enabled = ocr_enabled
        self._table_structure_enabled = table_structure_enabled
        self._converter = None

        if DOCLING_AVAILABLE:
            try:
                pipeline_options = PdfPipelineOptions()
                pipeline_options.do_ocr = ocr_enabled
                pipeline_options.do_table_structure = table_structure_enabled

                self._converter = DocumentConverter(
                    allowed_formats=[InputFormat.PDF, InputFormat.DOCX, InputFormat.HTML],
                )
                logger.info(
                    "Docling PDF parser initialized (OCR=%s, Tables=%s)",
                    ocr_enabled,
                    table_structure_enabled,
                )
            except Exception:
                logger.exception("Failed to initialize Docling converter")
                self._converter = None

    @staticmethod
    def is_available() -> bool:
        """Check if Docling is installed and usable."""
        return DOCLING_AVAILABLE

    def parse(self, file_path: str | Path) -> ParsedDocument:
        """
        Parse a document file into a structured ParsedDocument.

        Args:
            file_path: Path to the PDF, DOCX, or HTML file.

        Returns:
            ParsedDocument with extracted text, sections, and tables.
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Document not found: {file_path}")

        if self._converter is not None:
            return self._parse_with_docling(file_path)
        else:
            logger.warning(
                "Docling unavailable, using fallback text extraction for: %s",
                file_path,
            )
            return self._parse_fallback(file_path)

    def parse_text(self, text: str, source_id: str = "text-input") -> ParsedDocument:
        """
        Wrap raw text (e.g., from an API abstract) into a ParsedDocument.

        Used when the input is already text (not a PDF), such as
        patent abstracts or paper abstracts from OpenAlex/PubMed.
        """
        return ParsedDocument(
            file_path=source_id,
            title=None,
            full_text=text,
            sections=[
                ParsedSection(
                    heading="Full Text",
                    level=1,
                    text=text,
                )
            ],
            tables=[],
        )

    # ── Docling Parsing ──────────────────────────────────────────────────

    def _parse_with_docling(self, file_path: Path) -> ParsedDocument:
        """Parse using Docling for high-fidelity extraction."""
        try:
            result = self._converter.convert(str(file_path))
            doc = result.document

            # Extract sections
            sections = []
            tables = []
            table_counter = 0

            # Get document text and structure
            full_text = doc.export_to_text()

            # Extract tables from Docling output
            if hasattr(doc, "tables") and doc.tables:
                for tbl in doc.tables:
                    table_counter += 1
                    parsed_table = self._convert_docling_table(
                        tbl, table_id=f"T{table_counter}"
                    )
                    if parsed_table:
                        tables.append(parsed_table)

            # Build sections from document structure
            if hasattr(doc, "texts") and doc.texts:
                current_section = None
                for item in doc.texts:
                    text_content = item.text if hasattr(item, "text") else str(item)
                    label = getattr(item, "label", "paragraph")

                    if "heading" in str(label).lower() or "title" in str(label).lower():
                        if current_section:
                            sections.append(current_section)
                        level = 1 if "title" in str(label).lower() else 2
                        current_section = ParsedSection(
                            heading=text_content,
                            level=level,
                            text="",
                        )
                    elif current_section:
                        current_section.text += text_content + "\n"
                    else:
                        current_section = ParsedSection(
                            heading="Content",
                            level=1,
                            text=text_content + "\n",
                        )

                if current_section:
                    sections.append(current_section)

            return ParsedDocument(
                file_path=str(file_path),
                title=file_path.stem,
                full_text=full_text,
                sections=sections,
                tables=tables,
                num_pages=getattr(doc, "num_pages", None),
                metadata={"parser": "docling", "file_type": file_path.suffix},
            )

        except Exception:
            logger.exception("Docling parsing failed for: %s", file_path)
            return self._parse_fallback(file_path)

    def _convert_docling_table(
        self, docling_table: Any, table_id: str
    ) -> ParsedTable | None:
        """Convert a Docling table object to our ParsedTable format."""
        try:
            # Docling tables expose different APIs depending on version
            if hasattr(docling_table, "export_to_dataframe"):
                df = docling_table.export_to_dataframe()
                return ParsedTable(
                    table_id=table_id,
                    headers=list(df.columns),
                    rows=[list(row) for _, row in df.iterrows()],
                    caption=getattr(docling_table, "caption", None),
                )
            elif hasattr(docling_table, "cells"):
                # Raw cell-based extraction
                headers = []
                rows = []
                max_col = 0
                for cell in docling_table.cells:
                    col = getattr(cell, "col", 0)
                    if col > max_col:
                        max_col = col

                # Reconstruct grid
                grid: dict[int, dict[int, str]] = {}
                for cell in docling_table.cells:
                    row_idx = getattr(cell, "row", 0)
                    col_idx = getattr(cell, "col", 0)
                    text = getattr(cell, "text", "")
                    if row_idx not in grid:
                        grid[row_idx] = {}
                    grid[row_idx][col_idx] = text

                if grid:
                    sorted_rows = sorted(grid.keys())
                    # First row as headers
                    if sorted_rows:
                        first_row = sorted_rows[0]
                        headers = [
                            grid[first_row].get(c, "")
                            for c in range(max_col + 1)
                        ]
                        for row_idx in sorted_rows[1:]:
                            row = [
                                grid[row_idx].get(c, "")
                                for c in range(max_col + 1)
                            ]
                            rows.append(row)

                return ParsedTable(
                    table_id=table_id,
                    headers=headers,
                    rows=rows,
                    caption=getattr(docling_table, "caption", None),
                )

            return None
        except Exception:
            logger.debug("Failed to convert Docling table %s", table_id)
            return None

    # ── Fallback Parser ──────────────────────────────────────────────────

    def _parse_fallback(self, file_path: Path) -> ParsedDocument:
        """
        Basic text extraction fallback when Docling is unavailable.

        Only handles plain text and basic PDF text layer extraction.
        Tables will NOT be preserved.
        """
        text = ""
        try:
            if file_path.suffix.lower() in (".txt", ".md", ".csv"):
                text = file_path.read_text(encoding="utf-8", errors="replace")
            else:
                # For PDFs without Docling, we can only note it's unsupported
                text = (
                    f"[PDF file detected: {file_path.name}. "
                    f"Docling is required for full PDF parsing. "
                    f"Install with: pip install docling]"
                )
                logger.warning(
                    "Cannot parse PDF without Docling: %s", file_path
                )
        except Exception:
            logger.exception("Fallback parsing failed for: %s", file_path)

        return ParsedDocument(
            file_path=str(file_path),
            title=file_path.stem,
            full_text=text,
            sections=[
                ParsedSection(heading="Content", level=1, text=text)
            ],
            tables=[],
            metadata={"parser": "fallback", "file_type": file_path.suffix},
        )
