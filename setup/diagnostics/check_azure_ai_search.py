import os

from pathlib import Path
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.core.exceptions import HttpResponseError

# Load environment variables from project root .env
project_root = Path(__file__).resolve().parents[2]
load_dotenv(project_root / ".env", override=True)

ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT", "")
QUERY_KEY = os.getenv("AZURE_SEARCH_QUERY_KEY", "")
INDEX_NAME = os.getenv("AZURE_SEARCH_TABLE_CARDS_INDEX", "")


def test_connection():
    print(f"Testing connection to: {ENDPOINT}...")

    try:
        # Initialize the client
        client = SearchClient(
            endpoint=ENDPOINT,
            index_name=INDEX_NAME,
            credential=AzureKeyCredential(QUERY_KEY),
        )

        # Run a simple search for "*" (match all) and get just 1 result
        results = client.search(search_text="*", top=1)

        print("\nConnection Successful!")

        count = 0
        for result in results:
            count += 1
            print(f"   Found document with ID: {result.get('id', 'No ID field found')}")

        if count == 0:
            print("   (Connection worked, but the index is empty.)")

    except HttpResponseError as e:
        print("\nConnection FAILED.")
        print(f"   Status Code: {e.status_code}")
        print(f"   Message: {e.message}")

        if e.status_code == 403:
            print("\n Tip: 403 usually means your API Key is wrong.")
        elif e.status_code == 404:
            print(f"\n Tip: 404 usually means the index '{INDEX_NAME}' doesn't exist.")


if __name__ == "__main__":
    test_connection()
