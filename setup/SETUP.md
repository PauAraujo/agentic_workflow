## Setup
The setup process involves four main steps:

1. Export - Extract data and metadata from Oracle database (`export_oracle_schema.py`)
2. Build - Convert exported data into SQLite database (`build_sqlite_from_exports.py`)
3. Generate - Create table card metadata files from schema information (`generate_table_cards.py`)
4. Index - Build Azure AI Search index for intelligent table retrieval (`setup_table_cards_index.py`)

### Step 1. Export from Oracle
Use `export_oracle_schema.py` to export both data and metadata from an Oracle database schema.

#### 1.1 Configuration for exporting from Oracle
Edit these constants at the top of the `export_oracle_schema.py` file:
``` 
# Oracle connection details
DB_HOST = 'your-oracle-host'
DB_PORT = 1571
DB_SERVICE = 'your-service-name'
DB_USER = 'your-username'
DB_PASSWORD = 'your-password'

# What to export
TARGET_SCHEMA = 'ICSR_LOOKUP'                  # Schema name you want to export
BASE_OUTPUT_DIRECTORY = '../input/db_exports'  # Output location
CSV_ROW_LIMIT = 1000                           # Max rows per table to export
```
#### 1.1.1 Usage
```
# Export both data and metadata (default)
python setup/export_oracle_schema.py

# Export only table data
python setup/export_oracle_schema.py --export-data

# Export only schema metadata
python setup/export_oracle_schema.py --export-metadata
``` 

The script:
1. Connects to Oracle database 
2. Exports table data, saving the first 1000 rows of each table as CSV files
3. Exports schema metadata, capturing complete schema structure in a JSON file


#### 1.1.2 Output structure
``` 
  input/db_exports/
  └── ICSR_LOOKUP/               # Schema name (uppercase)
      ├── COUNTRY.csv            # Table data (1000 rows max)
      ├── DOSE_FORM.csv
      ├── ...
      └── _metadata.json         # Complete schema metadata
```

### Step 2. Build SQLite database
Use `build_sqlite_from_exports.py` to convert the exported Oracle data and metadata into a local SQLite database for development and testing.

#### 2.1 Input/Output flow
``` 
  INPUT:                                 OUTPUT:
  input/db_exports/                      input/db/
  └── ICSR_LOOKUP/                       └── ICSR_LOOKUP.db
      ├── ACCESS_RIGHT.csv          →        └── Tables:
      ├── ACCESS_LEVEL.csv          →            ├── ACCESS_RIGHT
      └── PATIENT.csv               →            ├── ACCESS_LEVEL
                                                 └── PATIENT
``` 

#### 2.2 Usage
```
# Build all schemas found in input/db_exports/
python setup/build_sqlite_from_exports.py
``` 

This script:
1. Finds all schema folders in input/db_exports/
2. Creates SQLite databases (one .db file per schema)
3. Imports CSV data (each CSV becomes a table in the database)
4. Preserves structure, maintaining the same table and column names
5. 
First CSV in a schema:
  - Deletes existing .db file (if any)
  - Creates fresh database
  - Imports table

Subsequent CSVs in same schema:
  - Opens existing database
  - Adds new table
  - Preserves existing tables

### Step 3. Generate table cards
Run `generate_table_cards.py` to create table card metadata files from your database schema. This script:

1. Reads schema metadata from _metadata.json files
2. Analyzes table structures, relationships, and data types
3. Generates descriptive cards for each table
4. Saves cards as JSON files in input/table_cards/


#### 3.1 Usage
```
# Generate table cards for all schemas
python setup/generate_table_cards.py
```

#### 3.2 Output structure
```
input/table_cards/
└── ICSR_LOOKUP/
    ├── COUNTRY.json        # Table card for COUNTRY table
    ├── DOSE_FORM.json      # Table card for DOSE_FORM table
    └── ...
```

Each table card JSON file contains structured metadata that the AI can use to understand which tables are relevant for a given query.

### 4. Build Azure AI Search index

Use `setup_table_cards_index.py` to create a searchable index of your table cards in Azure AI Search. 

#### 4.1 Prerequisites

Before running this step, you need:
1. An Azure AI Search service set up in Azure (access using a ZM account)
2. Azure credentials configured in your .env file

Add these environment variables to your `.env` file:
```bash
# Azure AI Search Configuration
AZURE_SEARCH_ENDPOINT=https://your-search-service.search.windows.net
AZURE_SEARCH_ADMIN_KEY=your-admin-key
AZURE_SEARCH_QUERY_KEY=your-query-key
AZURE_SEARCH_TABLE_CARDS_INDEX=sql_assistant_table_cards_index
```

**Where to find these values:**
- `AZURE_SEARCH_ENDPOINT`: Azure Portal → Your Search Service → Overview → URL
- `AZURE_SEARCH_ADMIN_KEY`: Settings → Keys → Primary Admin Key
- `AZURE_SEARCH_QUERY_KEY`: Settings → Keys → Manage Query Keys
- `AZURE_SEARCH_TABLE_CARDS_INDEX`: Choose a name (default: *sql_assistant_table_cards_index*)

#### 4.2 Usage
```
# Create index and upload table cards
python setup/setup_table_cards_index.py
```

The script will:
1. Create the search index (or recreate if it exists)
2. Load all table cards from `input/table_cards/`
3. Upload each table card as a searchable document
4. Display success/failure summary

#### Expected output
```
Creating index 'sql_assistant_table_cards_index'...
Index 'sql_assistant_table_cards_index' created successfully
Loading table cards from disk...
Preparing 15 table cards for indexing...
Uploading documents to index 'sql_assistant_table_cards_index'...
Successfully indexed 15/15 table cards

============================================================
   Index setup complete!
   Index: sql_assistant_table_cards_index
   Endpoint: https://your-search-service.search.windows.net
============================================================
```

#### When to re-run

Re-run this script whenever you:
- Add new table cards
- Modify existing table card descriptions
- Change table structures or relationships

The script recreates the index each time, ensuring it stays synchronized with your table cards.

### Typical workflow

1. Export from Oracle
```
# Run export (usually takes 1-5 minutes depending on schema size)
python setup/export_oracle_schema.py
```
Output:
- CSV files in input/db_exports/ICSR_LOOKUP/
- _metadata.json with schema structure

2. Build SQLite database
```
# Import all CSVs into SQLite (usually takes seconds)
python setup/build_sqlite_from_exports.py
```
Output: `input/db/ICSR_LOOKUP.db` ready to query

3. Generate table cards
```
# Create table card metadata files (usually takes seconds)
python setup/generate_table_cards.py
```
Output: JSON files in `input/table_cards/ICSR_LOOKUP/` describing each table

4. Build Azure AI Search index (optional but recommended)
```
# Create and populate search index (usually takes 5-10 seconds)
python setup/setup_table_cards_index.py
```
Output: Searchable index in Azure AI Search for intelligent table retrieval


### Common scenarios

Scenario 1: Full refresh (schema changed)

Oracle schema changed and you need fresh exports:
```
# Re-export from Oracle
python setup/export_oracle_schema.py

# Rebuild database (automatically deletes old .db file)
python setup/build_sqlite_from_exports.py

# Regenerate table cards with new schema
python setup/generate_table_cards.py

# Update search index with new table cards
python setup/setup_table_cards_index.py
``` 

Scenario 2: Multiple schemas

Export and build multiple schemas:
```
# Edit export_oracle_schema.py and change TARGET_SCHEMA
# Run for first schema
python setup/export_oracle_schema.py  # Creates db_exports/SCHEMA1/

# Change TARGET_SCHEMA again
# Run for second schema
python setup/export_oracle_schema.py  # Creates db_exports/SCHEMA2/

# Build both databases at once
python setup/build_sqlite_from_exports.py  # Creates SCHEMA1.db and SCHEMA2.db

# Generate table cards for both schemas
python setup/generate_table_cards.py  # Creates table_cards/SCHEMA1/ and table_cards/SCHEMA2/

# Build search index with all schemas
python setup/setup_table_cards_index.py  # Indexes all table cards
``` 
Scenario 3: Metadata only

You only need schema structure, not data:
```
  python setup/export_oracle_schema.py --export-metadata
``` 
This creates _metadata.json without exporting CSV files. Useful for:
  - Understanding schema structure
  - Generating documentation
  - Planning queries

Scenario 4: Incremental updates

Add more tables without re-exporting everything:
1. Manually add CSV files to input/db_exports/SCHEMA_NAME/
2. Run `python setup/build_sqlite_from_exports.py`
3. Run `python setup/generate_table_cards.py`
4. Run `python setup/setup_table_cards_index.py`
5. New tables are added to existing database and search index

Scenario 5: Update table descriptions only

You improved table card descriptions and want to update the search index:
```
# Edit table card JSON files in input/table_cards/
# Then rebuild the search index
python setup/setup_table_cards_index.py
```
This is useful when you want to improve table/column descriptions for better AI understanding without re-exporting data.

### Utilities

#### Azure AI Search Connection Test

Use `utilities/connect_azure_ai_search.py` to verify connectivity to your Azure AI Search service before setting up table card indexes.

This diagnostic script checks whether you can successfully connect to Azure AI Search by running a simple query. If it works, you'll see confirmation with a sample document ID. If it fails, it provides helpful troubleshooting hints based on the error code.

**Usage:**
```
python setup/utilities/connect_azure_ai_search.py
```

**Before running:**
Edit the credentials in the script:
```python
ENDPOINT = "https://your-search-service.search.windows.net"
QUERY_KEY = "your-query-key"
INDEX_NAME = "your-index-name"
```
