# 일반 사용자 설명서

이 시스템은 여러 컴퓨터가 API로 가위바위보 게임에 참여하고, 각 사용자가 자신의 컴퓨터에 전략 알고리즘을 넣어 승률을 실험하는 프로젝트입니다.

관리자용 운영 문서는 [ADMIN_GUIDE.md](ADMIN_GUIDE.md)를 확인하세요.

## 1. 서버 실행

```powershell
cd C:\access\rps
python app.py
```

브라우저:

```text
http://127.0.0.1:8000
```

## 2. Web UI 사용

1. 브라우저에서 `http://127.0.0.1:8000` 접속
2. 이름 입력 후 입장
3. 로비에서 매칭 시작 또는 초대 매칭 사용
4. `rock`, `paper`, `scissors` 중 하나 선택
5. 결과, 전적, 개인 분석 확인

## 3. 도움말 API

일반 사용자 도움말은 서버 API로도 제공합니다.

JSON:

```powershell
curl http://127.0.0.1:8000/api/help
curl "http://127.0.0.1:8000/api/help?section=client"
curl "http://127.0.0.1:8000/api/help?section=api_client"
```

JSON 응답 안에 출력용 도움말 문자열까지 포함해야 하면 `include_print=1`을 사용합니다.

```powershell
curl "http://127.0.0.1:8000/api/help?include_print=1"
```

콘솔에 바로 출력하기 좋은 print/text 버전:

```powershell
curl "http://127.0.0.1:8000/api/help?format=text"
curl http://127.0.0.1:8000/api/help/print
curl "http://127.0.0.1:8000/api/help?section=client&format=text"
curl "http://127.0.0.1:8000/api/help?section=api_client&format=text"
```

지원 section:

```text
overview
web_ui
client
api_client
strategy
api
ids
troubleshooting
```

## 4. 실행형 Python client

같은 PC에서 두 client를 실행하려면 `--profile`을 다르게 지정합니다.

첫 번째 CMD:

```powershell
cd C:\access\rps
python rps_client.py --profile p1 --name BotA --choice rock
```

두 번째 CMD:

```powershell
cd C:\access\rps
python rps_client.py --profile p2 --name BotB --choice scissors
```

10라운드 실행:

```powershell
python rps_client.py --profile p1 --strategy-file strategies\best_choice_strategy.py --rounds 10
python rps_client.py --profile p2 --strategy-file strategies\random_strategy.py --rounds 10
```

이전에 게임했던 상대를 기다리기:

```powershell
python rps_client.py --profile p1 --wait-previous-opponent --strategy-file strategies\my_strategy.py
```

## 5. 전략 파일 작성

전략 파일은 `choose(context)` 함수를 가진 Python 파일입니다.

예시:

```python
import random


def choose(context):
    analysis = context["analysis"]
    choices = context["choices"]

    best_choice = analysis.get("best_choice")
    if best_choice in choices:
        return best_choice

    return random.choice(choices)
```

실행:

```powershell
python rps_client.py --profile p1 --strategy-file strategies\my_strategy.py --rounds 10
```

반환값은 반드시 다음 중 하나입니다.

```text
rock
paper
scissors
```

## 6. api_client.py 사용

`api_client.py`는 외부 Python 코드에서 API를 쉽게 호출하도록 제공하는 모듈입니다.

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

실행 가능한 샘플 코드:

```powershell
python sample_api_game.py --name BotA --choice rock
python sample_api_game.py --name BotB --choice scissors
```

## 7. 주요 API 흐름

1. `POST /api/players`: `client_id`, `coupon_id` 발급
2. `POST /api/match/join`: 매칭 참여
3. `GET /api/state`: 매칭 완료와 `game_id` 확인
4. `POST /api/match/choice`: 선택 제출
5. `GET /api/games/{game_id}/result`: 내 기준 승패 조회
6. `GET /api/analysis`: 개인 전적/분석 조회

`coupon_id`는 JSON body, `X-Coupon-ID` header, query string 중 하나로 전달할 수 있습니다.

## 8. ID 규칙

- `client_id`: PC/플레이어 고유 ID입니다.
- `coupon_id`: API 인증에 쓰는 ID이며 현재는 `client_id`와 같은 값입니다.
- `game_name`: 참가자 조합으로 만든 이름입니다. 같은 참가자 조합이면 같은 이름을 씁니다.
- `game_id`: `game_name` 뒤에 serial을 붙인 실제 게임 ID입니다.

예시:

```text
rps-2p-bota-1-botb-2-0001
```
