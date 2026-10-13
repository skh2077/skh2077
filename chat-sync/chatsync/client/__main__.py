from __future__ import annotations

import argparse
import logging
import signal
import sys

from chatsync.client.agent import Agent
from chatsync.client.config import ClientConfig
from chatsync.client.sender import FatalSendError, Sender
from chatsync.client.watcher import FileWatcher
from chatsync.configfile import ConfigError, load_config

log = logging.getLogger("chatsync.client")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chatsync-client", description="채팅 로그 증분 전송 클라이언트")
    parser.add_argument("-c", "--config", default="config/client.yaml", help="설정 파일 경로")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config, ClientConfig)
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2

    logging.basicConfig(
        level=config.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # 요청마다 찍히는 로그 억제

    sender = Sender(str(config.server.url), config.client_id, config.server.api_key, config.server.timeout_sec)
    agent = Agent(config, sender)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: agent.stop())

    watcher = FileWatcher(config.source_file, agent.wakeup) if config.use_file_events else None
    if watcher:
        watcher.start()
    log.info("감시 시작: %s → %s", config.source_file, config.server.url)
    try:
        agent.run()
    except FatalSendError as e:
        log.error("서버가 요청을 거부했습니다 (설정 확인 필요): %s", e)
        return 1
    finally:
        if watcher:
            watcher.stop()
        sender.close()
    log.info("종료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
