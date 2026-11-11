"""
FormulaAI — Domain-Specific Extraction Prompts

System prompts and few-shot examples for the Gemini LLM extraction chain.
These prompts encode deep agrochemical domain knowledge to guide the LLM
in identifying entities, relationships, and physicochemical parameters.

Prompt Design Principles:
  1. Explicit schema awareness — the LLM knows exactly what fields to fill
  2. Negative data emphasis — failures and incompatibilities are as valuable
     as successes
  3. Physicochemical parameter hunting — HLB, pI, zeta potential, LogP, pH
     ranges are called out as CRITICAL extraction targets
  4. Trade name awareness — the LLM is instructed to flag trade names for
     downstream normalization
"""

# ── System Prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are FormulaAI, an expert agrochemical formulation scientist and data extraction agent with 30 years of experience in pesticide, biopesticide, biostimulant, and crop protection formulation development.

Your task is to extract structured scientific data from agrochemical documents (patents, research papers, technical data sheets, safety data sheets, and formulation manuals).

## EXTRACTION RULES

### Entities to Extract:
1. **Chemical Compounds**: Active ingredients, excipients, solvents, surfactants, adjuvants, polymers, co-formulants. For EVERY compound, extract:
   - Name (as written in text)
   - IUPAC name (if mentioned)
   - Trade/commercial names
   - CAS number (if mentioned)
   - SMILES string (if mentioned)
   - **CRITICAL physicochemical parameters** (extract whenever present):
     - Molecular weight (g/mol)
     - LogP (partition coefficient)
     - HLB value (Hydrophilic-Lipophilic Balance)
     - pH stability range (min and max)
     - Aqueous solubility (g/L)

2. **Biological Agents**: Bacteria, fungi, viruses, endophytes used in biopesticide/biostimulant formulations. Extract:
   - Scientific name and strain designation
   - Type (bacteria, fungi, virus, endophyte)
   - Target organisms/pathogens
   - Mode of action

3. **Peptides**: Antimicrobial peptides, cell-penetrating peptides, signal peptides. Extract all Compound fields PLUS:
   - Isoelectric point (pI)
   - Amino acid sequence
   - Cyclic/linear structure

4. **Nanomaterials / RNAi Vectors**: Nanoparticles, liposomes, nanoemulsions, RNAi delivery systems. Extract all Compound fields PLUS:
   - Zeta potential (mV)
   - Particle size (nm)
   - Polydispersity Index (PDI)
   - Encapsulation efficiency (%)
   - Vector type and cargo

### Relationships to Extract:
For every pair of entities that interact, extract a relationship with type:
- **FORMULATED_WITH**: Entity A is mixed with Entity B (include ratio, pH, temperature if mentioned)
- **STABILIZES**: Entity A stabilizes Entity B (include mechanism)
- **INCOMPATIBLE_WITH**: Entity A is incompatible with Entity B (include reason)
- **SOLUBILIZES**: Entity A dissolves/solubilizes Entity B
- **DEGRADES**: Entity A degrades Entity B
- **SYNERGIZES_WITH**: Entity A has synergistic effect with Entity B
- **ENHANCES**: Entity A enhances the activity of Entity B
- **INHIBITS**: Entity A inhibits Entity B
- **DELIVERS**: Entity A delivers Entity B (for nanocarriers)
- **ENCAPSULATES**: Entity A encapsulates Entity B
- **REPURPOSABLE_AS**: Pharma excipient Entity A can be repurposed for agrochemical use
- **REGULATED_BY**: Formulation is regulated by a regulatory body
- **FAILED_DUE_TO**: A formulation attempt failed due to Entity B

### CRITICAL: Negative Data Extraction
**Failures are as valuable as successes.** If the document mentions:
- A formulation that precipitated, phase-separated, or degraded
- An ingredient that was incompatible with another
- UV degradation, thermal instability, or pH-induced breakdown
- Any "did not work" or "was abandoned" language

You MUST extract these as relationships with `is_negative_data: true` and relationship type `FAILED_DUE_TO` or `INCOMPATIBLE_WITH`.

### Confidence Scoring:
For each entity and relationship, assign a confidence score (0.0–1.0):
- 1.0: Explicit, unambiguous statement with exact values
- 0.8–0.9: Clearly stated but some inference needed
- 0.6–0.7: Implied or partially stated
- 0.3–0.5: Speculative or uncertain
- Below 0.3: Do not extract (too uncertain)

### Source Context:
For each extraction, include the `source_context` field containing the exact sentence or table cell where you found the information. This is critical for human verification.

## OUTPUT FORMAT
Return a JSON object matching the ExtractionResult schema exactly. Do not add fields not in the schema. Use null for unknown values, never guess."""


# ── Few-Shot Examples ────────────────────────────────────────────────────────

FEW_SHOT_PATENT_INPUT = """## Patent US10234567: Stable Aqueous Herbicide Composition

### Description
This invention relates to a stable aqueous herbicide composition comprising
glyphosate isopropylamine salt (CAS 38641-94-0) as the active ingredient at
360 g/L concentration. The formulation includes Tween 80 (HLB 15.0) as the
primary surfactant at 5% w/v, and polyethylene glycol 400 as a co-solvent at
3% w/v.

### Example 1
The composition was found to be stable at pH 4.5-6.5 and temperatures up to
54°C for 2 weeks. When tested with Span 60 (HLB 4.7) as an alternative
surfactant, the formulation phase-separated within 24 hours due to
insufficient hydrophilicity.

### Table 1: Formulation Stability Results
| Component | Concentration | HLB | Result |
|---|---|---|---|
| Tween 80 | 5% w/v | 15.0 | Stable |
| Span 60 | 5% w/v | 4.7 | Phase separated |
| Brij 35 | 5% w/v | 16.9 | Stable |"""


FEW_SHOT_PATENT_OUTPUT = """{
  "source_id": "US10234567",
  "source_type": "patent",
  "compounds": [
    {
      "name": "glyphosate isopropylamine salt",
      "iupac_name": null,
      "trade_names": [],
      "cas_number": "38641-94-0",
      "canonical_smiles": null,
      "inchikey": null,
      "molecular_weight": null,
      "log_p": null,
      "hlb_value": null,
      "ph_stability_min": 4.5,
      "ph_stability_max": 6.5,
      "solubility_g_per_l": null,
      "compound_class": "organic",
      "functional_categories": ["herbicide"],
      "confidence": 0.95,
      "source_context": "glyphosate isopropylamine salt (CAS 38641-94-0) as the active ingredient at 360 g/L"
    },
    {
      "name": "Polysorbate 80",
      "iupac_name": null,
      "trade_names": ["Tween 80"],
      "cas_number": null,
      "canonical_smiles": null,
      "inchikey": null,
      "molecular_weight": null,
      "log_p": null,
      "hlb_value": 15.0,
      "ph_stability_min": null,
      "ph_stability_max": null,
      "solubility_g_per_l": null,
      "compound_class": "organic",
      "functional_categories": ["surfactant_adjuvant", "emulsifier"],
      "confidence": 0.95,
      "source_context": "Tween 80 (HLB 15.0) as the primary surfactant at 5% w/v"
    },
    {
      "name": "Polyethylene glycol 400",
      "iupac_name": null,
      "trade_names": [],
      "cas_number": null,
      "canonical_smiles": null,
      "inchikey": null,
      "molecular_weight": null,
      "log_p": null,
      "hlb_value": null,
      "ph_stability_min": null,
      "ph_stability_max": null,
      "solubility_g_per_l": null,
      "compound_class": "organic",
      "functional_categories": ["solubilizer", "excipient"],
      "confidence": 0.90,
      "source_context": "polyethylene glycol 400 as a co-solvent at 3% w/v"
    },
    {
      "name": "Sorbitan monostearate",
      "iupac_name": null,
      "trade_names": ["Span 60"],
      "cas_number": null,
      "canonical_smiles": null,
      "inchikey": null,
      "molecular_weight": null,
      "log_p": null,
      "hlb_value": 4.7,
      "ph_stability_min": null,
      "ph_stability_max": null,
      "solubility_g_per_l": null,
      "compound_class": "organic",
      "functional_categories": ["surfactant_adjuvant", "emulsifier"],
      "confidence": 0.90,
      "source_context": "Span 60 (HLB 4.7) as an alternative surfactant"
    }
  ],
  "biologicals": [],
  "peptides": [],
  "nanomaterials": [],
  "relationships": [
    {
      "source_entity": "glyphosate isopropylamine salt",
      "target_entity": "Polysorbate 80",
      "relationship_type": "FORMULATED_WITH",
      "ratio": "5% w/v surfactant to 360 g/L AI",
      "ph": null,
      "temperature_c": null,
      "mechanism": null,
      "physical_state": null,
      "target_use": null,
      "status": null,
      "reason": null,
      "confidence": 0.95,
      "source_context": "comprising glyphosate isopropylamine salt... includes Tween 80 as the primary surfactant",
      "is_negative_data": false
    },
    {
      "source_entity": "Polysorbate 80",
      "target_entity": "glyphosate isopropylamine salt",
      "relationship_type": "STABILIZES",
      "ratio": null,
      "ph": null,
      "temperature_c": 54.0,
      "mechanism": "surfactant stabilization",
      "physical_state": "stable aqueous solution",
      "target_use": null,
      "status": null,
      "reason": null,
      "confidence": 0.90,
      "source_context": "stable at pH 4.5-6.5 and temperatures up to 54°C for 2 weeks",
      "is_negative_data": false
    },
    {
      "source_entity": "Sorbitan monostearate",
      "target_entity": "glyphosate isopropylamine salt",
      "relationship_type": "INCOMPATIBLE_WITH",
      "ratio": "5% w/v",
      "ph": null,
      "temperature_c": null,
      "mechanism": "insufficient hydrophilicity (HLB 4.7 too low)",
      "physical_state": "phase separated",
      "target_use": null,
      "status": null,
      "reason": "HLB value too low for aqueous formulation",
      "confidence": 0.95,
      "source_context": "Span 60 (HLB 4.7) as an alternative surfactant, the formulation phase-separated within 24 hours",
      "is_negative_data": true
    }
  ],
  "formulation_type": "SL",
  "document_summary": "Patent describes a stable aqueous glyphosate herbicide formulation using Tween 80 (HLB 15.0) as surfactant. Span 60 (HLB 4.7) was found incompatible, causing phase separation due to insufficient hydrophilicity."
}"""


# ── Prompt Builders ──────────────────────────────────────────────────────────


def build_extraction_prompt(
    document_text: str,
    source_id: str,
    source_type: str,
) -> list[dict[str, str]]:
    """
    Build the complete message list for the extraction LLM call.

    Returns a list of message dicts in the OpenAI/Gemini chat format:
    [{"role": "system"|"user"|"model", "content": "..."}]
    """
    messages = [
        {"role": "user", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Here is an example of correct extraction from a patent:\n\n"
                f"**INPUT DOCUMENT:**\n{FEW_SHOT_PATENT_INPUT}"
            ),
        },
        {
            "role": "model",
            "content": FEW_SHOT_PATENT_OUTPUT,
        },
        {
            "role": "user",
            "content": (
                f"Now extract all entities and relationships from the following "
                f"{source_type} document.\n\n"
                f"**Document ID:** {source_id}\n"
                f"**Source Type:** {source_type}\n\n"
                f"**DOCUMENT TEXT:**\n{document_text}\n\n"
                f"Extract ALL compounds, biological agents, peptides, "
                f"nanomaterials, and relationships. Pay special attention to "
                f"physicochemical parameters (HLB, LogP, pH ranges, particle "
                f"sizes, zeta potential) and negative data (failures, "
                f"incompatibilities). Return the ExtractionResult JSON."
            ),
        },
    ]
    return messages


def build_table_extraction_prompt(
    table_markdown: str,
    table_context: str,
    source_id: str,
) -> list[dict[str, str]]:
    """
    Build a specialized prompt for extracting data from a chemical table.

    Tables in patents often contain the richest formulation data
    (compositions, stability results, bioassay data) and deserve
    focused extraction.
    """
    messages = [
        {
            "role": "user",
            "content": (
                f"{SYSTEM_PROMPT}\n\n"
                f"FOCUS: You are extracting data specifically from a "
                f"formulation/composition table. Tables in agrochemical patents "
                f"contain the most precise data — exact ratios, concentrations, "
                f"stability outcomes, and bioassay results.\n\n"
                f"**Document ID:** {source_id}\n\n"
                f"**Context around the table:**\n{table_context}\n\n"
                f"**TABLE:**\n{table_markdown}\n\n"
                f"Extract every compound, ratio, and relationship from this table. "
                f"If a row shows a 'failed' or 'unstable' result, mark it as "
                f"negative data with is_negative_data=true."
            ),
        },
    ]
    return messages
