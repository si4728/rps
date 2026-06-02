# 가위바위보 알고리즘 대전 시스템

Flask + SQLite 기반의 2인 가위바위보 API/UI 시스템입니다. 각 PC가 하나의 플레이어로 참여하고, 사용자는 Python 전략 파일 또는 외부 API client를 통해 자신만의 알고리즘을 실험할 수 있습니다.

## 실행

```powershell
cd C:\access\rps
python app.py
```

브라우저 접속:

```text
http://127.0.0.1:8000
```

## 문서

- 일반 사용자 설명서: [USER_GUIDE.md](USER_GUIDE.md)
- 관리자 설명서: [ADMIN_GUIDE.md](ADMIN_GUIDE.md)
- 일반 사용자 도움말 API: `GET /api/help`
- 출력용 도움말 API: `GET /api/help?format=text`
- 출력용 도움말 별칭: `GET /api/help/print`

## 도움말 API

JSON 도움말:

```powershell
curl http://127.0.0.1:8000/api/help
curl "http://127.0.0.1:8000/api/help?section=api_client"
```

JSON 응답 안에 출력용 문자열까지 포함해야 하면 `include_print=1`을 붙입니다.

```powershell
curl "http://127.0.0.1:8000/api/help?include_print=1"
```

콘솔에 바로 출력하기 좋은 text 도움말:

```powershell
curl "http://127.0.0.1:8000/api/help?format=text"
curl http://127.0.0.1:8000/api/help/print
curl "http://127.0.0.1:8000/api/help?section=client&format=text"
curl "http://127.0.0.1:8000/api/help?section=api_client&format=text"
```

## Python 실행형 client

같은 PC에서 두 client를 실행할 때는 profile을 다르게 지정합니다.

첫 번째 CMD:

```powershell
python rps_client.py --profile p1 --name BotA --strategy-file strategies\best_choice_strategy.py --rounds 10
```

두 번째 CMD:

```powershell
python rps_client.py --profile p2 --name BotB --strategy-file strategies\random_strategy.py --rounds 10
```

## api_client.py 재사용

`api_client.py`는 다른 Python 코드에서 import해서 쓰는 API 래퍼입니다.

```python
from api_client import RpsApiClient

client = RpsApiClient("http://127.0.0.1:8000")
player = client.create_player("MyBot")
client.coupon_id = player["coupon_id"]

joined = client.join_match()
game_id = joined.get("game_id") or client.wait_for_game()

client.submit_choice("rock")
result = client.wait_for_next_result(game_id, 0)
print(result["latest_result"]["player_result"])
```

실행 가능한 샘플:

```powershell
python sample_api_game.py --name BotA --choice rock
python sample_api_game.py --name BotB --choice scissors
```

## 주요 파일

- `app.py`: Flask 서버, SQLite DB, 매칭/게임/API
- `rps_client.py`: 실행형 Python 게임 client
- `api_client.py`: 외부 Python 코드용 API client 모듈
- `sample_api_game.py`: `api_client.py` 사용 샘플
- `strategies/`: 사용자가 교체할 수 있는 전략 파일
- `data/rps.db`: SQLite 데이터베이스
