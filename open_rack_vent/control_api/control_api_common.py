"""Common code shared between the different external control APIs"""

from typing import Callable, NamedTuple


class APIController(NamedTuple):
    """
    Abstraction to manage the different external control APIs.
    """

    non_blocking_run: Callable[[], None]
    stop: Callable[[], None]
