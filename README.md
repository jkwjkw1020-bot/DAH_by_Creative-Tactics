# JANUS — 이기종 UAV-UGV 협동작전 자율 공방 AI 에이전트 (DAH 2026 예선 PoC)

**JANUS** (Joint Adversarial Network for Unmanned Systems) 는 UAV(MAVLink)와 UGV(ROS2)를 잇는
**협동 게이트웨이**를 표적으로, 공격(Red)·방어(Blue) AI 에이전트가 자율 대결하는 프레임워크의
개념증명(PoC)이다. DAH 2026 예선 부가자료.

## 핵심 개념
- **공격(4장)**: 게이트웨이 MITM → 미서명 명령주입 + GPS 점진 스푸핑 → 표적좌표 변조 횡적확산 → 군집분열·은폐
- **방어(5장)**: MAVLink2 서명검증 · 센서융합 이상탐지(EKF 이노베이션) · 게이트웨이 무결성 → 차단·추측항법·격리·롤백
- **에이전트(6장)**: LLM 통합 지점을 둔 Red/Blue 멀티에이전트 + Orchestrator 공방 폐루프

## 디렉토리 구조
```
src/janus/
  mavlink_lite.py   # MAVLink2 메시지 모델 + HMAC 메시지 서명
  world.py          # UAV/UGV 운동·센서 + 협동 게이트웨이 Env
  attack.py         # Red 공격 도구 (킬체인 MIRROR-CRACK)
  defense.py        # Blue 탐지·차단·복구
  agents.py         # Red/Blue 에이전트 + Orchestrator
src/run_engagement.py   # 공방 교전 데모 (방어 OFF/ON 비교)
docs/results/           # 결과 그래프·로그 (실행 시 생성)
report/                 # 예선 보고서 원고 (장별)
references/             # 참고문헌
```

## 실행 방법
```bash
python3 -m pip install -r requirements.txt   # numpy, matplotlib, scikit-learn
python3 src/run_engagement.py
```
실행하면 `docs/results/` 에 그래프 3종(PNG)과 `engagement_log.json` 이 생성되고, 콘솔에 요약이 출력된다.

## 재현 결과
| 지표 | 방어 OFF | 방어 ON |
|---|---:|---:|
| UAV 임무 위치오차 | 49.2 m | 0.6 m |
| 최대 이노베이션 | 29.2 m | 3.6 m |
| UGV 표적오차 | 67.5 m | 0.0 m |
| 탐지 / 차단 / 복구 | 0 / 0 / 0 | 2 / 1 / 2 |

## 비고
- 본 PoC는 **재현성**을 위해 결정적 규칙(rule) 정책을 사용. 실제 시스템에선 `agents.py` 의
  `_decide()`/`_triage()` 를 **LLM 정책(mlx-lm 등)** 으로 교체 가능.
- 실기체/ArduPilot SITL 연동 시 `mavlink_lite.py` 를 **pymavlink** 로 교체.
- 환경: macOS (Apple Silicon), Python 3.9. 외부 네트워크·실기체 불필요(완전 시뮬레이션).
- 본 코드는 **방어 연구·교육 목적의 시뮬레이션**이며 실제 무인체계 대상 공격에 사용을 금한다.
