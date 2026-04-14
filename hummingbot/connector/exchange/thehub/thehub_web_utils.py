import time
from typing import Optional

from hummingbot.connector.exchange.thehub import thehub_constants as CONSTANTS
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTRequest
from hummingbot.core.web_assistant.rest_pre_processors import RESTPreProcessorBase
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory


class TheHubRESTPreProcessor(RESTPreProcessorBase):
    async def pre_process(self, request: RESTRequest) -> RESTRequest:
        if request.headers is None:
            request.headers = {}
        request.headers["Content-Type"] = "application/json"
        return request


def rest_url(path_url: str, base_url: str = CONSTANTS.DEFAULT_BASE_URL) -> str:
    return f"{base_url.rstrip('/')}{path_url}"


def public_rest_url(path_url: str, base_url: str = CONSTANTS.DEFAULT_BASE_URL) -> str:
    return rest_url(path_url=path_url, base_url=base_url)


def private_rest_url(path_url: str, base_url: str = CONSTANTS.DEFAULT_BASE_URL) -> str:
    return rest_url(path_url=path_url, base_url=base_url)


def chain_path(path_url: str, chain_id: int = CONSTANTS.DEFAULT_CHAIN_ID) -> str:
    if path_url.startswith("/api/orderbook/"):
        return path_url
    normalized_path = path_url if path_url.startswith("/") else f"/{path_url}"
    return f"/api/orderbook/{chain_id}{normalized_path}"


def build_api_factory(
    throttler: Optional[AsyncThrottler] = None,
    auth: Optional[AuthBase] = None,
) -> WebAssistantsFactory:
    throttler = throttler or create_throttler()
    return WebAssistantsFactory(
        throttler=throttler,
        rest_pre_processors=[TheHubRESTPreProcessor()],
        auth=auth,
    )


def build_api_factory_without_time_synchronizer_pre_processor(throttler: AsyncThrottler) -> WebAssistantsFactory:
    return WebAssistantsFactory(throttler=throttler, rest_pre_processors=[TheHubRESTPreProcessor()])


def create_throttler() -> AsyncThrottler:
    return AsyncThrottler(CONSTANTS.RATE_LIMITS)


async def get_current_server_time(throttler, domain) -> float:
    return time.time()
