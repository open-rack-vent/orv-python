"""
Canonical threading Events.
"""

import logging
import signal
from threading import Event as SignalEvent
from types import FrameType
from typing import Optional

LOGGER = logging.getLogger(__name__)


def create_signal_event() -> SignalEvent:
    """
    Create a stop event. This is like a `multiprocessing.Event`.
    Should only be consumed in the main thread or a signal handler. If you pass to a child process
    it will not work as expected.
    :return: The event.
    """

    return SignalEvent()


def entry_point_exit_condition(signal_event: Optional[SignalEvent] = None) -> None:
    """
    Create the exit condition that responds to the SIGHUP, SIGTERM and SIGINT signals.
    :param signal_event: If given, this will be set upon receiving one of the shutdown signals.
    :return: None
    :raises ValueError: If the wrong signal event type is given.
    """

    if not isinstance(signal_event, SignalEvent):
        raise ValueError("Using a multiprocessing.Event in a signal handler leads to deadlock.")

    def trigger_quit(  # pylint: disable=unused-argument, no-member
        signal_number: Optional[int], frame: Optional[FrameType]
    ) -> None:
        """
        Set the internal current entry point flag that signals the application to shutdown.
        :param signal_number: The signal number provided by signal.
        :param frame: The calling frame provided by signal. We do not consume this
        :return: None
        """
        # Ignore additional signals
        signal.signal(signal_number, getattr(signal, "SIG_IGN"))
        del frame
        LOGGER.info("Interrupted by signal number %d, shutting down", signal_number)

        if signal_event is not None:
            signal_event.set()

    signal.signal(getattr(signal, "SIGINT"), trigger_quit)
    signal.signal(getattr(signal, "SIGTERM"), trigger_quit)
    signal.signal(getattr(signal, "SIGHUP"), trigger_quit)
