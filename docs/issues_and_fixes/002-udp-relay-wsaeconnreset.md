# ISSUE-002: UDP 릴레이가 클라이언트 종료 후 인증을 못 받음 (Windows WSAECONNRESET)

## 증상
- 한 클라이언트가 종료된 뒤, 이후 새 클라이언트의 `auth` 요청에 서버가 응답하지 않음.
- 잘못된 비밀번호 테스트가 `denied`가 아니라 타임아웃으로 떨어짐. 릴레이가 사실상 먹통.

## 원인
- Windows UDP 소켓 고유 동작: 목적지(사라진 클라이언트)로 `sendto()` 하면 OS가 ICMP Port-Unreachable을 받고, **다음 `recvfrom()`에서 `WSAECONNRESET`(10054)** 를 던짐.
- `relay_server.py`의 control loop가 `except OSError: break` 여서, 데이터 스레드의 `sendto` 실패가 유발한 10054로 인해 control 스레드가 **종료** → 이후 인증 처리 불가. ✓(`amr_lidar/relay_server.py` control_loop)

## 해결
- 소켓 생성 직후 리셋 동작 비활성화: `sock.ioctl(socket.SIO_UDP_CONNRESET, 0)` (`hasattr` 가드).
- control loop에서 `ConnectionResetError`는 `continue`로 무시, `OSError`도 `self.running`일 때는 루프 유지.
- (총 ~8줄 추가/수정, `amr_lidar/relay_server.py`)

## 검증
- [x] SIL(loopback) — 순서 재현: 정상 클라 → (종료) → 오답 클라 → 정상 클라
  - 정상 클라: live 프레임 수신(~800 pts)
  - 오답 클라: `Auth denied - wrong id/pw.` (트레이스백 없음)
  - 정상 클라(재접속): live 프레임 수신 → control loop 생존 확인 = PASS

## 관련 작업
- [worklog 2026-07-09](../worklog/2026/07/2026-07-09.md)
