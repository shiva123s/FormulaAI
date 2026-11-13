-- ==============================================================================
-- FormulaAI — Snowflake Enterprise Patent C-RAG Initialization Script
-- 
-- Run this script in a Snowflake SQL Worksheet as ACCOUNTADMIN or SYSADMIN.
-- It sets up the compute warehouse, knowledge database, patent schema,
-- table structure, and initial seed patents used by FormulaAI multi-agent tools.
-- ==============================================================================

-- 1. Create Compute Warehouse
CREATE WAREHOUSE IF NOT EXISTS FORMULA_APP_WH
    WITH 
    WAREHOUSE_SIZE = 'XSMALL'
    AUTO_SUSPEND = 60
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    COMMENT = 'FormulaAI application compute warehouse for patent semantic search';

-- 2. Create Knowledge Database
CREATE DATABASE IF NOT EXISTS FORMULA_KNOWLEDGE_DB
    COMMENT = 'FormulaAI enterprise scientific knowledge and patent warehouse';

USE DATABASE FORMULA_KNOWLEDGE_DB;

-- 3. Create Patent Schema
CREATE SCHEMA IF NOT EXISTS GLOBAL_PATENTS
    COMMENT = 'Global patent records covering agrochemical formulations, excipients, and delivery vectors';

USE SCHEMA GLOBAL_PATENTS;

-- 4. Create Raw Patent Table
CREATE TABLE IF NOT EXISTS RAW_PATENT_DATA (
    PATENT_ID VARCHAR(100) PRIMARY KEY,
    TITLE VARCHAR(1000),
    ABSTRACT TEXT,
    COUNTRY_CODE VARCHAR(10),
    PUBLICATION_DATE VARCHAR(50),
    SOURCE_URL VARCHAR(1000),
    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Ensure columns exist if table was already created in earlier migrations
ALTER TABLE RAW_PATENT_DATA ADD COLUMN IF NOT EXISTS COUNTRY_CODE VARCHAR(10);
ALTER TABLE RAW_PATENT_DATA ADD COLUMN IF NOT EXISTS PUBLICATION_DATE VARCHAR(50);
ALTER TABLE RAW_PATENT_DATA ADD COLUMN IF NOT EXISTS SOURCE_URL VARCHAR(1000);

-- 5. Insert Seed Agrochemical & Biopesticide Patents
MERGE INTO RAW_PATENT_DATA AS target
USING (
    SELECT 
        'US-10849321-B2' AS PATENT_ID,
        'Stable Oil Dispersion (OD) Biopesticide Formulations of Entomopathogenic Fungi' AS TITLE,
        'Anhydrous oil dispersion (OD) formulation for entomopathogenic fungi including Beauveria bassiana and Metarhizium anisopliae. Comprises methylated seed oil (MSO) carrier, polyoxyethylene sorbitan monooleate (Polysorbate 80 / Tween 80), hydrophobic fumed silica (Aerosil 200) rheology modifier, and sodium lignosulfonate UV protectant to enhance spore survival, dispersion stability, and leaf deposition under solar UV radiation.' AS ABSTRACT,
        'US' AS COUNTRY_CODE,
        '2020-12-01' AS PUBLICATION_DATE,
        'https://patents.google.com/patent/US10849321B2' AS SOURCE_URL
    UNION ALL
    SELECT 
        'BR-112021008412-A2' AS PATENT_ID,
        'Chitosan Nanoparticle and Lignosulfonate Encapsulated Biopesticide Suspension Concentrate' AS TITLE,
        'Aqueous suspension concentrate (SC) utilizing chitosan-tripolyphosphate (TPP) nanoparticles and calcium lignosulfonate for sustained release, enhanced foliar cuticle adhesion, and enzymatic (RNase/protease) shielding of fragile biological payloads including antimicrobial peptides, Bacillus thuringiensis endotoxins, and double-stranded RNA (dsRNA).' AS ABSTRACT,
        'BR' AS COUNTRY_CODE,
        '2021-08-10' AS PUBLICATION_DATE,
        'https://patents.google.com/patent/BR112021008412A2' AS SOURCE_URL
    UNION ALL
    SELECT 
        'US-10842154-B2' AS PATENT_ID,
        'High-Load Agrochemical Emulsifiable Concentrate (EC) and Soluble Liquid (SL) Formulations' AS TITLE,
        'High-load herbicide and pesticide concentrate utilizing C8-C10 alkyl polyglucoside (APG) non-ionic surfactant, cocoamidopropyl betaine amphoteric co-surfactant, ammonium sulfate water conditioner, and soy lecithin drift retardant exhibiting low aquatic toxicity, negligible eye irritation, and high rainfastness.' AS ABSTRACT,
        'US' AS COUNTRY_CODE,
        '2020-11-24' AS PUBLICATION_DATE,
        'https://patents.google.com/patent/US10842154B2' AS SOURCE_URL
    UNION ALL
    SELECT 
        'WO-2023114509-A1' AS PATENT_ID,
        'Double-Stranded RNA (dsRNA) Nanocarrier Formulations for Targeted Pest Control' AS TITLE,
        'Nanostructured lipid carrier (NLC) and cationic polymer formulations for stabilizing and delivering double-stranded RNA (dsRNA) targeting pest-specific essential genes in aphids, Colorado potato beetle, and diamondback moth. Provides protection against environmental nucleases and solar photolysis.' AS ABSTRACT,
        'WO' AS COUNTRY_CODE,
        '2023-06-22' AS PUBLICATION_DATE,
        'https://patents.google.com/patent/WO2023114509A1' AS SOURCE_URL
) AS source
ON target.PATENT_ID = source.PATENT_ID
WHEN MATCHED THEN
    UPDATE SET 
        target.TITLE = source.TITLE,
        target.ABSTRACT = source.ABSTRACT,
        target.COUNTRY_CODE = source.COUNTRY_CODE,
        target.PUBLICATION_DATE = source.PUBLICATION_DATE,
        target.SOURCE_URL = source.SOURCE_URL
WHEN NOT MATCHED THEN
    INSERT (PATENT_ID, TITLE, ABSTRACT, COUNTRY_CODE, PUBLICATION_DATE, SOURCE_URL)
    VALUES (source.PATENT_ID, source.TITLE, source.ABSTRACT, source.COUNTRY_CODE, source.PUBLICATION_DATE, source.SOURCE_URL);

-- 6. Verification Queries
SELECT COUNT(*) AS total_patents FROM RAW_PATENT_DATA;
SELECT PATENT_ID, TITLE FROM RAW_PATENT_DATA;

