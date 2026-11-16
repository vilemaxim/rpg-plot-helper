"""The LLM providers an Interview can use, by the name the config gives them.

The interface every adapter implements is `Provider`, in `base.py`. To add a
provider, write its adapter beside `anthropic.py` and register it here.
"""

from .anthropic import AnthropicProvider
from .base import Ended, Message, Provider, ProviderError, Text, Usage

ADAPTERS: dict[str, type[Provider]] = {
    "anthropic": AnthropicProvider,
}

__all__ = ["ADAPTERS", "Ended", "Message", "Provider", "ProviderError", "Text", "Usage"]
