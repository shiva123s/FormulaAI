"""
FormulaAI — Shared Test Fixtures

Provides reusable pytest fixtures for mocking HTTP responses, creating
test data, and configuring test environments.
"""

from __future__ import annotations

import pytest
import pytest_asyncio


# ── Sample Data ──────────────────────────────────────────────────────────────


SAMPLE_OPENALEX_WORK = {
    "id": "https://openalex.org/W2741809807",
    "doi": "https://doi.org/10.1000/test-doi",
    "title": "Novel surfactant systems for glyphosate formulation",
    "display_name": "Novel surfactant systems for glyphosate formulation",
    "publication_date": "2023-06-15",
    "type": "article",
    "open_access": {"is_oa": True, "oa_url": "https://example.com/paper.pdf"},
    "authorships": [
        {"author": {"display_name": "Jane Smith", "id": "A1"}},
        {"author": {"display_name": "John Doe", "id": "A2"}},
    ],
    "concepts": [
        {"display_name": "Surfactant", "score": 0.95},
        {"display_name": "Herbicide", "score": 0.88},
    ],
    "keywords": [{"keyword": "glyphosate"}, {"keyword": "formulation"}],
    "abstract_inverted_index": {
        "This": [0],
        "study": [1],
        "evaluates": [2],
        "novel": [3],
        "surfactant": [4],
        "systems": [5],
        "for": [6],
        "glyphosate": [7],
        "formulations.": [8],
    },
    "primary_location": {
        "source": {"display_name": "Journal of Agricultural Chemistry"},
        "landing_page_url": "https://example.com/paper",
    },
    "cited_by_count": 42,
}

SAMPLE_OPENALEX_RESPONSE = {
    "results": [SAMPLE_OPENALEX_WORK],
    "meta": {"next_cursor": None, "count": 1},
}

SAMPLE_PUBMED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
    <PubmedArticle>
        <MedlineCitation>
            <PMID>12345678</PMID>
            <Article>
                <ArticleTitle>Surfactant effects on pesticide formulation stability</ArticleTitle>
                <Abstract>
                    <AbstractText Label="BACKGROUND">Surfactants play a critical role in pesticide formulations.</AbstractText>
                    <AbstractText Label="RESULTS">We found that polysorbate 80 improved stability by 40%.</AbstractText>
                </Abstract>
                <AuthorList>
                    <Author>
                        <LastName>Garcia</LastName>
                        <ForeName>Maria</ForeName>
                    </Author>
                </AuthorList>
                <Journal>
                    <Title>Pest Management Science</Title>
                    <JournalIssue>
                        <PubDate>
                            <Year>2023</Year>
                            <Month>03</Month>
                            <Day>15</Day>
                        </PubDate>
                    </JournalIssue>
                </Journal>
            </Article>
            <MeshHeadingList>
                <MeshHeading>
                    <DescriptorName>Surfactants</DescriptorName>
                </MeshHeading>
                <MeshHeading>
                    <DescriptorName>Pesticides</DescriptorName>
                </MeshHeading>
            </MeshHeadingList>
        </MedlineCitation>
        <PubmedData>
            <ArticleIdList>
                <ArticleId IdType="doi">10.1002/ps.7890</ArticleId>
                <ArticleId IdType="pubmed">12345678</ArticleId>
            </ArticleIdList>
        </PubmedData>
    </PubmedArticle>
</PubmedArticleSet>"""

SAMPLE_CHEMBL_MOLECULE = {
    "molecule_chembl_id": "CHEMBL25",
    "pref_name": "ASPIRIN",
    "molecule_type": "Small molecule",
    "molecule_structures": {
        "canonical_smiles": "CC(=O)Oc1ccccc1C(O)=O",
        "standard_inchi_key": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
    },
    "molecule_properties": {
        "full_mwt": "180.16",
        "alogp": "1.31",
        "hba": 3,
        "hbd": 1,
        "psa": "63.60",
        "num_ro5_violations": 0,
    },
    "max_phase": 4,
    "first_approval": 1950,
    "oral": True,
    "topical": False,
}

SAMPLE_CHEMBL_SEARCH_RESPONSE = {
    "molecules": [SAMPLE_CHEMBL_MOLECULE],
    "page_meta": {"next": None},
}

SAMPLE_PATENT_RESPONSE = {
    "patents": [
        {
            "patent_id": "10123456",
            "patent_title": "Herbicide composition with improved surfactant system",
            "patent_abstract": "A novel herbicide formulation comprising glyphosate and a non-ionic surfactant.",
            "patent_date": "2023-01-15",
            "patent_type": "utility",
            "patent_num_claims": 20,
            "inventors": [
                {"inventor_first_name": "Alice", "inventor_last_name": "Johnson"},
            ],
            "assignees": [
                {"assignee_organization": "AgriChem Corp"},
            ],
            "cpcs": [
                {"cpc_subgroup_id": "A01N57/20"},
            ],
        }
    ],
    "total_patent_count": 1,
}

SAMPLE_PUBCHEM_CID_RESPONSE = {
    "IdentifierList": {"CID": [5564]}
}

SAMPLE_PUBCHEM_PROPERTY_RESPONSE = {
    "PropertyTable": {
        "Properties": [
            {
                "CID": 5564,
                "IUPACName": "2-(phosphonomethylamino)acetic acid",
                "CanonicalSMILES": "OC(=O)CNCP(O)(O)=O",
                "MolecularFormula": "C3H8NO5P",
                "MolecularWeight": 169.07,
            }
        ]
    }
}

SAMPLE_PUBCHEM_SYNONYMS_RESPONSE = {
    "InformationList": {
        "Information": [
            {
                "CID": 5564,
                "Synonym": [
                    "glyphosate",
                    "1071-83-6",
                    "Roundup",
                    "N-(phosphonomethyl)glycine",
                ],
            }
        ]
    }
}

SAMPLE_NCBI_ESEARCH_RESPONSE = {
    "esearchresult": {"idlist": ["1423"]}
}

SAMPLE_NCBI_ESUMMARY_RESPONSE = {
    "result": {
        "1423": {
            "scientificname": "Bacillus thuringiensis",
            "commonname": "Bt",
            "rank": "species",
            "division": "Bacteria",
            "lineage": "Bacteria; Firmicutes; Bacilli; Bacillales; Bacillaceae; Bacillus",
        }
    }
}
