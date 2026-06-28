# JANUS — 이기종 UAV-UGV 협동작전 자율 공방 AI 에이전트 (DAH 2026 예선)

**JANUS**(Joint Adversarial Network for Unmanned Systems)는 무인기(UAV, MAVLink)와 무인지상차량
(UGV, ROS2)이 협동하는 방산 환경에서, 두 도메인을 잇는 **협동 게이트웨이**를 핵심 공격 표면으로 보고
공격(Red)·방어(Blue) AI 에이전트가 자율적으로 대결·자가개선하는 프레임워크의 개념증명(PoC)이다.
DAH 2026 예선 부가자료(소스코드)이며, 보고서 본문은 대회 플랫폼에 별도 제출한다.

> 배경: 유무인 복합전투(MUM-T)와 이기종 군집은 미 공군 CCA, 미 육군 OMFV, EU MUSHER 등으로
> 전력화가 진행 중이다. 한편 GPS 스푸핑(2011 RQ-170, 러-우 전쟁)과 MAVLink 메시지 주입은
> 실전·실증으로 확인된 위협이다. JANUS는 이 두 흐름이 만나는 협동 게이트웨이의 위험을 다룬다.

## 핵심 개념
- **공격(MIRROR-CRACK)**: 게이트웨이 중간자 → 명령 주입 + GPS 점진 스푸핑(센서·제어 동시 기만) → 표적좌표 변조 횡적확산 → 군집 분열 → 은폐. 확장 전술로 리플레이·탈동기 포함.
- **방어(Zero-Trust, 심층 방어)**: MAVLink2 서명 · 센서융합 이상탐지(EKF 이노베이션 + CUSUM) · 게이트웨이 무결성/홉바이홉(D3) · 종단간 출처증명(D6) · 다중 항법원 투표 · 신선도/anti-replay(D7) → 차단 · 추측항법 복구 · 격리·롤백
- **에이전트**: 조정자(LLM) + Red/Blue 전문 에이전트의 공방 폐루프, 그리고 **공방을 반복해 약점을 자동 발견·보완하는 적대적 자가개선**
- **전술공간 보안게임**: 공방을 예산 제약 자원배분 게임으로 정식화하여 minimax 혼합전략 균형을 풀고, 어떤 고정 방어 배치도 안전하지 않음을 정량적으로 입증(균형 기반 방어 자원배분)

## 디렉토리 구조
```
src/janus/
  mavlink_lite.py   # MAVLink2 메시지 모델 + HMAC 메시지 서명
  world.py          # UAV/UGV 운동·센서 + 협동 게이트웨이 (교전 환경, 다중 항법원)
  attack.py         # Red 공격 도구 (킬체인: 주입·스푸핑·변조·위조·리플레이·탈동기)
  defense.py        # Blue 탐지(고정임계+CUSUM)·차단·복구 + 출처증명(D6)·신선도(D7)
  agents.py         # Red/Blue 에이전트 + Orchestrator
src/run_engagement.py      # 공방 교전 데모 (방어 미적용 vs 적용 비교)        → fig1~3
src/coevolution.py         # 반복 적대적 공진화 (약점 발견 → 보완 → 수렴)     → fig4~5
src/advanced_engagement.py # 신뢰 축 붕괴 시 방어: 종단간 출처증명·생존성      → fig6~7
src/security_game.py       # 전술공간 보안게임·minimax 균형·보안-비용 곡선     → fig8~9
src/llm_strategist.py      # 실제 LLM(Qwen2.5-VL) 전략가 교차검증 (python3.12)  → log
src/llm_inloop_engagement.py # LLM을 방어 루프에 직접 배선한 교전 시연 (python3.12) → log
src/timescale_budget.py    # 2-시간척도 지연 실측 (인루프 검사 vs LLM 자문)     → fig10
src/portfolio_extension.py # 공격 포트폴리오 확장(리플레이·탈동기)·균형 재조정  → fig11
src/robustness.py          # 다중시드 강건성 점검 (헤드라인 수치 분포 안정성)   → log
src/make_diagrams.py       # 보고서용 아키텍처 다이어그램 생성
src/build_report.py        # 보고서 마크다운 → PDF 빌드
tests/test_smoke.py        # 스모크 테스트 (9건)
docs/results/              # 교전·실험 결과 그래프(fig1~11)·로그(JSON)
docs/diagrams/             # 아키텍처 다이어그램
```

## 실행 방법
```bash
python3 -m pip install -r requirements.txt   # numpy, scipy, matplotlib (+scikit-learn)

# 핵심 공방·실험 (python3)
PYTHONPATH=src python3 src/run_engagement.py       # 공방 교전 → fig1~3, engagement_log.json
PYTHONPATH=src python3 src/coevolution.py          # 반복 공진화 → fig4~5
PYTHONPATH=src python3 src/advanced_engagement.py  # 출처증명·생존성 → fig6~7
PYTHONPATH=src python3 src/security_game.py        # 보안게임·균형 → fig8~9
PYTHONPATH=src python3 src/timescale_budget.py     # 2-시간척도 지연 실측 → fig10
PYTHONPATH=src python3 src/portfolio_extension.py  # 포트폴리오 확장·D7 균형 재조정 → fig11
PYTHONPATH=src python3 src/robustness.py           # 다중시드 강건성 → robustness_log.json

python3 tests/test_smoke.py      # 동작 검증 (9건)

# (선택) 실제 LLM 전략가 교차검증 / LLM 인루프 교전 시연 — python3.12 + mlx-vlm, 로컬 Qwen2.5-VL-7B
/opt/homebrew/bin/python3.12 -m pip install --break-system-packages mlx-vlm
/opt/homebrew/bin/python3.12 src/llm_strategist.py       # → llm_strategist_log.json
/opt/homebrew/bin/python3.12 src/llm_inloop_engagement.py # 교전 루프 안의 LLM 결정 시연 → llm_inloop_log.json
```

## 주요 결과 (재현 가능, 시드 고정)

**공방 교전 (방어 미적용 vs 적용)**

| 지표 | 방어 미적용 | 방어 적용 |
|---|---:|---:|
| UAV 임무 위치오차 | 49.2 m | 0.6 m |
| UGV 표적오차 | 67.5 m | 0.0 m |
| 탐지 / 차단 / 복구 | 0 / 0 / 0 | 2 / 1 / 2 |

**심화 결과**
- **적대적 자가개선(공진화)**: 스텔스 GPS 스푸핑이라는 방어의 사각지대를 자동으로 발견하고 CUSUM 누적합 검정으로 보완하여, 무탐지 피해가 4라운드 만에 2.53 m → 0.85 m로 수렴(fig5).
- **종단간 출처증명(D6)**: 정상 키로 장악된 게이트웨이가 자기보고까지 위조하면 홉바이홉 무결성(D3)은 110 m·0탐지로 뚫리나, UAV가 자기 키로 서명한 종단간 출처증명은 0 m·탐지·복구로 막아낸다(fig6).
- **탐지 없는 생존성**: 임계 직하 스텔스 스푸핑(탐지 0건)에서 탐지전용은 2.53 m 이탈하나, 다중 항법원 중앙값 투표는 동일 무탐지 조건에서 0.44 m로 억제(fig7).
- **전술공간 보안게임**: 어떤 단일 메커니즘도 전 전술을 막지 못한다(fig8a). 예산 B=3에서 가용 고정태세 29개가 전부 임무실패(1.5)인데, minimax 혼합전략 균형은 0.68로 55% 낮춘다 — 정량적 심층방어(fig8b·9).
- **실제 LLM 교차검증**: 로컬 Qwen2.5-VL-7B가 동일 관찰에서 게임이론 해와 3결론(고정배치 불가·무작위화 필요·D6 핵심) 독립 일치, 분류 3/3 규칙정책 일치.
- **LLM 인루프 시연**: 방어 에이전트의 분류·대응 정책 자리(`triage_policy`)에 로컬 LLM을 직접 꽂아 교전 루프 안에서 경보별 대응(spoof→R1, gateway→R3)을 실시간 결정·복구 구동 → 규칙 정책과 동일한 임무 보전(UAV 0.6 m·UGV 0 m). LLM이 폐루프 결정자로 동작함을 입증(`llm_inloop_log.json`).
- **2-시간척도 지연**: 결정적 인루프 검사 전 스택 16.9마이크로초/스텝(50Hz의 0.08%) vs LLM 결정 1.52 s(약 9만 배) → 빠른 제어 경로 + 느린 자문 루프 분리(fig10).
- **포트폴리오 확장**: 공격에 리플레이·탈동기를 추가하면 신선도 검사 D7의 균형 가동확률이 0 → 0.66으로 부상 — 공격 혁신에 균형이 자동 재배분(fig11).
- **다중시드 강건성**: 21개 독립 시드 반복에서 헤드라인 수치가 좁은 표준편차로 안정(예: 방어 적용 UAV 0.44 ± 0.20 m, D6 0.00 ± 0.00 m, 게임값 0.67 ± 0.01). 정성적 결론은 전 시드에서 동일(`robustness_log.json`).

## 결과물 목록
- **그림**: `docs/results/fig1~fig11` (교전 3 + 공진화 2 + 출처증명/생존성 2 + 보안게임 2 + 2-시간척도 1 + 포트폴리오 1)
- **로그(JSON)**: engagement / coevolution / advanced / security_game / llm_strategist / llm_inloop / timescale_budget / portfolio_extension / robustness
- **다이어그램**: `docs/diagrams/` (협동 통신 구조 · 킬체인 · 방어 스택 · JANUS 아키텍처)

## 비고
- 본 PoC는 재현성과 단일 장비 실행을 위해 비행 동역학을 ArduPilot SITL을 모사한 경량 시뮬레이터로,
  에이전트 정책을 결정적 규칙으로 구현하였다. 메시지 계층(`mavlink_lite`)과 정책 계층은 인터페이스가
  분리되어 각각 pymavlink와 언어모델(mlx-lm/mlx-vlm)로 교체 가능하다. 실제 LLM 전략가 교차검증
  (`llm_strategist.py`)과 LLM 인루프 교전 시연(`llm_inloop_engagement.py`)이 이 교체 가능성을 로컬 모델로 실증한다.
- 환경: macOS(Apple Silicon), Python 3.9(핵심) / Python 3.12(LLM 교차검증, 선택).
- 본 코드는 **방어 연구·교육 목적의 시뮬레이션**이며, 실제 무인체계를 대상으로 한 공격에 사용하는 것을 금한다.
