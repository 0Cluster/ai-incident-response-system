"""Entry point for ``python -m app.main``."""

from __future__ import annotations

import logging
import signal

from .agent import RemoteAgentRunner
from .config import AgentConfig


def main() -> int:
    config = AgentConfig.from_env()
    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    runner = RemoteAgentRunner(config)

    def _stop(signum, frame):  # noqa: ANN001
        runner.stop()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    try:
        runner.run_forever()
    finally:
        runner.client.close()
        runner.store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
