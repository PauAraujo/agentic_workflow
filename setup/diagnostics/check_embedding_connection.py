from openai import AzureOpenAI

from sql_query_assistant.config import Settings


def main():
    settings = Settings()
    if not settings.azure_search:
        raise ValueError("Azure Search not configured (no AZURE_SEARCH_* env vars).")

    endpoint = str(settings.azure.openai_endpoint).rstrip("/")
    api_key = settings.azure.api_key
    api_version = settings.azure.api_version
    deployment = settings.azure_search.embedding_deployment

    client = AzureOpenAI(
        api_version=api_version,
        azure_endpoint=endpoint,
        api_key=api_key,
    )

    print(f"Endpoint:   {endpoint}")
    print(f"Deployment: {deployment}")
    print(f"API ver:    {api_version}")
    # print(f"API api_key:    {api_key}") # only for sanity check, not for sharing
    print("Sending a sample embedding request...\n")

    try:
        response = client.embeddings.create(
            input="hello world",
            model=deployment,
        )
        vec = response.data[0].embedding
        print(f"Success! Received embedding of length {len(vec)}.")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
