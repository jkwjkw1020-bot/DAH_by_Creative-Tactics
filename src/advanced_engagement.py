#!/usr/bin/env python3
"""JANUS 심화 실험 — '신뢰 축이 무너졌을 때'의 방어를 입증한다 (6장 확장).

전제: 4장에서 게이트웨이를 신뢰 연쇄의 단일 실패점으로 규정하였다. 그렇다면
정상 키를 가진 채 장악된 게이트웨이, 그리고 탐지 임계 직하의 스텔스 공격처럼
'암호화·탐지가 실패하는' 최악의 경우에도 임무가 살아남는가?

Exp-A (교차도메인 출처증명) : 장악된 게이트웨이가 자기보고까지 위조하면 홉바이홉
  무결성 검증(D3)은 무력화된다. 그러나 UAV가 자신의 키로 서명한 종단간 출처증명
  토큰(D6)은 게이트웨이가 위조할 수 없으므로 표적 변조가 드러난다. → fig6
Exp-B (탐지 없는 생존성) : 임계 직하 스텔스 GPS 스푸핑은 탐지되지 않는다(6.8에서 입증).
  그러나 다중 항법원 중앙값 투표는 탐지 경보 없이도 단일 편향원을 기각하여 임무
  이탈을 잡음 수준으로 묶는다. → fig7

실행: PYTHONPATH=src python3 src/advanced_engagement.py
"""
import os
import sys
import json
import copy
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from janus.world import World, Vehicle
from janus.attack import RedAttacker
from janus.defense import BlueDefender
from janus.agents import RedTeamAgent, BlueTeamAgent, Orchestrator

RESULTS = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "docs", "results"))
os.makedirs(RESULTS, exist_ok=True)

UAV, UGV = 1, 2
UAV_TARGET = [60.0, 0.0, 20.0]
UGV_START = [0.0, -40.0, 0.0]
OFF = 99999.0   # 해당 공격 단계 비활성


def build_world():
    w = World()
    w.add(Vehicle(UAV, "uav", [0.0, 0.0, 20.0]))
    w.add(Vehicle(UGV, "ugv", UGV_START))
    w.get(UAV).set_target(UAV_TARGET)
    return w


def run(sched, defense_kwargs, defense_on=True, steps=32, dt=1.0, seed=42):
    np.random.seed(seed)
    w = build_world()
    red = RedTeamAgent(w, RedAttacker(w), copy.deepcopy(sched))
    blue = BlueTeamAgent(w, BlueDefender(w, **defense_kwargs), enabled=defense_on)
    orch = Orchestrator(w, red, blue)
    orch.run(steps, dt, np.array(UAV_TARGET, float), UGV)
    return w, red, blue, orch


# ============== Exp-A: 교차도메인 출처증명 vs 장악된 인증 게이트웨이 ==============
SCHED_FORGE = dict(
    uav=UAV, recon_t=2.0, mitm_t=3.0,
    inject_t=OFF, spoof_t=OFF, spoof_end=OFF, spoof_drift=[0, 0, 0], spoof_cap=None,
    lateral_t=6.0,          # ④ 표적 변조(횡적확산)
    forge_t=6.0,            # ④' 게이트웨이 자기보고까지 위조 → 홉바이홉(D3) 회피
    evade_t=OFF,
    fake_uav_target=UAV_TARGET, fake_ugv_target=[-30.0, 60.0, 0.0], telemetry_fake=UAV_TARGET,
)


def gw_tamper_detections(blue):
    return sum(1 for a in blue.d.alarms
               if a[1] in ("D3_gateway_tamper", "D6_provenance_mismatch", "D6_provenance_unsigned"))


def exp_a():
    configs = [
        ("No defense", dict(innov_threshold=3.0), False),
        ("Hop-by-hop (D3)", dict(innov_threshold=3.0, use_provenance=False), True),
        ("End-to-end (D6)", dict(innov_threshold=3.0, use_provenance=True), True),
    ]
    rows = []
    for name, dk, on in configs:
        w, red, blue, orch = run(SCHED_FORGE, dk, defense_on=on)
        rows.append({
            "config": name,
            "ugv_target_err": orch.metrics[-1]["ugv_target_err"],
            "gw_detections": gw_tamper_detections(blue),
        })
    return rows


def fig_a(rows):
    names = [r["config"] for r in rows]
    errs = [r["ugv_target_err"] for r in rows]
    colors = ["crimson", "darkorange", "seagreen"]
    plt.figure(figsize=(8.4, 4.3))
    bars = plt.bar(names, errs, color=colors[:len(names)], width=0.55)
    for i, r in enumerate(rows):
        plt.text(i, errs[i] + max(errs) * 0.02 + 0.3,
                 f"{r['gw_detections']} det", ha="center", fontsize=9)
    plt.ylabel("UGV target error (m)")
    plt.title("Fig.6  Compromised authenticated gateway: hop-by-hop fails, end-to-end provenance holds")
    plt.grid(alpha=0.3, axis="y"); plt.tight_layout()
    plt.savefig(os.path.join(RESULTS, "fig6_provenance.png"), dpi=130); plt.close()


# ============== Exp-B: 탐지 없는 생존성 (다중 항법원 투표) vs 스텔스 스푸핑 ==============
SCHED_STEALTH = dict(
    uav=UAV, recon_t=2.0, mitm_t=3.0,
    inject_t=OFF, lateral_t=OFF, evade_t=OFF,
    spoof_t=4.0, spoof_end=OFF, spoof_drift=[1.0, 0.0, 0.0], spoof_cap=2.5,   # 임계(3.0) 직하 스텔스
    fake_uav_target=UAV_TARGET, fake_ugv_target=UGV_START, telemetry_fake=UAV_TARGET,
)


def spoof_detections(blue):
    return sum(1 for a in blue.d.alarms if a[1] in ("D1_innovation", "D1_cusum"))


def exp_b():
    configs = [
        ("Detection-only", dict(innov_threshold=3.0, use_cusum=False, use_robust_nav=False)),
        ("+ Resilient nav (voting)", dict(innov_threshold=3.0, use_cusum=False, use_robust_nav=True)),
    ]
    series, rows = [], []
    for name, dk in configs:
        w, red, blue, orch = run(SCHED_STEALTH, dk, defense_on=True)
        t = [x["t"] for x in orch.metrics]
        err = [x["uav_pos_err"] for x in orch.metrics]
        series.append((name, t, err))
        rows.append({
            "config": name,
            "mean_uav_pos_err": round(float(np.mean(err[12:])), 2),
            "final_uav_pos_err": orch.metrics[-1]["uav_pos_err"],
            "spoof_detections": spoof_detections(blue),
        })
    return series, rows


def fig_b(series):
    plt.figure(figsize=(8.4, 4.3))
    colors = {"Detection-only": "crimson", "+ Resilient nav (voting)": "seagreen"}
    for name, t, err in series:
        plt.plot(t, err, lw=2, color=colors[name], label=f"{name} (0 detections)")
    plt.axhline(2.5, ls=":", c="gray", lw=1, label="stealth bias cap (2.5 m, below threshold)")
    plt.xlabel("time (s)"); plt.ylabel("UAV position error vs mission target (m)")
    plt.title("Fig.7  Surviving an UNDETECTED stealth spoof via multi-source nav voting")
    plt.legend(); plt.grid(alpha=0.3); plt.tight_layout()
    plt.savefig(os.path.join(RESULTS, "fig7_resilient_nav.png"), dpi=130); plt.close()


def main():
    rows_a = exp_a()
    fig_a(rows_a)
    series_b, rows_b = exp_b()
    fig_b(series_b)

    print("=" * 82)
    print("JANUS 심화 실험 — 신뢰 축이 무너졌을 때의 방어 (Exp-A 출처증명 / Exp-B 생존성)")
    print("=" * 82)
    print("\n[Exp-A] 장악된(인증된) 게이트웨이가 자기보고까지 위조 → 표적 변조 (fig6):")
    print(f"  {'방어 구성':22} | {'UGV 표적오차':>11} | {'게이트웨이 탐지':>12}")
    print("  " + "-" * 54)
    for r in rows_a:
        print(f"  {r['config']:22} | {r['ugv_target_err']:>9.1f} m | {r['gw_detections']:>10} 건")

    print("\n[Exp-B] 임계 직하 스텔스 GPS 스푸핑(탐지 0건) — 다중 항법원 투표의 생존성 (fig7):")
    print(f"  {'방어 구성':26} | {'평균 이탈':>8} | {'최종 이탈':>8} | {'스푸핑 탐지':>9}")
    print("  " + "-" * 64)
    for r in rows_b:
        print(f"  {r['config']:26} | {r['mean_uav_pos_err']:>6} m | {r['final_uav_pos_err']:>6} m | {r['spoof_detections']:>7} 건")

    with open(os.path.join(RESULTS, "advanced_log.json"), "w") as f:
        json.dump({"exp_a_provenance": rows_a, "exp_b_resilient_nav": rows_b},
                  f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {RESULTS}/fig6_provenance.png, fig7_resilient_nav.png, advanced_log.json")


if __name__ == "__main__":
    main()
