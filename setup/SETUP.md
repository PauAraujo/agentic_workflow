# Setup guide for SQL Query Assistant

Table of contents:
``` 
1) Azure setup
  - Required values
  - Types of API keys
  
2) AWS setup 
  - Prerequisites
  - Configure SSO
  - How to configure agents to use AWS
  - Troubleshooting AWS connection
 
3) Environment quickstart

4) Project setup 
  - Step 1. Export from Oracle
  - Step 2. Build SQLite database
  - Step 3. Generate table cards
  - Step 4. Enrich table cards (optional)
  - Step 5. Build Azure AI Search index
  - Typical workflow
  
5) Utilities
```

## 1) Azure setup
Login with your ZM account to the Azure Portal to create or view your assigned resource (e.g. search service `dev-dap-llm-01-srch`).

### Required values
Before running the setup scripts, ensure you have the following Azure values already configured in your `.env` file:

```
AZURE_SEARCH_ENDPOINT="https://your-search-service.search.windows.net"
AZURE_SEARCH_ADMIN_KEY="your-admin-key-here"
AZURE_SEARCH_QUERY_KEY="your-query-key-here"
AZURE_SEARCH_TABLE_CARDS_INDEX="sql_assistant_table_cards_index"
```
You can find these values in the Azure Portal:
- `AZURE_SEARCH_ENDPOINT`: From the Azure Portal, navigate to your Azure AI Search resource. Overview → Essentials → URL
- `AZURE_SEARCH_ADMIN_KEY` and `AZURE_SEARCH_QUERY_KEY` are under Settings → Keys 

Set `AZURE_SEARCH_TABLE_CARDS_INDEX` to your desired index name (default: `sql_assistant_table_cards_index`). Once set, this name should not be changed unless you plan to recreate the index.

### Types of API keys
Azure AI Search uses two types of API keys with different permission levels:

For running the application (normal use) you only need the **Query Key**. The application only searches the index (it doesn't modify it).

For setup (indexing table cards) you need the **Admin Key**. Only needed for `setup_table_cards_index.py` (creating/updating the index)


## 2) AWS setup (optional)
This guide helps you configure AWS Bedrock (Claude) for use with the SQL Query Assistant. This is optional; Azure OpenAI is the default LLM provider.

### Prerequisites

1. **AWS account** with access to AWS Bedrock
2. **AWS CLI** installed (https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
3. You must request **access to Claude models** in AWS console

### Configure SSO

1. Go to your **AWS access portal** (e.g. https://XYZ.awsapps.com/start/)
2. Sign in with your **EMA zm account**.
3. Find your AWS IAM Identity Center credentials by going to `"DAP-AI-Dev" > DAP-AI-Dev > DAPAIDevUser-PS > Access keys` 
Here you will find:
    - SSO start URL
    - SSO region
    - AWS_ACCESS_KEY_ID
    - AWS_SECRET_ACCESS_KEY
    - AWS_SESSION_TOKEN

4. In your terminal, run: `aws configure sso`
5. Create a session name, provide your IAM Identity Center start URL or the issuer URL, the AWS Region that hosts the IAM Identity Center directory, and the registration scope:
```
SSO session name (Recommended): AWS EMA
SSO start URL [None]: https://d-996712cf4e.awsapps.com/start/#
SSO region [None]: eu-central-1
SSO registration scopes [sso:account:access]: -- press Enter and click the link in incognito
```
*Tip:* If you have issues, try using an incognito/private browser window to avoid cached login problems. Generally for AWS SSO with an EMA account you will need to use eu-central-1 region. 

### How to configure agents to use AWS

In your `.env` file, configure which agents should use AWS Claude:
``` 
AWS_PROFILE="YourProfileName"
AWS_BEDROCK_REGION="eu-central-1"

# Example using Claude Sonnet 4.5 for the drafter agent
DRAFTER_MODEL_PROVIDER="aws"
DRAFTER_MODEL_NAME="eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
DRAFTER_TEMPERATURE="0.0"
``` 

**Common Claude models (as of Jan 2026):**
- `eu.anthropic.claude-opus-4-5-20251101-v1:0` - latest Sonnet (recommended)
- `eu.anthropic.claude-sonnet-4-5-20250929-v1:0` - previous Sonnet
- `eu.anthropic.claude-haiku-4-5-20251001-v1:0` - haiku (faster, cheaper)
- `eu.anthropic.claude-3-haiku-20240307-v1:0` - opus (most capable)

To see up-to date list of all available foundation models and inference profiles run: `utilities/check_bedrock_models.py`


### Troubleshooting AWS connection

#### Error: "The provided model identifier is invalid"
For AWS Bedrock, the client accepts foundation model IDs, inference profile IDs, and full ARNs; you can use whichever format your AWS setup provides. 

However, some models only support inference profiles.
If you see this error, it likely means:
you are using a foundation model ID (e.g., `anthropic.claude-*`) when only inference profiles are supported for that model (which may often be the case for newer models). Use the EU inference profile ID instead (e.g., `eu.anthropic.claude-opus-4-5-20251101-v1:0`)


For reference, a correct inference format typically looks as follows:
`eu.{provider}.{model-name}-{version}`


#### Error: "Access denied" or "Model not found"
Model may not be enabled in your AWS account or region. Run the utility script `check_bedrock_models.py` to verify which models are available.

#### Error when retrieving token from sso
If your AWS session expired, you may run into errors.

To verify your AWS SSO profile and session are live before using Bedrock, run the utility script `connect_aws_sso.py`.

You may need to login first (`aws sso login --profile <your_profile_name>`).
Click the link (*tip:* in incognito mode) and login to your EMA account.

## 3) Environment quickstart (do this first)
1) Copy `.env.example` to `.env` at project root (never commit secrets).
2) Fill these required values:
   - Azure OpenAI: 
     - `AZURE_OPENAI_ENDPOINT`
     - `AZURE_OPENAI_API_KEY`
     - `AZURE_OPENAI_API_VERSION`
     - `AZURE_OPENAI_DEPLOYMENT`.
   - Azure Search (for indexing/retrieval): 
     - `AZURE_SEARCH_ENDPOINT`
     - `AZURE_SEARCH_QUERY_KEY`
     - `AZURE_SEARCH_ADMIN_KEY`
     - `AZURE_SEARCH_TABLE_CARDS_INDEX`.
   - Oracle database (for export): 
     - `DB_HOST`
     - `DB_PORT`
     - `DB_SERVICE`
     - `DB_USER`
     - `DB_PASSWORD`
3) Optional but supported:
   - AWS Bedrock (alternate LLM): 
     - `AWS_REGION`
     - `AWS_PROFILE`
     - `AWS_BEDROCK_MAX_RETRIES`
     - `BEDROCK_MODEL_ID`.
   - Langfuse tracing: 
     - `LANGFUSE_PUBLIC_KEY`
     - `LANGFUSE_SECRET_KEY`
     - `LANGFUSE_HOST`
   - Workflow knobs (defaults are sane): 
     - `TARGET_SQL_DIALECT`
     - `MAX_REPAIR_ATTEMPTS`
     - `TABLE_SELECTOR_CORE_TABLES`
     - `TABLE_SELECTOR_NOISE_VALUE_MAPS`

## 4) Project setup
The setup process involves five main steps:

1. **Export** data and metadata from Oracle database (`export_oracle_schema.py`)
2. **Convert**  exported data into SQLite database (`build_sqlite_from_exports.py`)
3. **Generate** table card metadata files from schema information (`generate_table_cards.py`)
4. **Enrich** by adding missing descriptions to table cards (`enrich_table_cards.py`) 
5. **Index** using Azure AI Search for intelligent table retrieval (`setup_table_cards_index.py`)

### Step 1. Export from Oracle
Use `export_oracle_schema.py` to export both data and metadata from an Oracle database schema.

#### 1.1 Configuration for exporting from Oracle
Ensure your `.env` file (at project root) contains the Oracle database credentials:
```  
# Oracle Database (Setup only - for export_oracle_schema.py)
DB_HOST="your-oracle-host"
DB_PORT=1571
DB_SERVICE="your-service-name"
DB_USER="your-username"
DB_PASSWORD="your-password"
```

To customize what gets exported, edit these constants in `export_oracle_schema.py`:
```python
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
1. Finds all schema folders in `input/db_exports/`
2. Creates SQLite databases (one `.db` file per schema)
3. Imports CSV data (each CSV becomes a table in the database)
4. Preserves structure, maintaining the same table and column names

First CSV in a schema:
  - Deletes existing `.db` file (if any)
  - Creates fresh database
  - Imports table

Subsequent CSVs in same schema:
  - Opens existing database
  - Adds new table
  - Preserves existing tables

### Step 3. Generate table cards
Run `generate_table_cards.py` to create table cards from your database schema. This script:

1. Reads schema metadata from `_metadata.json` files
2. Analyzes table structures, relationships, and data types
3. Generates descriptive cards for each table
4. Saves cards as JSON files in `input/table_cards/`


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

### Step 4. Enrich table cards (optional step before indexing)

Run `enrich_table_cards.py` after `generate_table_cards.py` to fill missing descriptions from supplied Excel files.

- Inputs (defaults):
  - `input/supplied_descriptions/ev-icsr-tables.xlsx` (owner/schema, table name, comment)
  - `input/supplied_descriptions/ev-icsr-columns.xlsx` (table, column, comment)
  - Generated table cards in `input/table_cards/` (or a schema subfolder)
The script will fill missing column or table descriptions. It only updates empty descriptions; existing text is preserved.

```
python setup/enrich_table_cards.py
```

### Step 5. Build Azure AI Search index

Use `setup_table_cards_index.py` to create a searchable index of your table cards in Azure AI Search. 

#### 4.1 Prerequisites

Before running this step, you need:
1. An Azure AI Search service set up in Azure (access using your ZM account)
2. Azure credentials configured in your .env file

Add the following environment variables to your `.env` file:
``` 
# Azure AI Search Configuration
AZURE_SEARCH_ENDPOINT=https://your-search-service.search.windows.net
AZURE_SEARCH_ADMIN_KEY=your-admin-key
AZURE_SEARCH_QUERY_KEY=your-query-key
AZURE_SEARCH_TABLE_CARDS_INDEX=sql_assistant_table_cards_index
```

Where to find these values in the Azure Portal:
- `AZURE_SEARCH_ENDPOINT` 
Azure Portal → Your Search Service → Overview → URL
- `AZURE_SEARCH_ADMIN_KEY` Settings → Keys → Primary Admin Key
- `AZURE_SEARCH_QUERY_KEY` Settings → Keys → Manage Query Keys
- `AZURE_SEARCH_TABLE_CARDS_INDEX` Choose a name (default: *sql_assistant_table_cards_index*)

#### 4.2 Usage
```
# Create index and upload table cards
python setup/setup_table_cards_index.py
```

The script will:
1. Create the search index (or recreate if it exists)
2. Load all table cards from `input/table_cards/` and upload each one as a searchable document
4. Display success/failure summary

Re-run this script whenever you add or modify table cards. The script will recreate the index each time, which ensures it stays synchronized with your table cards.

### Typical workflow

#### 1. Export from Oracle
```
# Run export (usually takes 1-5 minutes depending on schema size)
python setup/export_oracle_schema.py
```
*Output:* CSV files in `input/db_exports/ICSR_LOOKUP/` and `_metadata.json` with schema structure

#### 2. Build SQLite database
```
# Import all CSVs into SQLite (usually takes seconds)
python setup/build_sqlite_from_exports.py
```
*Output:* `input/db/ICSR_LOOKUP.db` ready to query

#### 3. Generate table cards
```
# Create table card metadata files (usually takes seconds)
python setup/generate_table_cards.py
```
*Output:* JSON files in `input/table_cards/ICSR_LOOKUP/` describing each table

#### 4. Build Azure AI Search index (optional but recommended)
```
# Create and populate search index (usually takes 5-10 seconds)
python setup/setup_table_cards_index.py
```
*Output:* Searchable index in Azure AI Search for intelligent table retrieval


#### Common scenarios:

Export and build **multiple schemas** by changing `TARGET_SCHEMA` in `export_oracle_schema.py`:
```
# Edit export_oracle_schema.py: set TARGET_SCHEMA = 'SCHEMA1'
# Run for first schema
python setup/export_oracle_schema.py  # Creates db_exports/SCHEMA1/

# Edit export_oracle_schema.py: set TARGET_SCHEMA = 'SCHEMA2'
# Run for second schema
python setup/export_oracle_schema.py  # Creates db_exports/SCHEMA2/

# Build both databases at once
python setup/build_sqlite_from_exports.py  # Creates SCHEMA1.db and SCHEMA2.db

# Generate table cards for both schemas
python setup/generate_table_cards.py  # Creates table_cards/SCHEMA1/ and table_cards/SCHEMA2/

# Build search index with all schemas
python setup/setup_table_cards_index.py  # Indexes all table cards
``` 
If you only need the **schema structure** (`_metadata.json` without exporting CSV files):
```
  python setup/export_oracle_schema.py --export-metadata
``` 


Alternatively, if you want to perform **incremental updates** (i.e. adding more tables without re-exporting everything):
1. Manually add CSV files to `input/db_exports/SCHEMA_NAME/`
2. Run `python setup/build_sqlite_from_exports.py`
3. Run `python setup/generate_table_cards.py`
4. Run `python setup/enrich_table_cards.py` (if needed)
5. Run `python setup/setup_table_cards_index.py`
6. New tables are added to existing database and search index



## 5) Utilities

The `setup/utilities/` folder contains diagnostic scripts to verify connectivity and configuration, useful for troubleshooting if you encounter issues during setup.

All utility scripts load credentials from the root `.env` file - no need to edit the scripts themselves. See `setup/utilities/README.md` for detailed usage instructions.

For a complete list of utility scripts and their purposes, see `setup/utilities/README.md`.
