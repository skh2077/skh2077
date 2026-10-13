"""YAML 설정 파일 로딩 (클라이언트/서버 공용).

문자열 값의 ``${ENV_VAR}`` 는 환경변수로 치환되므로, 비밀번호·API 키를
설정 파일에 직접 적지 않고 환경변수로 넘길 수 있다.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

M = TypeVar("M", bound=BaseModel)

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(Exception):
    """설정 파일을 읽을 수 없거나 값이 올바르지 않을 때."""


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        def repl(m: re.Match[str]) -> str:
            name = m.group(1)
            if name not in os.environ:
                raise ConfigError(f"설정에서 참조한 환경변수 {name} 가 정의되어 있지 않습니다")
            return os.environ[name]

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def load_config(path: str | os.PathLike[str], model: type[M]) -> M:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raise ConfigError(f"설정 파일이 없습니다: {path}") from None
    except yaml.YAMLError as e:
        raise ConfigError(f"설정 파일 YAML 문법 오류 ({path}): {e}") from None
    if not isinstance(raw, dict):
        raise ConfigError(f"설정 파일 최상위는 key: value 형식이어야 합니다: {path}")
    try:
        return model.model_validate(_expand_env(raw))
    except ValidationError as e:
        raise ConfigError(f"설정 값 오류 ({path}):\n{e}") from None
