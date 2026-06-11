"""Signal handling helpers — extracts SIGINT/SIGTERM setup from TaskExecutor."""

import logging
import signal

logger = logging.getLogger(__name__)


def install_handlers(executor) -> None:
    """Install SIGINT and SIGTERM handlers on *executor*.

    Calls executor._handle_signal on receipt of either signal, triggering
    graceful shutdown via executor.should_stop = True.
    """
    signal.signal(signal.SIGINT, executor._handle_signal)
    signal.signal(signal.SIGTERM, executor._handle_signal)
