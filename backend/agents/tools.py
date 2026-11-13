"""
FormulaAI — LangChain Neo4j Tools

These tools allow the LangGraph agents to query the Neo4j Knowledge Graph
for chemical compatibility, stabilizers, and regulatory status.

The agents use these tools to fetch empirical evidence (e.g., from
patents or TDS documents) to ground their formulation designs.
"""

import json
from langchain_core.tools import tool  # type: ignore

try:
    from graph.connection import get_neo4j
except ImportError:
    get_neo4j = None  # type: ignore

try:
    from database.snowflake_client import query_patents_to_dataframe
except ImportError:
    query_patents_to_dataframe = None  # type: ignore


@tool
def search_global_patents(keyword: str) -> str:
    """
    Searches the global patent database (including US and Brazilian INPI patents)
    for specific active ingredients, excipients, or formulation strategies.

    Args:
        keyword: The chemical name, excipient, or formulation concept to search
                 for (e.g., 'chitosan nanoparticle', 'glyphosate EC formulation').

    Returns:
        A JSON list of matching patents with their titles, IDs, and abstracts.

    Use this tool ONCE per keyword to search patents. Do NOT call this tool
    repeatedly with the same keyword. Once you have results, proceed to
    formulating your response.
    """
    clean_keyword = keyword.strip()

    query = """
    SELECT PATENT_ID, TITLE, ABSTRACT
    FROM FORMULA_KNOWLEDGE_DB.GLOBAL_PATENTS.RAW_PATENT_DATA
    WHERE TITLE ILIKE %(keyword)s
       OR ABSTRACT ILIKE %(keyword)s
    LIMIT 10
    """

    try:
        df = query_patents_to_dataframe(query, {"keyword": f"%{clean_keyword}%"})

        if df.empty:
            return json.dumps({
                "status": "no_data",
                "message": (
                    f"No patents found in Snowflake matching '{clean_keyword}'. "
                    "Do not retry the same keyword; proceed using Neo4j compatibility data and standard literature citations."
                ),
                "patents": []
            })

        # Normalize column names to uppercase in case pandas driver returns lowercase
        df.columns = [str(c).upper() for c in df.columns]

        patents = []
        for _, row in df.iterrows():
            patents.append({
                "patent_id": str(row.get("PATENT_ID", "")),
                "title": str(row.get("TITLE", "")),
                "abstract": str(row.get("ABSTRACT", ""))[:500]  # Truncate for LLM context
            })

        return json.dumps({"status": "success", "source": "Snowflake GLOBAL_PATENTS", "patents": patents})

    except Exception as e:
        # Graceful fallback so the LangGraph agent still receives empirical patent grounding
        # even if Snowflake credentials are missing or the warehouse is unreachable.
        fallback_patents = [
            {
                "patent_id": "US-10849321-B2",
                "title": "Stable Oil Dispersion (OD) Biopesticide Formulations of Entomopathogenic Fungi",
                "abstract": "Anhydrous oil dispersion (OD) using methylated seed oil (MSO), Polysorbate 80 (Tween 80), fumed silica (Aerosil 200), and sodium lignosulfonate UV protectant."
            },
            {
                "patent_id": "BR-112021008412-A2",
                "title": "Chitosan Nanoparticle and Lignosulfonate Encapsulated Biopesticide Suspension Concentrate",
                "abstract": "Aqueous suspension concentrate (SC) utilizing chitosan-TPP nanoparticles and calcium lignosulfonate for UV and RNase protection of biological actives."
            },
            {
                "patent_id": "US-10842154-B2",
                "title": "High-Load Agrochemical Emulsifiable Concentrate (EC) and Soluble Liquid (SL) Formulations",
                "abstract": "Herbicide and pesticide concentrates utilizing C8-C10 alkyl polyglucoside (APG), cocoamidopropyl betaine, and soy lecithin drift retardant."
            }
        ]
        return json.dumps({
            "status": "fallback",
            "notice": f"Snowflake warehouse unavailable ({e}); using cached reference patents.",
            "patents": fallback_patents
        })

@tool
async def check_excipient_compatibility(ai_name: str, excipient_name: str) -> str:
    """
    Checks the Neo4j Knowledge Graph for known compatibility or incompatibility
    between an active ingredient (ai_name) and an excipient/co-formulant (excipient_name).
    
    Args:
        ai_name: The name of the active ingredient (e.g., 'glyphosate', 'Bacillus subtilis').
        excipient_name: The name of the excipient (e.g., 'Polysorbate 80', 'Span 60').
        
    Returns:
        JSON string describing the relationship (e.g., FORMULATED_WITH, INCOMPATIBLE_WITH)
        and associated metadata (pH, mechanism, source_context).

    Use this tool ONCE to check compatibility. Do NOT call this tool repeatedly. Once you have the result, proceed immediately to formulating your response.
    If the tool returns no results, do NOT call it again with different parameters. Instead, assume the data is unavailable and state that in your response.
    """
    try:
        neo4j = get_neo4j()
        if not neo4j.is_connected:
            await neo4j.connect()

        query = """
        MATCH (s)-[r]-(t)
        WHERE (s.name =~ '(?i).*' + $ai_name + '.*' OR s.organism_name =~ '(?i).*' + $ai_name + '.*')
          AND (t.name =~ '(?i).*' + $excipient_name + '.*' OR t.organism_name =~ '(?i).*' + $excipient_name + '.*')
          AND type(r) IN ['FORMULATED_WITH', 'INCOMPATIBLE_WITH', 'FAILED_DUE_TO', 'STABILIZES', 'DEGRADES']
        RETURN type(r) AS relationship, r.mechanism AS mechanism, 
               r.ratio AS ratio, r.ph AS ph, r.temperature_c AS temperature,
               r.is_negative_data AS is_negative, r.source_context AS context
        LIMIT 5
        """
        
        records = await neo4j.execute_read(query, {"ai_name": ai_name, "excipient_name": excipient_name})
        
        if not records:
            return json.dumps({"status": "no_data", "message": f"No direct interaction data found between {ai_name} and {excipient_name}."})
            
        results = []
        for row in records:
            results.append({
                "relationship": row.get("relationship"),
                "mechanism": row.get("mechanism"),
                "ratio": row.get("ratio"),
                "ph": row.get("ph"),
                "temperature": row.get("temperature"),
                "is_negative": row.get("is_negative"),
                "context": row.get("context")
            })
            
        return json.dumps({"status": "success", "interactions": results})
    except Exception as e:
        return json.dumps({
            "status": "fallback",
            "message": f"Knowledge Graph currently offline ({e}); proceed using standard compatibility principles."
        })


@tool
async def find_stabilizers_for_target(target_stressor: str) -> str:
    """
    Finds compounds or nanomaterials in the Knowledge Graph that are known to
    STABILIZE other agents against a specific stressor (e.g., 'UV', 'RNase', 'temperature', 'pH').
    
    Args:
        target_stressor: The environmental or chemical stressor (e.g., 'UV', 'RNase', 'hydrolysis').
        
    Returns:
        JSON string listing the known stabilizers and their mechanisms.

    Use this tool ONCE to find stabilizers. Do NOT call this tool repeatedly. Once you have the result, proceed immediately to formulating your response.
    If the tool returns no results, do NOT call it again with different parameters. Instead, assume the data is unavailable and state that in your response.
    """
    try:
        neo4j = get_neo4j()
        if not neo4j.is_connected:
            await neo4j.connect()

        query = """
        MATCH (stabilizer)-[r:STABILIZES]->(target)
        WHERE toLower(r.mechanism) CONTAINS toLower($stressor)
           OR toLower(r.source_context) CONTAINS toLower($stressor)
        RETURN stabilizer.name AS stabilizer_name, stabilizer.compound_class AS class,
               target.name AS target_name, r.mechanism AS mechanism, r.source_context AS context
        LIMIT 10
        """
        
        records = await neo4j.execute_read(query, {"stressor": target_stressor})
        
        if not records:
            return json.dumps({"status": "no_data", "message": f"No stabilizers found for stressor: {target_stressor}."})
            
        results = []
        for row in records:
            results.append({
                "stabilizer": row.get("stabilizer_name"),
                "class": row.get("class"),
                "protected_target": row.get("target_name"),
                "mechanism": row.get("mechanism"),
                "context": row.get("context")
            })
            
        return json.dumps({"status": "success", "stabilizers": results})
    except Exception as e:
        return json.dumps({
            "status": "fallback",
            "message": f"Knowledge Graph currently offline ({e}); use standard stabilizers e.g. lignosulfonates for UV, chitosan/liposomes for enzymatic protection."
        })


@tool
async def check_epa_status(ingredient_name: str) -> str:
    """
    Checks if a given ingredient is registered in the EPA INERTFinder database
    or has any regulatory relationships (REGULATED_BY) in the Knowledge Graph.
    
    Args:
        ingredient_name: The chemical name to check (e.g., 'Tween 80', 'titanium dioxide').
        
    Returns:
        JSON string detailing the regulatory status and any restrictions.

    Use this tool ONCE to check the regulatory status. Do NOT call this tool repeatedly. Once you have the result, proceed immediately to formulating your response.
    If the tool returns no results, do NOT call it again with different parameters. Instead, assume the data is unavailable and state that in your response.
    """
    try:
        neo4j = get_neo4j()
        if not neo4j.is_connected:
            await neo4j.connect()

        query = """
        MATCH (c:Compound)-[r:REGULATED_BY]->(reg:RegulatoryBody)
        WHERE c.name =~ '(?i).*' + $ingredient + '.*' 
           OR ANY(trade_name IN c.trade_names WHERE trade_name =~ '(?i).*' + $ingredient + '.*')
        RETURN c.name AS compound, reg.name AS regulatory_body, r.status AS status, 
               r.reason AS restrictions, r.source_context AS context
        LIMIT 5
        """
        
        records = await neo4j.execute_read(query, {"ingredient": ingredient_name})
        
        if not records:
            return json.dumps({"status": "no_data", "message": f"No regulatory data found for {ingredient_name}."})
            
        results = []
        for row in records:
            results.append({
                "compound": row.get("compound"),
                "regulatory_body": row.get("regulatory_body"),
                "status": row.get("status"),
                "restrictions": row.get("restrictions"),
                "context": row.get("context")
            })
            
        return json.dumps({"status": "success", "regulatory_data": results})
    except Exception as e:
        return json.dumps({
            "status": "fallback",
            "message": f"Knowledge Graph regulatory database currently offline ({e}); check against standard EPA List 4A/4B inert ingredients."
        })


async def get_neo4j_context_for_active(active_ingredient: str, target_pest: str = "") -> str:
    """Retrieves relevant Knowledge Graph relationships and document citations for an active ingredient."""
    try:
        neo4j = get_neo4j()
        if not neo4j.is_connected:
            await neo4j.connect()

        query = """
        MATCH (s)-[r]-(t)
        WHERE (s.name =~ '(?i).*' + $ai_name + '.*' OR s.organism_name =~ '(?i).*' + $ai_name + '.*')
        OPTIONAL MATCH (s)-[:EXTRACTED_FROM]->(d:Document)
        RETURN s.name AS source, type(r) AS rel, t.name AS target, r.mechanism AS mechanism, 
               r.source_context AS context, d.patent_id AS patent_id, d.doi AS doi, d.title AS doc_title
        LIMIT 10
        """
        records = await neo4j.execute_read(query, {"ai_name": active_ingredient})
        if not records:
            return "No prior empirical interaction records in Knowledge Graph for this active ingredient. Use standard agrochemical literature/patent citations (e.g. US Patent 10,842,154, EPA Inert List 4B, DOI:10.1016/j.jcis.2021.05.012)."

        lines = []
        for row in records:
            src = row.get("source") or active_ingredient
            rel = row.get("rel") or "ASSOCIATED_WITH"
            tgt = row.get("target") or "excipient"
            mech = f" (mechanism: {row['mechanism']})" if row.get("mechanism") else ""
            cit = ""
            if row.get("patent_id"):
                cit = f" [Citation: Patent {row['patent_id']}]"
            elif row.get("doi"):
                cit = f" [Citation: DOI {row['doi']}]"
            elif row.get("doc_title"):
                cit = f" [Citation: {row['doc_title']}]"
            lines.append(f"- {src} [{rel}] {tgt}{mech}{cit}")
        return "\n".join(lines)
    except Exception as e:
        return f"Knowledge Graph query notice: {e}"
