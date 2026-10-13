# chatsync

계속 내용이 추가되는 채팅 텍스트파일에서 **아직 서버로 보내지 않은 줄만** 골라 서버 DB(PostgreSQL/MySQL)에 저장합니다.

```
[채팅 텍스트파일] ─(새로 붙은 완성된 줄만)─▶ client ──HTTP POST──▶ server ──▶ PostgreSQL / MySQL
        ▲                                   │                     │
   파일 이벤트 + 폴링                state.json (전송 위치)    stream별 committed_offset
```

## 동작 원리

| 항목 | 방식 |
|---|---|
| 미전송분 판별 | 파일의 **바이트 위치(offset)**를 저장해 두고 그 뒤만 읽음 (Filebeat registry 방식[^filebeat]) |
| 쓰는 중인 줄 | `\n` 으로 끝난 줄만 전송하고, 미완성 줄은 다음 차례로 보류 |
| 위치 저장 시점 | 서버가 저장 완료를 응답한 **뒤에만** 갱신. 임시파일에 쓴 뒤 `os.replace` 로 원자적으로 교체[^replace] |
| 중복 방지 | 서버가 스트림별 `committed_offset` 을 관리하고 이미 받은 구간은 저장하지 않음. 응답이 유실돼 재전송해도 중복이 생기지 않음 |
| 누락 복구 | 요청 시작점이 서버 기록보다 뒤면 409와 함께 서버가 아는 위치를 돌려줌. 클라이언트는 그 위치부터 다시 보냄 |
| 파일 교체(로테이션) | `st_dev:st_ino` 가 바뀌면 새 파일로 판단[^stat] → 새 stream 으로 처음부터 |
| 파일 비우기 | 파일 크기가 저장 위치보다 작아지면 새 stream 으로 처음부터 |
| 상태 파일 분실 | 서버에서 같은 파일(identity)의 최근 stream 을 조회해 이어서 보냄 |
| 변경 감지 | watchdog 파일 이벤트로 즉시 반응[^watchdog]하고, 이벤트를 놓쳐도 `poll_interval_sec` 마다 폴링 |
| 서버 장애 | 재시도 간격을 지수적으로 늘림 (1s → 2s → … 최대 60s). 그동안 위치는 그대로 유지 |

## 설치

```bash
cd chat-sync
pip install -e ".[client]"                 # 채팅 PC
pip install -e ".[server,postgres]"        # 서버 (MySQL 이면 server,mysql)
```

Python 3.10 이상이 필요합니다.

## 설정

```bash
cp config/client.example.yaml config/client.yaml
cp config/server.example.yaml config/server.yaml
```

- **텍스트파일 전체 경로**: `config/client.yaml` 의 `source_file`
- **서버 주소**: `config/client.yaml` 의 `server.url`
- **서버 저장 DB**: `config/server.yaml` 의 `database_url`
- 문자열 값에 `${ENV_VAR}` 를 쓰면 환경변수로 치환됩니다. 비밀번호와 API 키는 이 방식을 권장합니다.
- 클라이언트의 `client_id` / `server.api_key` 는 서버 `api_keys` 에 등록된 값과 같아야 합니다.

## 실행

```bash
# 서버
export CHATSYNC_DATABASE_URL="postgresql+psycopg://user:pass@localhost:5432/chatsync"
export CHATSYNC_API_KEY_PC01="긴-랜덤-문자열"
python -m chatsync.server -c config/server.yaml

# 클라이언트
export CHATSYNC_API_KEY="긴-랜덤-문자열"
python -m chatsync.client -c config/client.yaml
```

테이블(`chat_streams`, `chat_messages`)은 서버를 처음 실행할 때 자동으로 생성됩니다.

## DB 스키마

| 테이블 | 주요 컬럼 |
|---|---|
| `chat_streams` | `client_id`, `stream_id`, `source_path`, `file_identity`, `committed_offset` — (client_id, stream_id) UNIQUE |
| `chat_messages` | `stream_pk`, `byte_offset`, `content`, `received_at` — (stream_pk, byte_offset) UNIQUE |

## API

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/v1/ingest` | 줄 묶음 저장. 헤더 `X-Client-Id`, `X-API-Key` |
| GET | `/api/v1/streams/lookup?file_identity=` | 상태 파일을 잃었을 때 이어 보낼 위치 조회 |
| GET | `/healthz` | 헬스 체크 |

## 테스트

```bash
pip install -e ".[dev,postgres]"
python -m pytest                     # SQLite 로 실행
CHATSYNC_TEST_DATABASE_URL="postgresql+psycopg://chatsync:chatsync@localhost/chatsync" python -m pytest
```

## 알려진 제약

- **ASCII 호환 인코딩만 지원합니다** (utf-8, cp949, euc-kr 등). UTF-16 으로 저장되는 로그는 지원하지 않습니다.
- **줄 단위로만 전송합니다.** 마지막 줄이 개행 없이 끝나면 다음 개행이 올 때까지 보내지 않습니다.
- **파일이 교체되기 직전에 추가된 미전송 줄은 놓칠 수 있습니다.** 클라이언트가 파일 핸들을 계속 열어두지 않기 때문입니다. Windows 에서 핸들을 잡고 있으면 채팅 프로그램이 파일 이름을 바꾸거나 지우지 못할 수 있어 이렇게 설계했습니다.
- `st_ino` 를 제공하지 않는 파일시스템(일부 네트워크 드라이브 등)에서는 파일 교체를 감지하지 못하고, 파일 비우기만 감지합니다.
- 네트워크 드라이브에서는 파일 이벤트가 오지 않을 수 있습니다. 이 경우에도 폴링으로 동작합니다.
- 운영 환경에서는 서버 앞에 HTTPS 리버스 프록시(nginx 등)를 두세요. API 키가 평문 HTTP 로 전송되기 때문입니다.

[^filebeat]: Elastic, *How Filebeat works* — registry 파일에 파일별 마지막 offset 을 저장하고 at-least-once 전송을 보장. https://www.elastic.co/guide/en/beats/filebeat/current/how-filebeat-works.html
[^replace]: Python docs, `os.replace` — "If successful, the renaming will be an atomic operation (this is a POSIX requirement)." https://docs.python.org/3/library/os.html#os.replace
[^stat]: Python docs, `os.stat_result.st_ino` / `st_dev` — Unix 는 inode 번호, Windows 는 파일 인덱스. https://docs.python.org/3/library/os.html#os.stat_result
[^watchdog]: watchdog — 크로스플랫폼 파일시스템 이벤트 감시 라이브러리 (inotify / FSEvents / ReadDirectoryChangesW). https://python-watchdog.readthedocs.io/
