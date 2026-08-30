"""Runner: listens on both numbers. One process, two legs, one policy in the middle.

Requires:
  GUAVA_API_KEY       - from https://app.goguava.ai/dashboard/api-keys
  HOUSEHOLD_NUMBER     - the number the mother dials, from the Phone Numbers dashboard
  INSTITUTION_NUMBER   - the number the judge (playing the rep) dials
"""
import os

from dotenv import load_dotenv

load_dotenv()  # must run before importing the agents: Agent() reads GUAVA_API_KEY at construction time

from guava import Runner
from guava.logging_utils import configure_logging

from scopelock.agents.household import household
from scopelock.agents.institution import institution

configure_logging()

runner = Runner()
runner.listen_phone(household, os.environ["HOUSEHOLD_NUMBER"])

institution_number = os.environ.get("INSTITUTION_NUMBER")
if institution_number:
    runner.listen_phone(institution, institution_number)
else:
    print(
        "INSTITUTION_NUMBER not set — the institution leg is not listening tonight. "
        "Buy a second number at app.goguava.ai/dashboard/phone-numbers, set it in .env, "
        "and restart to test the full A3 flow."
    )

runner.run()
