# SQL Query Assistant

> Work in progress: active development

Natural-language to SQL assistant built on a LangGraph workflow. It finds the right tables, drafts SQL, validates/repairs it, executes against SQLite, and can save the run for later inspection.

## Prerequisites

- Python 3.13+ 
- Azure OpenAI credentials (endpoint, API key, deployment name)
- Input data: table card JSONs and SQLite DB files (see [setup/SETUP.md](setup/SETUP.md))

Optional: AWS Bedrock (alternative LLM), Azure AI Search (RAG retrieval), Langfuse (tracing)

## Quick start

``` 
# Clone the repository
git clone <repo-url>
cd sql_query_assistant

# Create virtual environment and install dependencies

# Using uv 
uv venv 
 
# Install from pyproject.toml
uv pip install -e .

.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# Create .env from template
copy .env.example .env        # Windows
# cp .env.example .env        # macOS/Linux

# Edit .env with your Azure OpenAI credentials (minimum required):
#    AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
#    AZURE_OPENAI_API_KEY=your-api-key
#    AZURE_OPENAI_API_VERSION=2024-02-15-preview
#    AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini

# Run
python main.py "Count all cases"
```

For full setup (Oracle export, Azure Search indexing, etc.), see [setup/SETUP.md](setup/SETUP.md).


## How it works
- Table cards are retrieved (Azure AI Search RAG when configured, otherwise a token-based fallback with FK expansion).
- A table selector LLM refines the table list.
- A drafter LLM produces SQL for the target dialect (default SQLite).
- A validator checks the SQL; a repair loop retries on failure up to `MAX_REPAIR_ATTEMPTS`.
- Execution runs in an in-memory SQLite engine with all schema DBs attached.
- Optional persistence writes CSVs and state dumps for debugging.

## Repo map (high level)
- `main.py`: CLI entrypoint.
- `app.py`: Streamlit UI.
- `src/sql_query_assistant/config.py`: Settings and env parsing.
- `src/sql_query_assistant/workflow/`: LangGraph wiring and orchestration.
- `src/sql_query_assistant/modules/`: Table retrieval, selection, drafting, validation, repair, execution.
- `src/sql_query_assistant/persistence/`: Writers for CSVs and state dumps.
- Inputs: `input/table_cards/<SCHEMA>/*.json`, `input/schemas_dir/*.db`.
- Outputs (if enabled): `output/query_runs.csv`, `output/state_dumps/run_*.json`.


## Configuration

### Required environment variables

Create `.env` from `.env.example` and set:
```
AZURE_OPENAI_ENDPOINT=your-azure-openai-endpoint
AZURE_OPENAI_API_KEY=your-azure-openai-api-key
AZURE_OPENAI_API_VERSION=2024-02-15-preview
AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
```

RAG for table cards:
```
AZURE_SEARCH_ENDPOINT=
AZURE_SEARCH_ADMIN_KEY=
AZURE_SEARCH_QUERY_KEY=
AZURE_SEARCH_TABLE_CARDS_INDEX=your_table_cards_index
AZURE_SEARCH_TOP_K=50
TABLE_CARD_CORE_COUNT=10
FK_EXPANSION_ENABLED=true
FK_EXPANSION_SOURCE_COUNT=3
FK_EXPANSION_MAX_TOTAL=25
FK_EXPANSION_INCLUDE_REVERSE=false
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small
AZURE_OPENAI_EMBEDDING_DIMENSIONS=1536
HYBRID_SEARCH_ENABLED=true
```

Optional (provider overrides per agent), for example:
```
DRAFTER_MODEL_PROVIDER=azure|aws
DRAFTER_MODEL_NAME=specific-model-name
DRAFTER_TEMPERATURE=0.0
```

Optional (other knobs):
```
TARGET_SQL_DIALECT=sqlite
MAX_REPAIR_ATTEMPTS=3
TABLE_SELECTOR_CORE_TABLES=["example_table1", "example_table2"]
TABLE_SELECTOR_NOISE_VALUE_MAPS= ["example_table2", "example_table3"]
LANGFUSE_*=...
AWS_BEDROCK_REGION=...   # plus AWS_PROFILE if using Bedrock
```

### Run from CLI
- Basic: `python main.py "Show me all female patient cases"`
- With debug logs: `python main.py "Show me all female patient cases" --debug`
- Limit schemas / override table cards dir:  
  `python main.py "query" --table-cards-dir ./input/table_cards --schemas ICSR ICSR_LOOKUP`
- Skip persistence: `python main.py "query" --no-persist`

### Run the Streamlit UI
``` 
streamlit run app.py
```
View generated SQL, execution metrics, sample rows, workflow graphs, input table cards, and prior run state dumps.

### Inputs
- Table cards: `input/table_cards/<SCHEMA>/*.json` (include FK metadata for relationship expansion).
- Schemas for execution: `input/schemas_dir/*.db` (filename stem is the schema name). To create the .db check `SETUP.md` in the `setup/` folder.

### Outputs (when persistence is enabled)
- `output/query_runs.csv`: Summary per run
- `output/state_dumps/run_*.json`: Full workflow state for replay/debugging

### Behavior notes
- Oracle-style column types in table cards are mapped to SQLite affinities when `TARGET_SQL_DIALECT=sqlite`
- Execution currently attaches all schema DBs into one in-memory SQLite connection. This will change in the future to connect directly to external DBs.
- The repair loop stops after `MAX_REPAIR_ATTEMPTS`; if validation still fails, execution is skipped and an error is returned.
