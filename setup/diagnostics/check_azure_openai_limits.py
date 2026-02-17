import os
import sys
import httpx

from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

load_dotenv(project_root / ".env", override=True)


def list_deployments(endpoint: str, api_key: str, api_version: str) -> list[dict]:
    """
    List all available Azure OpenAI deployments.

    Args:
        endpoint: Azure OpenAI endpoint URL
        api_key: Azure OpenAI API key
        api_version: API version string

    Returns:
        List of deployment dictionaries
    """
    url = f"{endpoint}/openai/deployments?api-version={api_version}"
    headers = {"api-key": api_key}

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers)

            if response.status_code == 200:
                data = response.json()
                return data.get("data", [])
            else:
                print(f"Failed to list deployments: {response.status_code}")
                print(response.text[:500])
                return []
    except httpx.RequestError as e:
        print(f"Request failed: {e}")
        return []


def check_deployment_limits(
    endpoint: str, api_key: str, api_version: str, deployment: str
) -> dict:
    """
    Check rate limits for a specific deployment by making a minimal API call.

    Args:
        endpoint: Azure OpenAI endpoint URL
        api_key: Azure OpenAI API key
        api_version: API version string
        deployment: Deployment name to check
    Returns:
        Dictionary with rate limit information
    """
    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
    headers = {"api-key": api_key, "Content-Type": "application/json"}
    payload = {"messages": [{"role": "user", "content": "Hi"}], "max_tokens": 5}

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, headers=headers, json=payload)

            return {
                "status_code": response.status_code,
                "limit_requests": response.headers.get("x-ratelimit-limit-requests"),
                "limit_tokens": response.headers.get("x-ratelimit-limit-tokens"),
                "remaining_requests": response.headers.get(
                    "x-ratelimit-remaining-requests"
                ),
                "remaining_tokens": response.headers.get(
                    "x-ratelimit-remaining-tokens"
                ),
                "region": response.headers.get("x-ms-region"),
            }
    except httpx.RequestError as e:
        return {"error": str(e)}


def check_azure_openai_limits():
    """Make a minimal API call and report rate limit headers."""
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")

    if not endpoint or not api_key:
        print("ERROR: Missing AZURE_OPENAI_ENDPOINT or AZURE_OPENAI_API_KEY in .env")
        sys.exit(1)

    endpoint = endpoint.rstrip("/")

    print("Azure OpenAI configuration:")
    print(f"Endpoint:    {endpoint}")
    print(f"Deployment:  {deployment}")
    print(f"API Version: {api_version}")
    print()

    request_url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"

    headers = {
        "api-key": api_key,
        "Content-Type": "application/json",
    }

    # Minimal request payload
    payload = {
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 5,
    }

    print("Making minimal API call to check rate limits...")
    print()

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(request_url, headers=headers, json=payload)

            print("Response status")
            print(f"Status Code: {response.status_code} {response.reason_phrase}")
            print()

            print("Rate limit headers:")

            rate_limit_headers = [
                "x-ratelimit-limit-requests",
                "x-ratelimit-limit-tokens",
                "x-ratelimit-remaining-requests",
                "x-ratelimit-remaining-tokens",
                "x-ratelimit-reset-requests",
                "x-ratelimit-reset-tokens",
                "retry-after",
                "x-ms-region",
            ]

            found_headers = False
            for header in rate_limit_headers:
                value = response.headers.get(header)
                if value:
                    found_headers = True
                    print(f"{header}: {value}")

            if not found_headers:
                print("No rate limit headers found in response")
                print("\nAll response headers:")
                for key, value in response.headers.items():
                    print(f"  {key}: {value}")

            print()
            print("Response body")

            if response.status_code == 200:
                data = response.json()
                usage = data.get("usage", {})
                print("Request succeeded!")
                print(f"Prompt tokens:     {usage.get('prompt_tokens', 'N/A')}")
                print(f"Completion tokens: {usage.get('completion_tokens', 'N/A')}")
                print(f"Total tokens:      {usage.get('total_tokens', 'N/A')}")
            elif response.status_code == 429:
                print("Rare Limited (429 too many requests)")
                print()
                try:
                    error_data = response.json()
                    error_msg = error_data.get("error", {}).get("message", "")
                    print(f"Error message: {error_msg}")
                except:
                    print(f"Raw response: {response.text[:500]}")
            else:
                print("Unexpected response:")
                print(response.text[:500])

    except httpx.RequestError as e:
        print(f"Request failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    check_azure_openai_limits()
