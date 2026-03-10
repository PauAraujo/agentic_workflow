import os
import sys
import boto3

from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from project root .env
project_root = Path(__file__).resolve().parents[2]
load_dotenv(project_root / ".env", override=True)


def main():
    # Configuration loaded from .env
    profile = os.getenv("AWS_PROFILE")
    region = os.getenv("AWS_REGION", "eu-central-1")

    if not profile:
        print("ERROR: AWS_PROFILE not set in .env file")
        return 1

    session = boto3.Session(profile_name=profile)
    bedrock = session.client("bedrock", region_name=region)

    print("CLAUDE MODELS ONLY")

    # List foundation models (filter for Claude only)
    print("FOUNDATION MODELS (Claude only):")
    response = bedrock.list_foundation_models()

    for model in sorted(response["modelSummaries"], key=lambda x: x["modelName"]):
        if "claude" in model["modelId"].lower():
            print(f"\n✓ {model['modelName']}")
            print(f"  Model ID: {model['modelId']}")
            print(f"  Provider: {model['providerName']}")
            print(f"  Inference Types: {model.get('inferenceTypesSupported', [])}")
            print(f"  Status: {model['modelLifecycle']['status']}")

    # List inference profiles (filter for Claude only)
    print("\n\nINFERENCE PROFILES (Claude only):")
    response = bedrock.list_inference_profiles()

    for profile in sorted(
        response["inferenceProfileSummaries"], key=lambda x: x["inferenceProfileName"]
    ):
        if "claude" in profile["inferenceProfileId"].lower():
            print(f"\n✓ {profile['inferenceProfileName']}")
            print(f"  Profile ID: {profile['inferenceProfileId']}")
            print(f"  Status: {profile['status']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
