#!/usr/bin/env python3
"""JANUS 2-시간척도 아키텍처와 지연 예산 실측 — 6.10.5.

6.10의 보안게임에서 방어 '예산'은 추상 비용이었다. 본 모듈은 각 결정적 방어 메커니즘과
LLM 전략결정의 실제 지연을 측정하여 그 예산이 곧 제어 루프의 지연 한도임을 정착시킨다.
핵심 결론은 두 시간척도의 분리다.
  - 빠른 계층(제어 경로 내): D1~D6·투표 등 결정적 안전·일관성 검사 = 마이크로초급. 전 스택을
    합쳐도 제어 주기(예: 50 Hz=20 ms) 안에 충분히 든다.
  - 느린 계층(제어 경로 밖): LLM 전략·분류 = 초급. 빠른 계층보다 수만 배 느리므로 제어 루프에
    넣을 수 없고, 느린 자문 루프로 동작해야 한다(6.10.4에서 실측한 결정 지연을 사용).

실행: PYTHONPATH=src python3 src/timescale_budget.py
"""
import os
import sys
import json
import timeit
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from janus.world import World, Vehicle
from janus import mavlink_lite as mav
from janus.attack import RedAttacker
from janus.defense import BlueDefender
from janus.agents import RedTeamAgent, BlueTeamAgent, Orchestrator

RESULTS = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "docs", "results"))
UAV, UGV = 1, 2
UAV_TARGET = [60.0, 0.0, 20.0]
OFF = 99999.0

# 제어 루프 후보 주기(설계 기준점) → 지연 한도(µs)
CONTROL_RATES = [("50 Hz", 20000.0), ("100 Hz", 10000.0), ("1 kHz", 1000.0)]


def populated_world():
    """다중벡터+은폐 공격을 방어 없이 진행해 모든 검사가 처리할 상태를 채운 월드를 만든다."""
    np.random.seed(42)
    w = World()
    w.add(Vehicle(UAV, "uav", [0.0, 0.0, 20.0]))
    w.add(Vehicle(UGV, "ugv", [0.0, -40.0, 0.0]))
    w.get(UAV).set_target(UAV_TARGET)
    sched = dict(uav=UAV, recon_t=2, mitm_t=3, inject_t=6, spoof_t=6, spoof_end=OFF,
                 spoof_drift=[1.0, 0, 0], spoof_cap=2.5, lateral_t=6, forge_t=6, evade_t=8,
                 fake_uav_target=[60.0, 40.0, 20.0], fake_ugv_target=[-30.0, 60.0, 0.0],
                 telemetry_fake=UAV_TARGET)
    red = RedTeamAgent(w, RedAttacker(w), sched)
    blue = BlueTeamAgent(w, BlueDefender(w), enabled=False)   # 방어 OFF → 상태 보존
    Orchestrator(w, red, blue).run(10, 1.0, np.array(UAV_TARGET, float), UGV)
    return w


def measure_us(fn, number=2000, repeat=5):
    """호출 1회 지연(µs) — best-of-repeat로 잡음 제거."""
    best = min(timeit.timeit(fn, number=number) for _ in range(repeat)) / number
    return best * 1e6


def main():
    w = populated_world()
    d = BlueDefender(w, innov_threshold=3.0, use_cusum=True, use_provenance=True, use_robust_nav=True)
    uav = w.get(UAV)
    signed = mav.sign_message(mav.set_position_target(UGV, 60, 0, 20, sysid=UAV), uav.key)

    def t_d1():
        d.alarms.clear(); d._cusum.clear(); d.use_cusum = False; d.innovation_monitor()

    def t_cusum():
        d.alarms.clear(); d._cusum.clear(); d.use_cusum = True; d.innovation_monitor()

    def t_d2():
        mav.verify_message(signed, uav.key)

    def t_d3():
        d.alarms.clear(); d.gateway_integrity()

    def t_d5():
        d.alarms.clear(); d.telemetry_crosscheck()

    def t_d6():
        d.alarms.clear(); d.provenance_check()

    def t_nav():
        gps = uav.true_pos + uav.gps_bias
        np.median(np.vstack([gps, uav.dr_pos, uav.aux_pos]), axis=0)

    checks = [("D1 innov", t_d1), ("D1+CUSUM", t_cusum), ("D2 signature", t_d2),
              ("D3 hop integ", t_d3), ("D5 telemetry", t_d5), ("D6 provenance", t_d6),
              ("Robust-nav vote", t_nav)]
    lat = {name: round(measure_us(fn), 3) for name, fn in checks}

    # 제어 스텝(빠른 계층 기준) — 별도 월드에서 측정
    w2 = populated_world()
    ctrl_us = round(measure_us(lambda: w2.step(1.0)), 3)

    # 전 방어 스택 1스텝 비용(CUSUM은 D1 포함이므로 D1 중복 제외)
    fast_stack_us = round(lat["D1+CUSUM"] + lat["D2 signature"] + lat["D3 hop integ"]
                          + lat["D5 telemetry"] + lat["D6 provenance"] + lat["Robust-nav vote"], 3)

    # LLM 결정 지연(6.10.4 실측 로그에서). 없으면 None.
    llm_s = None
    p = os.path.join(RESULTS, "llm_strategist_log.json")
    if os.path.exists(p):
        llm_s = json.load(open(p)).get("llm_decision_seconds", {}).get("median_s")
    llm_us = (llm_s * 1e6) if llm_s else None
    ratio = round(llm_us / fast_stack_us) if llm_us else None

    print("=" * 80)
    print("JANUS 2-시간척도 지연 예산 실측 (6.10.5)")
    print("=" * 80)
    print("\n[빠른 계층] 결정적 방어 검사 1회 지연(µs):")
    for name, _ in checks:
        print(f"  {name:18} {lat[name]:>9.3f} µs")
    print(f"  {'(제어 스텝)':18} {ctrl_us:>9.3f} µs")
    print(f"  {'전 방어 스택/스텝':18} {fast_stack_us:>9.3f} µs")
    print("\n[제어 주기 한도 대비 전 방어 스택 점유율]:")
    for name, ddl in CONTROL_RATES:
        print(f"  {name:8} (한도 {ddl/1000:.0f} ms): {fast_stack_us/ddl*100:6.2f} %  "
              f"({'든다' if fast_stack_us < ddl else '초과'})")
    print("\n[느린 계층] LLM 전략·분류 결정 지연(6.10.4 실측):")
    if llm_s:
        print(f"  LLM 결정 1건  {llm_s:.2f} s  =  {llm_us:,.0f} µs")
        print(f"  → 빠른 계층(전 방어 스택)보다 약 {ratio:,}배 느림 → 제어 경로 밖 자문 루프여야 함")

    fig_timescale(lat, ctrl_us, fast_stack_us, llm_s)

    out = {"check_latency_us": lat, "control_step_us": ctrl_us, "fast_stack_us": fast_stack_us,
           "control_rates": {n: {"deadline_us": d_, "stack_utilization_pct": round(fast_stack_us / d_ * 100, 2),
                                 "fits": fast_stack_us < d_} for n, d_ in CONTROL_RATES},
           "llm_decision_s": llm_s, "slow_over_fast_ratio": ratio}
    with open(os.path.join(RESULTS, "timescale_budget_log.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {RESULTS}/fig10_timescale.png, timescale_budget_log.json")


def fig_timescale(lat, ctrl_us, fast_stack_us, llm_s):
    rows = [(f"{k}", v / 1e6) for k, v in lat.items()]                 # → 초
    rows.append(("control step", ctrl_us / 1e6))
    rows.append(("FULL defense stack", fast_stack_us / 1e6))
    if llm_s:
        rows.append(("LLM decision", llm_s))
    rows.sort(key=lambda r: r[1])
    names = [r[0] for r in rows]
    vals = [r[1] for r in rows]
    colors = ["0.75"] * len(rows)
    for i, n in enumerate(names):
        if n == "LLM decision":
            colors[i] = "0.15"            # 느린 계층 강조(무채색 짙은 회색)
        elif n == "FULL defense stack":
            colors[i] = "0.45"

    plt.figure(figsize=(10.2, 5.2))
    y = np.arange(len(rows))
    plt.barh(y, vals, color=colors, edgecolor="black", linewidth=0.4)
    plt.yticks(y, names, fontsize=9)
    plt.xscale("log")
    plt.xlabel("wall-clock latency per invocation (s, log scale)")
    for name, ddl in CONTROL_RATES:
        plt.axvline(ddl / 1e6, ls="--", lw=1, color="gray")
        plt.text(ddl / 1e6, len(rows) - 0.4, f" {name} deadline", rotation=90,
                 va="top", ha="left", fontsize=7.5, color="gray")
    for yi, v in zip(y, vals):
        plt.text(v * 1.15, yi, f"{v*1e6:,.1f} µs" if v < 1e-3 else
                 (f"{v*1e3:,.2f} ms" if v < 1 else f"{v:,.2f} s"), va="center", fontsize=7.5)
    plt.title("Fig.10  Two-timescale budget: deterministic safety checks (in-loop, µs) "
              "vs LLM strategy (out-of-loop, s)", fontsize=10)
    plt.grid(alpha=0.3, axis="x", which="both")
    plt.xlim(min(vals) * 0.4, max(vals) * 4)
    plt.tight_layout()
    plt.savefig(os.path.join(RESULTS, "fig10_timescale.png"), dpi=130)
    plt.close()


if __name__ == "__main__":
    main()
