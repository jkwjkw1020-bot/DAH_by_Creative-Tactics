# JANUS — 이기종 UAV-UGV 협동작전 자율 공방 AI 에이전트 (DAH 2026 예선)

**JANUS**(Joint Adversarial Network for Unmanned Systems)는 무인기(UAV, MAVLink)와 무인지상차량
(UGV, ROS2)이 협동하는 방산 환경에서, 두 도메인을 잇는 **협동 게이트웨이**를 핵심 공격 표면으로 보고
공격(Red)·방어(Blue) AI 에이전트가 자율적으로 대결·자가개선하는 프레임워크의 개념증명(PoC)이다.
DAH 2026 예선 부가자료(소스코드)이며, 보고서 본문은 대회 플랫폼에 별도 제출한다.

> 배경: 유무인 복합전투(MUM-T)와 이기종 군집은 미 공군 CCA, 미 육군 OMFV, EU MUSHER 등으로
> 전력화가 진행 중이다. 한편 GPS 스푸핑(2011 RQ-170, 러-우 전쟁)과 MAVLink 메시지 주입은
> 실전·실증으로 확인된 위협이다. JANUS는 이 두 흐름이 만나는 협동 게이트웨이의 위험을 다룬다.

## 핵심 개념
- **공격(MIRROR-CRACK)**: 게이트웨이 중간자 → 명령 주입 + GPS 점진 스푸핑(센서·제어 동시 기만) → 표적좌표 변조 횡적확산 → 군집 분열 → 은폐
- **방어(Zero-Trust, 심층 방어)**: MAVLink2 서명 · 센서융합 이상탐지(EKF 이노베이션 + CUSUM) · 게이트웨이 무결성 → 차단 · 추측항법 복구 · 격리·롤백
- **에이전트**: 조정자(LLM) + Red/Blue 전문 에이전트의 공방 폐루프, 그리고 **공방을 반복해 약점을 자동 발견·보완하는 적대적 자가개선**

## 디렉토리 구조
```
src/janus/
  mavlink_lite.py   # MAVLink2 메시지 모델 + HMAC 메시지 서명
  world.py          # UAV/UGV 운동·센서 + 협동 게이트웨이 (교전 환경)
  attack.py         # Red 공격 도구 (킬체인)
  defense.py        # Blue 탐지(고정임계+CUSUM)·차단·복구
  agents.py         # Red/Blue 에이전트 + Orchestrator
src/run_engagement.py   # 공방 교전 데모 (방어 미적용 vs 적용 비교)
src/coevolution.py      # 반복 적대적 공진화 (약점 발견 → 보완 → 수렴)
src/make_diagrams.py    # 보고서용 아키텍처 다이어그램 생성
src/build_report.py     # 보고서 마크다운 → PDF 빌드
tests/test_smoke.py     # 스모크 테스트
docs/results/           # 교전·공진화 결과 그래프·로그
docs/diagrams/          # 아키텍처 다이어그램
```

## 실행 방법
```bash
python3 -m pip install -r requirements.txt   # numpy, matplotlib, scikit-learn
python3 src/run_engagement.py    # 공방 교전 데모 → docs/results/ 그래프·로그 생성
python3 src/coevolution.py       # 반복 공진화 → 수렴 그래프 생성
python3 tests/test_smoke.py      # 동작 검증
```

## 주요 결과 (재현 가능)
| 구분 | 방어 미적용 | 방어 적용 |
|---|---:|---:|
| UAV 임무 위치오차 | 49.2 m | 0.6 m |
| UGV 표적오차 | 67.5 m | 0.0 m |
| 탐지 / 차단 / 복구 | 0 / 0 / 0 | 2 / 1 / 2 |

반복 공진화에서는 스텔스 GPS 스푸핑이라는 방어의 사각지대를 자동으로 발견하고 CUSUM 누적합 검정으로
보완하여, 공격의 무탐지 피해가 4라운드 만에 2.53 m에서 0.85 m로 수렴하였다(`docs/results/fig5_convergence.png`).

## 비고
- 본 PoC는 재현성과 단일 장비 실행을 위해 비행 동역학을 ArduPilot SITL을 모사한 경량 시뮬레이터로,
  에이전트 정책을 결정적 규칙으로 구현하였다. 메시지 계층(`mavlink_lite`)과 정책 계층은 인터페이스가
  분리되어 각각 pymavlink와 언어모델(mlx-lm 등)로 교체 가능하다.
- 환경: macOS(Apple Silicon), Python 3.9.
- 본 코드는 **방어 연구·교육 목적의 시뮬레이션**이며, 실제 무인체계를 대상으로 한 공격에 사용하는 것을 금한다.
