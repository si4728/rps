# 관리자용 운영 도움말

이 문서는 가위바위보 알고리즘 대전 시스템을 운영하는 관리자를 위한 문서입니다.

## 1. 서버 실행

```powershell
cd C:\access\rps
python app.py
```

기본 접속 주소:

```text
http://127.0.0.1:8000
```

다른 PC에서 접속하게 하려면 `app.py` 마지막 실행부를 변경합니다.

```python
app.run(host="0.0.0.0", port=8000, debug=True, threaded=True)
```

운영 환경에서는 `debug=False`를 권장합니다.

## 2. 주요 파일

- `app.py`: Flask 서버, 매칭, 게임 판정, 분석 API
- `rps_client.py`: 일반 사용자 또는 봇이 실행하는 Python client
- `strategies/`: 사용자 전략 알고리즘 파일
- `data/rps.db`: SQLite 데이터베이스
- `USER_GUIDE.md`: 전체 사용설명서
- `ADMIN_GUIDE.md`: 관리자용 문서

## 3. 관리자 화면

브라우저에서 접속합니다.

```text
http://127.0.0.1:8000/admin
```

확인 가능 항목:

- 사용자 목록
- 사용자 상태
- 방 정보
- 최근 매치
- 최근 라운드 로그

## 4. 데이터베이스

SQLite DB 위치:

```text
C:\access\rps\data\rps.db
```

주요 테이블:

- `users`: 사용자, client_id/coupon_id, 상태
- `rooms`: 방
- `matches`: game_id, game_name, serial, 참가자
- `rounds`: 라운드별 선택과 승패

## 5. ID 정책

### client_id

플레이어/PC 고유 ID입니다. `coupon_id`와 같은 값입니다.

### game_name

참가자 조합으로 생성됩니다. 같은 참가자 조합이면 동일합니다.

### game_id

`game_name + serial`입니다.

예:

```text
rps-2p-bota-1-botb-2-0001
```

## 6. 일반 사용자 도움말 API

일반사용자용 도움말은 서버 API로 제공합니다.

```text
GET /api/help
GET /api/help?section=client
GET /api/help?section=api
GET /api/help?section=strategy
```

관리자용 문서는 API로 공개하지 않고 파일 문서로 유지합니다.

## 7. 자주 보는 장애

### 같은 PC에서 클라이언트가 매칭되지 않음

같은 profile을 사용한 경우입니다. 서로 다른 profile을 사용하게 안내합니다.

```powershell
python rps_client.py --profile p1 --name BotA
python rps_client.py --profile p2 --name BotB
```

### `already ended by the other client`

오류가 아닙니다. 같은 매치의 상대 클라이언트가 먼저 종료한 것입니다.

### timeout

상대 클라이언트가 실행되지 않았거나 같은 profile을 재사용한 경우가 많습니다.

### DB 초기화

테스트 데이터를 모두 지우려면 서버를 끄고 `data\rps.db`를 백업/삭제한 뒤 서버를 다시 실행합니다.

## 8. 운영 권장사항

- 외부 공개 시 `RPS_SECRET_KEY` 환경변수 설정
- 관리자 화면 접근 제한 추가 권장
- 운영 DB 백업 권장
- 장시간 운영 시 SQLite 대신 별도 DBMS 검토
