import boto3
from botocore.exceptions import BotoCoreError, ClientError

PROFILE = "DAPAIDevUser..."
REGION = "eu-central-1"

def main():
    try:
        session = boto3.Session(profile_name=PROFILE, region_name=REGION)
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
