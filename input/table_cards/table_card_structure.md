# Table card structure and design rationale
This project uses "table cards" as compact JSON summaries of each database table. Each card captures not just the technical schema information (column names, data types, constraints) but also the semantic context that makes a table useful for answering natural language questions. This reduces the ambiguity that raw DDL often introduces.

The design philosophy behind table cards is straightforward: when a user asks a question like "How many adverse events were reported for elderly female patients?", the system needs to understand that `ICSR.PATIENT` contains patient demographics, that `PATIENT_AGE_GROUP_ID` maps to age categories including "Elderly", and that the `PATIENT_SEX_ID` column distinguishes between male and female patients. The table card encodes all of this knowledge in a structured format that can be retrieved, ranked, and fed into an LLM for SQL generation. 

## Table of contents
- [What a table card contains](#what-a-table-card-contains)
  - [Value maps structure](#value-maps-structure)
- [Why the value_map design](#why-the-value_map-design)
  - [Importance of value maps](#importance-of-value-maps)
  - [Threshold rationale](#threshold-rationale)
  - [Why value maps live in referencing tables](#why-value-maps-live-in-referencing-tables)
  - [Example: filtering on country](#example-filtering-on-country)
  - [Example: filtering on dose form](#example-filtering-on-dose-form)
- [Generation and maintenance](#generation-and-maintenance)
- [Why this structure works well for text-to-SQL](#why-this-structure-works-well-for-text-to-sql)
- [Future improvements](#future-improvements)
  - [Generalizing lookup schema support](#future-generalizing-lookup-schema-support)
  - [ReACT agent fallback](#future-react-agent-fallback)
  - [Potential indexing enhancement](#future-potential-indexing-enhancement)



## What a table card contains

Each file has three top-level sections.

1. The `table_metadata` block names and describes the table at a high level. It includes the qualified name (schema and table), the primary key, a row count, and a short description. This helps retrieval and ranking, especially when table names are generic or repeated across schemas. The row count helps the LLM make informed decisions about query performance, particularly when deciding whether to use aggregations or apply filtering conditions. It can also help an LLM decide which table is likely to be the fact table versus a small lookup.


2. The `columns` array is the heart of the card. Each column carries its name, type, nullability, and a human description. Optional fields add relationships (`fk`) and controlled vocabulary hints (`value_map_ref`). The design keeps the column record flat so it is easy to scan in a prompt, and it treats foreign keys as first-class metadata because joins are the most common source of errors in text-to-SQL.

3. The `value_maps` are embedded lookup table metadata within table cards. EudraVigilance, like many pharmacovigilance databases, uses extensive lookup tables to standardize coded values. Value maps enable the LLM to understand these coded columns.

*Note: Value maps matter most when the model needs semantic grounding for coded fields. Although value maps aren’t universally necessary, for a regulated, code‑heavy schema like EV they can be a practical safety net.*


### Value maps structure
Value maps use a threshold-based approach where the presence or absence of `_value_column` serves as a semantic signal:

**Complete lookup (≤500 rows)**, all values embedded, no `_value_column`:
```json
"COUNTRY": {
  "_count": 259,
  "1": "Afghanistan",
  "2": "Albania",
  ...
  "259": "Zimbabwe"
}
```

**Sampled lookup (>500 rows)**, 20 samples with `_value_column`:
```json
"DOSE_FORM": {
  "_count": 1075,
  "_value_column": "NAME",
  "1": "TABLET",
  "2": "CAPSULE",
  ...
}
```
`_count` is the total number of values in the lookup table. This tells the LLM whether it's dealing with a small controlled vocabulary (like sex with 2 values) or a large reference table (like dose forms with over a thousand entries).

`_value_column` indicates which column in the lookup table contains the human-readable text. The rule for the LLM is simple:
- `_value_column` **absent**: all values are shown, use the ID directly
- `_value_column` **present**: only samples shown, JOIN on that column if the needed value isn't listed


## Why the `value_map` design

### Importance of value maps
The importance of value maps becomes especially clear for cryptically-named columns. Consider `DOSAGE.ROA_ID`, where the abbreviation "ROA" gives little away. An LLM encountering this column cannot easily determine whether it's relevant to a query about "oral medications." But the embedded `value_map` immediately clarifies: this is the Route of Administration, with values like `"Oral"`, `"Buccal"`, `"Cutaneous"`, `"Intravenous"`. The Table Selector can now make an informed decision, and the SQL drafter knows that "oral" translates to a specific ID.

Similarly, columns ending in `_NF_ID` (such as `CITY_NF_ID` or `BIRTH_DATE_NF_ID`) are opaque without context. The `value_map` reveals these reference `NULL_FLAVOUR` (an HL7 standard for representing missing or masked data) with values like `"Masked"`, `"Asked but unknown"`, and `"Not applicable"`.

### Threshold rationale
The threshold of 500 rows was chosen to cover "user-facing" lookups where exact value matching matters:

| Lookup                  | Rows       | Treatment                                       |
|-------------------------|------------|-------------------------------------------------|
| `PATIENT_SEX`           | 2          | Complete. LLM sees `"Male"`, `"Female"`         |
| `PATIENT_AGE_GROUP`     | 7          | Complete. LLM sees `"Elderly"`, `"Adult"`, etc. |
| `COUNTRY`               | 259        | Complete. LLM sees all country names            |
| `OUTCOME`               | ~6         | Complete. LLM sees all outcome types            |
| `MEDDRA_PREFERRED_TERM` | 1,000,000+ | Sampled, must JOIN for text filtering           |

For lookups like `COUNTRY`, having all 259 values embedded means the LLM can resolve "Netherlands" vs "The Netherlands" vs "Holland" without guessing. This improves query accuracy for the class of lookups users commonly mention in natural language.

For truly large lookups like MedDRA terms, full embedding is impractical. The `_value_column` hint tells the LLM exactly which column to JOIN on when building text-based filters.

Value maps are deduplicated at the table level, so `COUNTRY` is embedded once even if multiple columns reference it. 
The threshold of 500 balances query accuracy against prompt size. Lookups above this size would add significant tokens for diminishing returns.

### Why value maps live in referencing tables

An alternative design would place value maps in the lookup table cards themselves (`PATIENT_SEX.json` would contain its own value map) rather than embedding them in referencing tables (`PATIENT.json` contains the `PATIENT_SEX` value map). We chose embedding for robustness.

Consider what happens when a user asks "How many female patients reported adverse events?":

**Current design (embedded in referencing tables):**
1. RAG retrieves `PATIENT` (good semantic match on "patients")
2. `PATIENT` card contains `value_maps.PATIENT_SEX` showing `{1: Male, 2: Female}`
3. LLM immediately knows to filter on `PATIENT_SEX_ID = 2`

**Alternative design (value maps in lookup tables):**
1. RAG retrieves `PATIENT` (good semantic match on "patients")
2. `PATIENT` card has FK reference but no value information
3. System must also retrieve `PATIENT_SEX` lookup table
4. LLM must cross-reference two cards to understand the column

The alternative creates a hard dependency on lookup table retrieval. If FK expansion is disabled, hits its limit, or the lookup table isn't retrieved for any reason, the LLM has no way to understand what the coded values mean.

The embedded design degrades gracefully:

| Failure mode           | Embedded (current) | In Lookup tables              |
|------------------------|-------------------|-------------------------------|
| RAG misses lookup      | Value map still available | No value context              |
| FK expansion disabled  | Works normally | Broken                        |
| FK expansion limit hit | Partial degradation | Critical lookups missing      |
| LLM context confusion  | Self-contained, less cross-referencing | Must correlate multiple cards |

For a system used by the EMA, robustness matters more than avoiding some data duplication. The current design ensures that when a table is retrieved, all the context needed to query it is immediately available.

The duplication cost is acceptable: value maps are deduplicated within each table card (if five columns reference `NULL_FLAVOUR`, it appears once in `value_maps`), table cards are generated rather than manually maintained, and modern context windows easily handle the overhead.

In short, we keep value maps in referencing tables (current design) because self-contained context reduces LLM reasoning errors. 


### Example: filtering on country

User asks: "Reports from the Netherlands"

The `SAFETY_REPORT` table card includes:
```json
"value_maps": {
  "COUNTRY": {
    "_count": 259,
    "157": "Netherlands",
    ...all 259 countries...
  }
}
```

No `_value_column` is present, signaling completeness. The LLM finds "Netherlands" directly and generates:
```sql
WHERE sr.PRIMARY_SOURCE_COUNTRY_ID = 157
```

No JOIN required. The exact country name is visible, eliminating ambiguity.

### Example: filtering on dose form

User asks: "Reports where the drug was administered as an injection"

The DOSAGE table card includes:
```json
"value_maps": {
  "DOSE_FORM": {
    "_count": 1075,
    "_value_column": "NAME",
    "1": "TABLET",
    "2": "CAPSULE",
    ...20 samples...
  }
}
```

The `_value_column` presence signals that this is incomplete. If "INJECTION" isn't in the 20 samples shown, the LLM generates:
```sql
JOIN ICSR_LOOKUP.DOSE_FORM df ON dos.DOSE_FORM_ID = df.DOSE_FORM_ID
WHERE df.NAME LIKE '%INJECTION%'
```

The `_value_column` hint ensures the JOIN uses the correct column for text filtering.



## Generation and maintenance

Table cards are generated from Oracle database metadata exports. The generation process extracts schema information (tables, columns, constraints, foreign keys) and combines it with human-authored descriptions from a separate documentation source. Value maps are populated by reading the actual lookup table data, applying the threshold logic to decide between full embedding and sampling.

The generation script filters out operational tables (temporary staging tables, audit logs, system configuration) that are not useful for end-user queries. This keeps the table card collection focused on the tables that matter for analytical questions.


## Why this structure works well for text-to-SQL

The structure is deliberately compact but semantically rich. It reduces the chance of hallucinated columns by showing only what exists, while still giving enough context to pick the right table and the right join path. In EV, where the schema is wide and has many similarly named fields across schemas, the combination of descriptions, foreign keys, and value maps is what keeps the model grounded.

## Future improvements
### *Future:* Generalizing lookup schema support

*Important limitation:* the code is hardcoded to only generate value maps for `ICSR_LOOKUP` references.

If a schema has lookups in a different schema, the code wouldn't handle it.

Options to generalize: 
1. Configuration-base, to allow specifying multiple lookup schemas in settings                                                           
```
LOOKUP_SCHEMAS = ["ICSR_LOOKUP", "ICSR_EMA_LOOKUP"]  # configurable
```

2. Heuristic-based, to detect lookup tables by pattern (small row count, ID+NAME columns, referenced by FKs)

For a more general text-to-SQL system the hardcoding would be a limitation. A configuration-driven approach would be cleaner.  



### *Future:* ReACT agent fallback

For sampled lookups where the needed value isn't in the samples, a future ReACT-style agent could:
1. Recognize that the value map is incomplete (via `_value_column` presence)
2. Query the database directly to fetch matching values
3. Retry SQL generation with the resolved ID

This would handle edge cases where sampling misses the needed value, while keeping the common case fast (no database round-trip for complete lookups or lucky sample hits).

This could also become relevant for running a post-hoc correction loop if the generated SQL fails execution or returns unexpected results: 
1. Generate SQL with current system
2. Execute
3. If error or suspicious results: ReACT agent investigates
4. Agent can query database for missing values, verify lookups, adjust SQL
5. Retry

### *Future:* potential indexing enhancement

In the future, we could keep embedded value maps in referencing tables (as is currently the case). But then, additionally, we could consider indexing lookup table cards with their value content.

This way "reports from Netherlands" might directly retrieve `COUNTRY` lookup as bonus context. 
But this is additive, not a replacement. 


