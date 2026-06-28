#!/usr/bin/env python3.12
"""JANUS — 언어모델을 방어 루프에 직접 배선한 폐루프 시연 (6.10.7).

6.10.4는 LLM이 게임이론 해·규칙 분류와 동일한 판단에 '오프라인'으로 도달함을 보였다.
본 모듈은 한 걸음 더 나아가, 실제 교전 루프 '안에서' LLM이 매 경보에 대한 대응(R1/R3)을
실시간으로 결정하고 그 결정이 시뮬레이터의 복구를 직접 구동하게 한다. 곧 BlueTeamAgent의
triage 정책 자리(triage_policy)에 규칙 대신 로컬 LLM(Qwen2.5-VL-7B, greedy)을 꽂아 동일
교전을 돌리고, 규칙 정책 대조군과 임무 결과가 일치하는지 본다. 이로써 '규칙=LLM의 충실한
대역'(6.10.4)을 넘어 'LLM이 폐루프 안의 결정자로 실제 동작'함을 입증한다.

지연 관리: 경보 종류(spoof/gateway)별로 LLM을 1회만 호출하고 결정을 캐시한다(2-시간척도,
6.10.5). 결정 1건은 초 단위이므로 제어 경로 밖 자문 계층에 해당한다.

실행: /opt/homebrew/bin/python3.12 src/llm_inloop_engagement.py
"""
import os
import sys
import json
import copy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from janus.world import World, Vehicle
from janus.attack import RedAttacker
from janus.defense import BlueDefender
from janus.agents import RedTeamAgent, BlueTeamAgent, Orchestrator
import llm_strategist                              # 동일 LLM 래퍼(mlx-vlm, greedy)·타이밍 재사용
from llm_strategist import llm, extract_json

RESULTS = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "docs", "results"))

UAV, UGV = 1, 2
UAV_TARGET = [60.0, 0.0, 20.0]
UGV_START = [0.0, -40.0, 0.0]

# 4장 킬체인 시나리오(주입+GPS 스푸핑+표적 변조+은폐) — spoof(D1)와 gateway(D3) 경보가 모두
# 발생하므로 LLM이 루프 안에서 R1과 R3 결정을 각각 한 번씩 실제로 내려야 한다.
SCHED = dict(uav=UAV, recon_t=4.0, mitm_t=5.0, inject_t=6.0, spoof_t=6.0, spoof_end=30.0,
             lateral_t=12.0, evade_t=16.0,
             fake_uav_target=[60.0, 40.0, 20.0], spoof_drift=[1.2, 0.0, 0.0],
             fake_ugv_target=[-30.0, 60.0, 0.0], telemetry_fake=UAV_TARGET)

SYS_TRIAGE = ("You are JANUS-Blue's in-loop triage agent defending a UAV-UGV cooperative gateway. "
              "On each detector alarm you must pick the single recovery action that preserves the "
              "mission. Reason briefly, then answer.")

_DECISIONS = {}   # kind -> {action, reasoning, raw}  (경보 종류별 1회만 LLM 호출)


def llm_triage_policy(kind, ctx):
    """BlueTeamAgent의 triage 정책 자리에 꽂히는 LLM 정책. (kind, ctx) -> 'R1'|'R3'|'NONE'."""
    if kind in _DECISIONS:
        return _DECISIONS[kind]["action"]          # 동일 경보종류는 캐시된 결정 재사용(지연 최소화)
    user = ("A live anomaly was detected during the UAV-UGV engagement.\n"
            f"  alarm category : {kind}\n"
            f"  evidence       : {ctx.get('evidence', '')}\n\n"
            "Choose exactly ONE recovery action:\n"
            "  R1 = switch the affected node's navigation to dead-reckoning "
            "(the right fix for GPS spoofing of a node)\n"
            "  R3 = isolate the gateway and roll back the relayed target "
            "(the right fix for relayed-target tampering or a compromised gateway)\n"
            "  NONE = take no recovery action\n\n"
            'Answer with ONLY a JSON object: {"action":"<R1|R3|NONE>","reasoning":"<one sentence>"}')
    raw = llm(SYS_TRIAGE, user, max_tokens=200)
    js = extract_json(raw) or {}
    action = (js.get("action") or "").strip().upper()
    action = action if action in ("R1", "R3", "NONE") else "NONE"
    _DECISIONS[kind] = {"action": action, "reasoning": js.get("reasoning"), "raw": raw}
    return action


def build_world():
    w = World()
    w.add(Vehicle(UAV, "uav", [0.0, 0.0, 20.0]))
    w.add(Vehicle(UGV, "ugv", UGV_START))
    w.get(UAV).set_target(UAV_TARGET)
    return w


def run(triage_policy, seed=42):
    np.random.seed(seed)
    w = build_world()
    red = RedTeamAgent(w, RedAttacker(w), copy.deepcopy(SCHED))
    blue = BlueTeamAgent(w, BlueDefender(w, innov_threshold=3.0), enabled=True, triage_policy=triage_policy)
    Orchestrator(w, red, blue).run(32, 1.0, np.array(UAV_TARGET, float), UGV)
    m = blue  # 편의
    last = None
    # 마지막 메트릭은 orchestrator에 있으나 여기선 blue/월드에서 직접 산출
    g = w.gateway
    ugv_err = float(np.linalg.norm(g.relayed_target - g.true_target)) if (
        g.relayed_target is not None and g.true_target is not None) else 0.0
    uav_err = float(np.linalg.norm(w.get(UAV).true_pos - np.array(UAV_TARGET, float)))
    return {"uav_pos_err": round(uav_err, 2), "ugv_target_err": round(ugv_err, 2),
            "detections": blue.detections, "recoveries": blue.recoveries,
            "triage_log": blue.triage_log}


def main():
    print("=" * 84)
    print("JANUS — 언어모델을 방어 루프에 직접 배선한 폐루프 시연 (6.10.7)")
    print("=" * 84)

    rule = run(triage_policy=None)                 # 대조군: 결정적 규칙 정책(기본)
    llm_res = run(triage_policy=llm_triage_policy)  # 처치군: LLM이 루프 안에서 대응 결정

    print(f"\n[규칙 정책]   UAV {rule['uav_pos_err']:.1f} m / UGV 표적 {rule['ugv_target_err']:.1f} m "
          f"/ 탐지 {rule['detections']} / 복구 {rule['recoveries']}")
    print(f"[LLM 인루프]  UAV {llm_res['uav_pos_err']:.1f} m / UGV 표적 {llm_res['ugv_target_err']:.1f} m "
          f"/ 탐지 {llm_res['detections']} / 복구 {llm_res['recoveries']}")

    print("\n[LLM이 루프 안에서 실시간으로 내린 대응 결정]")
    for kind, d in _DECISIONS.items():
        print(f"  {kind:8} → {d['action']}   ({d['reasoning']})")

    same_mission = (abs(llm_res['uav_pos_err'] - rule['uav_pos_err']) < 1.0 and
                    abs(llm_res['ugv_target_err'] - rule['ugv_target_err']) < 1.0)
    core_ok = (_DECISIONS.get("spoof", {}).get("action") == "R1" and
               _DECISIONS.get("gateway", {}).get("action") == "R3")
    print(f"\n임무 결과 규칙과 일치: {same_mission}  |  "
          f"LLM 핵심대응=규칙(spoof→R1, gateway→R3): {core_ok}")

    times = getattr(llm_strategist, "_CACHE", {}).get("times", [])
    out = {"model": llm_strategist.MODEL, "decoding": "greedy(temp=0)",
           "scenario": "MIRROR-CRACK in-loop (inject+spoof+tamper+evade), 32 steps, seed=42",
           "rule_policy": {k: rule[k] for k in ("uav_pos_err", "ugv_target_err", "detections", "recoveries")},
           "llm_inloop": {k: llm_res[k] for k in ("uav_pos_err", "ugv_target_err", "detections", "recoveries")},
           "llm_decisions": _DECISIONS,
           "llm_triage_log": [list(map(str, r)) for r in llm_res["triage_log"]],
           "mission_matches_rule": bool(same_mission), "core_actions_match_rule": bool(core_ok),
           "llm_calls": len(times), "llm_decision_seconds": [round(x, 2) for x in times]}
    with open(os.path.join(RESULTS, "llm_inloop_log.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n  LLM 호출 {len(times)}건 (경보종류별 1회), 결정 지연 {[round(x, 2) for x in times]} s")
    print(f"  결과 저장: {RESULTS}/llm_inloop_log.json")


if __name__ == "__main__":
    main()
