from __future__ import annotations

import argparse
import logging
import sys

import uvicorn

from chatsync.configfile import ConfigError, load_config
from chatsync.server.app import create_app
from chatsync.server.config import ServerConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chatsync-server", description="채팅 로그 수신 서버")
    parser.add_argument("-c", "--config", default="config/server.yaml", help="설정 파일 경로")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config, ServerConfig)
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2

    logging.basicConfig(
        level=config.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    uvicorn.run(create_app(config), host=config.host, port=config.port, log_level=config.log_level.lower())
    return 0


if __name__ == "__main__":
    sys.exit(main())
