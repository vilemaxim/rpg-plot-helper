"""Whether a World is reviewed by the app's LLM after each Event, by the
scheduled `run_world_reviews` command (`interviews.world_reviewing`).

One of the settings in `llm_runs.py`: an Organization Admin sets it for the
whole Organization, off by default, and may set it for one World.
"""

from .llm_runs import RunsByItself
from .models import WorldReviewOverride

SETTING = RunsByItself("reviews_after_events", WorldReviewOverride)
