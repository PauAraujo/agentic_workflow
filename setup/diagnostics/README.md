# Diagnostics guide

Quick cheatsheet for the helper scripts in this folder. All scripts assume you run them from the repo root (so they can load `.env`).

## How to run
- Activate your Python environment, then call: `python setup/diagnostics/<script_name>.py`
- Put required secrets/IDs in `.env` before running (see each script below).

## Scripts
- `check_azure_openai_limits.py` 
  - Use it to **verify keys/deployment names and see your current TPM/RPM quotas**. The script will make a tiny chat call to your Azure OpenAI deployment and prints rate-limit headers.  
  - It needs:
    - `AZURE_OPENAI_ENDPOINT`
    - `AZURE_OPENAI_API_KEY`
    - `AZURE_OPENAI_API_VERSION`
  - Targets the `gpt-4o-mini` deployment by default. Set `AZURE_OPENAI_DEPLOYMENT` to override.


- `check_embedding_connection.py`
  - Use it to **confirm the embedding path the retriever actually uses (same config as hybrid search)** and print the vector length.
  - It needs:
    - Main Azure OpenAI settings (`AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_API_VERSION`)
    - Embedding deployment name from the Azure Search config block (`AZURE_OPENAI_EMBEDDING_DEPLOYMENT`, read via `Settings.azure_search.embedding_deployment`).


- `check_azure_ai_search.py`
  - Use it to **smoke-test connectivity, keys, and confirm the index exists**. The script runs a simple "*" search against your Azure AI Search index.
  - It needs:
    - `AZURE_SEARCH_ENDPOINT`
    - `AZURE_SEARCH_QUERY_KEY`
    - `AZURE_SEARCH_TABLE_CARDS_INDEX`.


- `check_search_index.py`
  - Use it to **validate the table-card index after (re)indexing**. The script uses project settings to count documents and run a sample search over the table-cards index.
  - It needs:
    - `AZURE_SEARCH_*` values in `.env` (reads `Settings()` directly).


- `check_aws_sso.py`
  - Use it to **ensure your AWS profile and session are live before using Bedrock**. The script verifies AWS SSO profile by calling STS and listing Bedrock foundation models.
  - It needs:
    - `AWS_PROFILE`
    - `AWS_REGION` (optional, defaults to `eu-central-1`).


- `check_bedrock_models.py`
  - Use it to **find the correct model or profile ID to place in `.env`**. The script lists available Claude foundation models and inference profiles in Bedrock.
  - It needs:
    - `AWS_PROFILE`
    - `AWS_REGION` (optional, defaults to `eu-central-1`).


- `prompt_bedrock_claude.py`
  - Use it to **sanity-check Bedrock access and your chosen model ID**. The script sends a sample prompt to a Bedrock Claude model/profile and prints the reply.
  - It needs:
    - `AWS_PROFILE`
    - `AWS_REGION` (enforces `eu-central-1` unless you override)
  - Targets Claude Sonnet 4.5 by default. Set `BEDROCK_MODEL_ID` to override. `BEDROCK_PROMPT` is also optional.


- `list_table_cards.py`
  - Use it to **see an inventory of all generated table cards** organized by schema. Lists every schema folder and its tables under `input/table_cards/`.
  - It needs:
    - No environment variables required. Just run it from the repo root.


