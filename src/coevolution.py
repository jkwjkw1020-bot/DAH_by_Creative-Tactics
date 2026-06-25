#!/usr/bin/env python3
"""JANUS 반복 적대적 공진화(Iterated Adversarial Co-Evolution) — 6장 확장.

Part A. 공격 변종 vs 방어 비교(단일 라운드 스냅샷) → fig4
Part B. 다중 라운드 공진화: 매 라운드 공격이 현재 방어에 대한 '무탐지 최대 피해' 전술(cap)을
        탐색(best-response)하고, 방어는 그 약점을 보완(CUSUM slack을 공격 cap 직하로 조임).
        공격의 무탐지 피해가 잡음 수준으로 수렴하거나, 방어가 오탐(FP) 한계에 도달하면 종료 → fig5.

동역학: 공격은 탐지를 피하려 bias(cap)를 낮추고(피해↓), 방어는 누적검정 임계를 조인다.
단 방어를 과하게 조이면 정상 비행에서 오탐이 발생 → 이 트레이드오프가 균형(수렴)을 만든다.

실행: python3 src/coevolution.py
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
THR = 3.0
NOISE_FLOOR = 0.5            # 정상 비행 이노베이션 잡음 수준 → CUSUM slack 하한(FP 방지)
CONVERGE_HARM = 0.7          # 무탐지 피해가 이 값 미만이면 사실상 무해(수렴)

BASE_SCHED = dict(uav=UAV, recon_t=4.0, mitm_t=5.0, inject_t=6.0, spoof_t=6.0, spoof_end=999.0,
                  lateral_t=12.0, evade_t=16.0, fake_uav_target=[60.0, 40.0, 20.0],
                  spoof_drift=[0.8, 0, 0], spoof_cap=None, fake_ugv_target=[-30.0, 60.0, 0.0],
                  telemetry_fake=UAV_TARGET)

CAPS = [None, 3.5, 3.0, 2.5, 2.2, 2.0, 1.7, 1.5, 1.3, 1.0, 0.8, 0.6, 0.4]


def arena(spoof_cap, defense_kwargs, attack_on=True, steps=40, dt=1.0, seed=42):
    np.random.seed(seed)
    w = World()
    w.add(Vehicle(UAV, "uav", [0.0, 0.0, 20.0]))
    w.add(Vehicle(UGV, "ugv", [0.0, -40.0, 0.0]))
    w.get(UAV).set_target(UAV_TARGET)
    sched = copy.deepcopy(BASE_SCHED)
    if not attack_on:
        for k in ("recon_t", "mitm_t", "inject_t", "spoof_t", "lateral_t", "evade_t"):
            sched[k] = 99999.0
    else:
        sched["spoof_cap"] = spoof_cap
    red = RedTeamAgent(w, RedAttacker(w), sched)
    blue = BlueTeamAgent(w, BlueDefender(w, **defense_kwargs), enabled=True)
    orch = Orchestrator(w, red, blue)
    orch.run(steps, dt, np.array(UAV_TARGET, float), UGV)
    m = orch.metrics
    spoof_det = sum(1 for a in blue.d.alarms if a[1] in ("D1_innovation", "D1_cusum"))
    return {"mean_uav_pos_err": round(float(np.mean([x["uav_pos_err"] for x in m[12:]])), 2),
            "spoof_detections": spoof_det}


def best_undetected_attack(defense_kwargs):
    """현재 방어에 대해 '탐지 0건이면서 피해 최대'인 공격(cap) = 공격의 best-response."""
    best = {"cap": None, "harm": 0.0}
    for cap in CAPS:
        r = arena(cap, defense_kwargs, attack_on=True)
        if r["spoof_detections"] == 0 and r["mean_uav_pos_err"] > best["harm"]:
            best = {"cap": cap, "harm": r["mean_uav_pos_err"]}
    return best


def false_positives(defense_kwargs):
    """공격이 전혀 없는 정상 비행에서의 GPS 탐지 수 = 오탐(FP)."""
    return arena(None, defense_kwargs, attack_on=False)["spoof_detections"]


def describe(d):
    if d.get("use_cusum"):
        return f"fixed+CUSUM(slack={d['cusum_slack']}, H={d['cusum_h']})"
    return "fixed threshold only"


# ---------- Part A: 단일 라운드 변종 비교 (fig4) ----------
def part_a():
    variants = [("Aggressive", None), ("Stealth cap=2.8", 2.8), ("Stealth cap=2.5", 2.5)]
    rows = []
    for name, cap in variants:
        v1 = arena(cap, dict(innov_threshold=THR, use_cusum=False))
        v2 = arena(cap, dict(innov_threshold=THR, use_cusum=True, cusum_slack=1.5, cusum_h=6.0))
        rows.append((name, v1, v2))
    names = [r[0] for r in rows]
    v1e = [r[1]["mean_uav_pos_err"] for r in rows]
    v2e = [r[2]["mean_uav_pos_err"] for r in rows]
    x = np.arange(len(names)); wd = 0.35
    plt.figure(figsize=(9, 4.5))
    plt.bar(x - wd / 2, v1e, wd, label="Defense v1 (fixed threshold)", color="darkorange")
    plt.bar(x + wd / 2, v2e, wd, label="Defense v2 (+ CUSUM)", color="seagreen")
    for xi in range(len(names)):
        plt.text(xi - wd / 2, v1e[xi] + 0.05, f"{rows[xi][1]['spoof_detections']} det", ha="center", fontsize=8)
        plt.text(xi + wd / 2, v2e[xi] + 0.05, f"{rows[xi][2]['spoof_detections']} det", ha="center", fontsize=8)
    plt.ylabel("mean UAV position error (m)")
    plt.title("Fig.4  Stealth weakness found & patched (single round)")
    plt.xticks(x, names, fontsize=9); plt.legend(); plt.grid(alpha=0.3, axis="y"); plt.tight_layout()
    plt.savefig(os.path.join(RESULTS, "fig4_coevolution.png"), dpi=130); plt.close()
    return rows


# ---------- Part B: 반복 공진화 (fig5) ----------
def part_b(max_rounds=8):
    defense = dict(innov_threshold=THR, use_cusum=False)
    history = []
    verdict = "최대 라운드 도달"
    for rnd in range(max_rounds):
        ba = best_undetected_attack(defense)
        cur_fp = false_positives(defense)
        history.append({"round": rnd, "defense": describe(defense), "attack_cap": ba["cap"],
                        "undetected_harm": ba["harm"], "fp": cur_fp})
        if ba["harm"] < CONVERGE_HARM:
            verdict = f"수렴: 무탐지 공격 피해가 {ba['harm']} m로 잡음 수준 → 방어 우위 균형 도달"
            break
        # 방어 보완: 이 공격(cap)을 누적탐지하도록 CUSUM slack을 cap 직하로 조임
        nd = dict(defense); nd["use_cusum"] = True
        target_cap = ba["cap"] if ba["cap"] is not None else 3.0
        nd["cusum_slack"] = round(max(NOISE_FLOOR, target_cap - 0.4), 2)
        nd["cusum_h"] = 4.0
        if false_positives(nd) > 0:
            verdict = f"수렴: 방어가 오탐 한계 도달(slack={nd['cusum_slack']}에서 FP 발생) → 직전 방어가 최적"
            break
        defense = nd

    rs = [h["round"] for h in history]
    harm = [h["undetected_harm"] for h in history]
    plt.figure(figsize=(9, 4.5))
    plt.plot(rs, harm, "o-", color="crimson", lw=2, label="Attacker max UNDETECTED harm (m)")
    plt.axhline(CONVERGE_HARM, ls="--", c="gray", label="Convergence band (~noise floor)")
    for h in history:
        plt.annotate(h["defense"].replace("fixed threshold only", "v0: fixed").replace("fixed+CUSUM", "CUSUM"),
                     (h["round"], h["undetected_harm"]), textcoords="offset points",
                     xytext=(0, 9), fontsize=7, ha="center")
    plt.xlabel("co-evolution round"); plt.ylabel("attacker undetected harm (m)")
    plt.title("Fig.5  Iterated Red-Blue Co-Evolution converges (attack harm -> noise floor)")
    plt.legend(); plt.grid(alpha=0.3); plt.tight_layout()
    plt.savefig(os.path.join(RESULTS, "fig5_convergence.png"), dpi=130); plt.close()
    return history, verdict


def main():
    rows_a = part_a()
    history, verdict = part_b()

    print("=" * 82)
    print("JANUS 반복 적대적 공진화 (Iterated Red-Blue Co-Evolution)")
    print("=" * 82)
    print("\n[Part A] 단일 라운드 약점 비교 (fig4):")
    for n, a, b in rows_a:
        print(f"  {n:18}: v1 {a['mean_uav_pos_err']}m/{a['spoof_detections']}det "
              f"→ v2(+CUSUM) {b['mean_uav_pos_err']}m/{b['spoof_detections']}det")

    print("\n[Part B] 다중 라운드 공진화 — 공격 best-response ↔ 방어 보완 (fig5):")
    print(f"  {'R':>2} | {'방어 구성':34} | {'공격cap':>7} | {'무탐지피해':>9} | {'FP':>3}")
    print("  " + "-" * 72)
    for h in history:
        cap = "inf" if h["attack_cap"] is None else h["attack_cap"]
        print(f"  {h['round']:>2} | {h['defense']:34} | {str(cap):>7} | {h['undetected_harm']:>8}m | {h['fp']:>3}")
    print(f"\n  => {verdict}")
    print(f"  => 공격 무탐지 피해: {history[0]['undetected_harm']}m (R0) → {history[-1]['undetected_harm']}m (R{history[-1]['round']}),"
          f" {len(history)} 라운드 만에 안정")

    with open(os.path.join(RESULTS, "coevolution_log.json"), "w") as f:
        json.dump({"part_a": [{"variant": n, "v1": a, "v2": b} for n, a, b in rows_a],
                   "part_b": history, "verdict": verdict}, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {RESULTS}/fig4_coevolution.png, fig5_convergence.png, coevolution_log.json")


if __name__ == "__main__":
    main()
