# SQL Query Assistant

> Work in progress: active development 

Converts natural language queries to SQL using a LangGraph workflow with validation, repair, execution, and persistence.

## Overview
This tool takes a natural language query and processes it through:
1. **Table card retriever**: uses RAG to select relevant tables via Azure AI Search (to be configured)
2. **Interpreter**: selects relevant assumptions and builds an intent card
3. **SQL drafter**: generates a SQL draft from intent + schema
4. **SQL validator**: checks SQL validity
5. **SQL repairer**: retries draft when validation fails (looped up to a limit)
6. **SQL executor**: runs SQL against the configured database
7. **Persistence** (optional): saves run artifacts for debugging

### RAG-Based Table Selection

The tool will support intelligent table selection using Azure AI Search. 
Instead of loading all table cards into the LLM context, the RAG (Retrieval-Augmented Generation) retriever will:
- Searches indexed table cards using semantic search
- Selects only the most relevant tables for the query
- Improves LLM focus on relevant tables

## Input requirements
- Table cards (JSON files describing database schema)
  - Organized by schema directory: `input/table_cards/SCHEMA_NAME/*.json`
- Assumption catalog (YAML file with query assumptions)
  - Default path: `input/assumptions_catalog/assumptions_catalog.yaml`

## Installation

```bash
pip install -e .
```

## Usage

### Basic Usage

```bash
python main.py "Show me all active users"
```

### Command-Line Flags

| Flag | Description |
|------|-------------|
| `query` | Natural language query to convert to SQL (positional argument) |
| `--debug` | Enable debug logging |
| `--render-graph` | Render the workflow graph to a PNG and exit (no execution) |
| `--render-graph-path PATH` | Optional output path for the rendered workflow graph PNG |
| `--table-cards-dir PATH` | Override path to table cards directory |
| `--schemas SCHEMA ...` | Schema names to load table cards from (defaults to all schema subdirs) |
| `--assumptions-file PATH` | Override path to assumptions catalog YAML file |
| `--no-persist` | Skip writing outputs to disk |

### Examples

**With debug logging:**
```bash
python main.py "Show me all count of female patient cases" --debug
```

**Custom table cards directory + schemas:**
```bash
python main.py "Show me all count of female patient cases" --table-cards-dir ./input/table_cards --schemas ICSR ICSR_LOOKUP
```

**Render the workflow graph (no execution):**
```bash
python main.py --render-graph --render-graph-path ./output/graphs/main_graph.png
```

**Skip persistence:**
```bash
python main.py "Show me all count of female patient cases" --no-persist
```

**All options combined:**
```bash
python main.py "Show me all count of female patient cases" \
  --debug \
  --table-cards-dir ./input/table_cards \
  --schemas ICSR ICSR_LOOKUP \
  --assumptions-file ./input/assumptions_catalog/assumptions_catalog.yaml \
  --no-persist
```

## Workflow

The workflow is built using [LangGraph](https://langchain-ai.github.io/langgraph/) and currently consists of these modules:

```
User Query -> Interpreter -> SQL Drafter -> SQL Validator -> SQL Repairer (loop) -> SQL Executor -> Persistence (optional)
```

### 1. Interpreter module
Analyzes user query and selects relevant assumptions

*Nodes*:
- `interpret_query`: Analyzes the user query against table metadata and assumption catalog
- `build_intent_card`: Builds a structured `IntentCard` with task and selected assumptions

*Input*: User query, table cards, assumption catalog

*Output*: Intent card with selected assumptions

### 2. SQL Drafter module
Generates SQL query based on interpreted intent

*Nodes*:
- `draft_sql`: Generates SQL using the intent card and table metadata

*Input*: Intent card, table cards

*Output*: SQL draft with rationale and tables used

### 3. SQL Validator module
Validates the drafted SQL

*Nodes*:
- `validate_sql`: Validates SQL syntax and compatibility with the target dialect

*Input*: SQL draft
*Output*: Validation result


### 4. SQL Repairer module
Repairs SQL when validation fails

*Nodes*:
- `repair_sql`: Attempts to fix SQL based on validator feedback

*Input*: SQL draft + validation errors
*Output*: Repaired SQL draft

### 5. SQL Executor module
Executes SQL against the configured database

*Nodes*:
- `execute_sql`: Runs SQL and returns row count or error

*Input*: Valid SQL draft
*Output*: Query result

### 6. Persistence module (Optional)
Saves workflow results for debugging and tracking

*Nodes*:
- `persist_results`: Saves intent card, SQL draft, query result, and full workflow state to disk

*Input*: Complete workflow state
*Output*: Saved results with run ID

### Workflow state

The workflow maintains a `WorkflowState` that flows through all modules:
- `user_query`: Original natural language query
- `table_cards`: Database schema metadata
- `assumption_catalog`: Available query assumptions and options
- `selected_assumptions`: Assumptions chosen by interpreter
- `intent_card`: Structured interpretation of user intent
- `sql_draft`: Generated SQL query with rationale
- `validation_result`: Result of SQL validation
- `query_result`: Execution result (success, row count, errors)
- `run_id`: Unique identifier for persisted results (if persistence enabled)

## Output

The workflow outputs:
- **Intent card**: Interpreted query intent with selected assumptions and rationale
- **SQL draft**: Generated SQL query with explanation of logic and tables used
- **Query result**: Execution outcome (row count or error)

When persistence is enabled (default), results are saved with a unique run ID for later review.

## Configuration

- Target SQL dialect: `TARGET_SQL_DIALECT` (default: `sqlite`)
  - When target is SQLite, Oracle-style column types in table cards are mapped to SQLite.
- Per-agent model configuration via env vars:
  - `INTERPRETER_MODEL_PROVIDER`, `INTERPRETER_MODEL_NAME`, `INTERPRETER_TEMPERATURE`
  - `DRAFTER_MODEL_PROVIDER`, `DRAFTER_MODEL_NAME`, `DRAFTER_TEMPERATURE`
  - `REPAIRER_MODEL_PROVIDER`, `REPAIRER_MODEL_NAME`, `REPAIRER_TEMPERATURE`
- Supported providers: Azure OpenAI (default) and AWS Bedrock

## Project Structure
```
sql_query_assistant/
  main.py
  src/sql_query_assistant/
    config.py
    state.py
    llm_client.py
    domain/
    modules/
      interpreter/
      sql_drafter/
      sql_validator/
      sql_repairer/
      sql_executor/
    persistence/
    utils/
    workflow/
  input/
    table_cards/
    assumptions_catalog/
  output/
    query_runs.csv
    query_assumptions.csv
    state_dumps/
  tests/
```

## AWS Bedrock Setup (Optional)

This guide helps you configure AWS Bedrock (Claude) for use with the SQL Query Assistant.

### Prerequisites

1. AWS account with access to AWS Bedrock
2. AWS CLI installed: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
3. Bedrock model access (request access to Claude models in AWS console)

### Configure SSO

1. Go to your AWS access portal (e.g. https://XYZ.awsapps.com/start/)
2. Sign in with your account.
3. Find your AWS IAM Identity Center credentials by going to "DAP-AI-Dev" > "DAP-AI-Dev" > "DAPAIDevUser-PS" > Access keys
   - SSO start URL
   - SSO region
   - AWS_ACCESS_KEY_ID
   - AWS_SECRET_ACCESS_KEY
   - AWS_SESSION_TOKEN
4. In your terminal, run:

```
aws configure sso
```

5. Create a session name, provide your IAM Identity Center start URL or issuer URL, the AWS Region that hosts the IAM Identity Center directory, and the registration scope:

```
SSO session name (Recommended): AWS EMA
SSO start URL [None]: https://d-996712cf4e.awsapps.com/start/#
SSO region [None]: eu-central-1
SSO registration scopes [sso:account:access]: -- press Enter and click the link in incognito
```

6. In your `.env` file, set:

```bash
AWS_BEDROCK_REGION="eu-central-1"
AWS_PROFILE="your-profile-name"
```

### Login to SSO

```
aws sso login --profile <profile name>
```

Replace `<profile name>` with your profile name. Click the link (in incognito) and login.

### Configure Agents to use AWS

In your `.env` file, configure which agents should use AWS Claude:

```bash
# Example: Use AWS Claude for the drafter agent
DRAFTER_MODEL_PROVIDER="aws"
DRAFTER_MODEL_NAME="anthropic.claude-3-5-sonnet-20241022-v2:0"
DRAFTER_TEMPERATURE="0.0"
```

### Choosing Claude models
Available Claude models:
- `anthropic.claude-3-5-sonnet-20241022-v2:0` - latest Sonnet (recommended)
- `anthropic.claude-3-5-sonnet-20240620-v1:0` - previous Sonnet
- `anthropic.claude-3-haiku-20240307-v1:0` - haiku (faster, cheaper)
- `anthropic.claude-3-opus-20240229-v1:0` - opus (most capable)

To list all available models:
```
aws bedrock list-foundation-models --region eu-central-1 --profile <your_profile_name>
```
