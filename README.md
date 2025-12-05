# SQL Query Assistant

> **⚠️ Work in Progress**: This project is under active development.

Converts natural language queries to SQL using an agentic workflow powered by LangGraph and OpenAI.

## Overview
This tool takes a natural language query (e.g., "Show me all active users from last month") and converts it into structured SQL by:
1. Interpreting user intent and selecting relevant assumptions
2. Generating a SQL draft based on available database schema
3. Optionally persisting results for debugging and tracking

## Input requirements
- Table cards (JSON files describing database schema)
- Assumption catalog (YAML file with query assumptions)

## Installation

```bash
pip install -e .
```

## Usage

### Basic Usage

```bash
python main.py "Show me all active users"
```

Or run without arguments for interactive mode:

```bash
python main.py
# Enter your query:
```

### Command-Line Flags

| Flag | Description |
|------|-------------|
| `query` | Natural language query to convert to SQL (positional argument) |
| `--debug` | Enable debug logging |
| `--table-cards-dir PATH` | Override path to table cards directory |
| `--assumptions-file PATH` | Override path to assumptions catalog YAML file |
| `--no-persist` | Skip writing outputs to disk |

### Examples

**With debug logging:**
```bash
python main.py "Show me all count of cases" --debug
```

**Custom table cards directory:**
```bash
python main.py "Show me all count of cases" --table-cards-dir /path/to/cards
```

**Skip persistence:**
```bash
python main.py "Show me all count of cases" --no-persist
```

**All options combined:**
```bash
python main.py "Show me all count of cases" \
  --debug \
  --table-cards-dir ./custom/cards \
  --assumptions-file ./custom/assumptions.yaml \
  --no-persist
```

## Workflow

The workflow is built using [LangGraph](https://langchain-ai.github.io/langgraph/) and currently consists of three main modules executed sequentially:

```
User Query → Interpreter → SQL Drafter → Persistence
```

### 1. Interpreter module

**Purpose**: Analyze user query and select relevant assumptions

**Nodes**:
- `interpret_query`: Uses LLM to analyze the user query against table metadata and assumption catalog to determine which assumptions are relevant
- `build_intent_card`: Constructs a structured `IntentCard` containing the task and selected assumptions with rationale

**Input**: User query, table cards, assumption catalog
**Output**: Intent card with selected assumptions

### 2. SQL Drafter module

**Purpose**: Generate SQL query based on interpreted intent

**Nodes**:
- `draft_sql`: Uses LLM to generate SQL query using the intent card and table metadata

**Input**: Intent card, table cards
**Output**: SQL draft with query, rationale, and tables used

### 3. Persistence module (Optional)

**Purpose**: Save workflow results for debugging and tracking

**Nodes**:
- `persist_results`: Saves intent card, SQL draft, and full workflow state to disk with unique run ID

**Input**: Complete workflow state
**Output**: Saved results with run ID

### Workflow state

The workflow maintains a `WorkflowState` that flows through all modules:
- `user_query`: Original natural language query
- `table_cards`: Database schema metadata
- `assumption_catalog`: Available query assumptions and options
- `selected_assumptions`: Assumptions chosen by interpreter
- `intent_card`: Structured interpretation of user intent
- `sql_draft`: Generated SQL query with rationale
- `run_id`: Unique identifier for persisted results (if persistence enabled)

## Output

The workflow outputs:
- **Intent card**: Interpreted query intent with selected assumptions and rationale
- **SQL draft**: Generated SQL query with explanation of logic and tables used

When persistence is enabled (default), results are saved with a unique run ID for later review.

## Project Structure

```
sql_query_assistant/
├── main.py                          # CLI entry point
├── src/sql_query_assistant/
│   ├── config.py                    # Settings and configuration
│   ├── state.py                     # WorkflowState definition
│   ├── llm_client.py                # OpenAI LLM client wrapper
│   ├── domain/                      # Domain models (IntentCard, SQLDraft, etc.)
│   └── modules/                     # Workflow modules
│       ├── interpreter/             # Query interpretation module
│       │   ├── graph.py             # Subgraph definition
│       │   ├── nodes.py             # Node implementations
│       │   ├── prompts.py           # LLM prompts
│       │   └── models.py            # Pydantic models
│       ├── sql_drafter/             # SQL generation module
│       │   ├── graph.py
│       │   ├── nodes.py
│       │   ├── prompts.py
│       │   └── models.py
│       └── persistence/             # Result persistence module
│           ├── graph.py
│           ├── nodes.py
│           └── service.py           # Persistence logic
└── tests/                           # Test suite
```

