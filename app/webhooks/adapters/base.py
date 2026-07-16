from abc import ABC
from abc import abstractmethod
from typing import Generic
from typing import TypeVar

from app.webhooks.models import WebhookIncident

T = TypeVar("T")


class WebhookAdapter(
    ABC,
    Generic[T],
):

    @abstractmethod
    def parse(
        self,
        request: T,
    ) -> list[WebhookIncident]:
        ...
