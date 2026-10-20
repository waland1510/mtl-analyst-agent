"""Azure mode: Foundry through the Agent Framework's chat-completion client, Entra credentials only, no keys."""

from __future__ import annotations

import os
from dataclasses import dataclass

from azure.identity import AzureCliCredential, DefaultAzureCredential


@dataclass(frozen=True, slots=True)
class AzureSettings:
    endpoint: str
    deployment: str
    api_version: str = "2024-10-21"
    cli_subscription: str | None = None

    @classmethod
    def from_env(cls) -> AzureSettings:
        endpoint = os.environ.get("MTL_FOUNDRY_ENDPOINT")
        deployment = os.environ.get("MTL_CHAT_DEPLOYMENT")
        if not endpoint or not deployment:
            raise RuntimeError("MTL_FOUNDRY_ENDPOINT and MTL_CHAT_DEPLOYMENT are required in azure mode.")
        return cls(endpoint, deployment, cli_subscription=os.environ.get("MTL_AZURE_CLI_SUBSCRIPTION"))


def credential(settings: AzureSettings):
    """Locally the CLI identity is pinned to one subscription, which implies the tenant that owns the resources."""
    if settings.cli_subscription:
        return AzureCliCredential(subscription=settings.cli_subscription)
    return DefaultAzureCredential()


def chat_client(settings: AzureSettings):
    from agent_framework.openai import OpenAIChatCompletionClient

    return OpenAIChatCompletionClient(
        model=settings.deployment,
        azure_endpoint=settings.endpoint,
        api_version=settings.api_version,
        credential=credential(settings),
    )
