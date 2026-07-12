from app.ai.contracts import AiError, AiProvider


class AiRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, AiProvider] = {}

    def register(self, provider: AiProvider) -> None:
        name = provider.name.strip().upper()
        if not name:
            raise AiError("Provider name не задан.", code="PROVIDER_NAME")
        if name in self._providers:
            raise AiError("Provider уже зарегистрирован.", code="PROVIDER_DUPLICATE")
        self._providers[name] = provider

    def provider(self, name: str) -> AiProvider:
        provider = self._providers.get(name.strip().upper())
        if provider is None:
            raise AiError("AI provider не зарегистрирован.", code="PROVIDER_NOT_FOUND")
        return provider
