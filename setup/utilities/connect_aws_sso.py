import os
import boto3

from pathlib import Path
from dotenv import load_dotenv
from botocore.exceptions import BotoCoreError, ClientError

# Load environment variables from project root .env
project_root = Path(__file__).resolve().parents[2]
load_dotenv(project_root / ".env", override=True)

def main():
    try:
        profile = os.getenv("AWS_PROFILE")
        region = os.getenv("AWS_REGION", "eu-central-1") # Beware of default region

        if not profile:
            print("ERROR: AWS_PROFILE not set in .env file")
            # Troubleshooting tip: Ensure AWS SSO is configured and you have run 'aws sso login --profile <profile
            # Also note that if the AWS region is outside of EU, Bedrock calls will fail.
            return

        session = boto3.Session(profile_name=profile, region_name=region)
        sts = session.client("sts")
        who = sts.get_caller_identity()
        print("Security Token Service OK:", who)

        bedrock = session.client("bedrock")
        models = bedrock.list_foundation_models()
        print("Foundation models:", models.get("modelSummaries", []))

    except (ClientError, BotoCoreError) as e:
        print("AWS error:", e)

if __name__ == "__main__":
    main()
