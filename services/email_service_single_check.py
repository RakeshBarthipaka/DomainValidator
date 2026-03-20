import neverbounce_sdk
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("NEVERBOUNCE_API_KEY")

client = neverbounce_sdk.client(
    api_key=api_key,
    api_version="v4.2"
)


def verify_email(email):

    verification = client.single_check(
        email=email,
        address_info=True,
        credits_info=True,
        historical_data=False,
        timeout=10
    )

    return verification