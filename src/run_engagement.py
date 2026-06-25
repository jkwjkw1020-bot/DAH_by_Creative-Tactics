#!/usr/bin/env python3
"""JANUS 공방 교전 시뮬레이션 — 4·5·6장 통합 데모.

방어 OFF(공격 성공 입증) vs 방어 ON(방어 성공 입증) 두 모드를 실행하고
로그(JSON)·그래프(PNG)·콘솔 요약을 생성한다.

실행:
    PYTHONPATH=src python3 src/run_engagement.py
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

np.random.seed(42)

RESULTS = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "docs", "results"))
os.makedirs(RESULTS, exist_ok=True)

UAV, UGV = 1, 2
UAV_TARGET = [60.0, 0.0, 20.0]    # UAV 원래 정찰 표적
UGV_START = [0.0, -40.0, 0.0]

SCHED = dict(
    uav=UAV,
    recon_t=4.0, mitm_t=5.0, inject_t=6.0, spoof_t=6.0, spoof_end=30.0,
    lateral_t=12.0, evade_t=16.0,
    fake_uav_target=[60.0, 40.0, 20.0],   # ③ 주입: UAV를 측면으로 끌어냄
    spoof_drift=[1.2, 0.0, 0.0],          # ③ 매 스텝 +1.2 m GPS bias 누적(점진)
    fake_ugv_target=[-30.0, 60.0, 0.0],   # ④ UGV 오표적
    telemetry_fake=UAV_TARGET,            # ⑥ GCS엔 정상 도달처럼 위조
)


def build_world():
    w = World()
    w.add(Vehicle(UAV, "uav", [0.0, 0.0, 20.0]))
    w.add(Vehicle(UGV, "ugv", UGV_START))
    w.get(UAV).set_target(UAV_TARGET)
    return w


def run(defense_on, steps=32, dt=1.0):
    np.random.seed(42)  # 두 모드 동일 잡음 시퀀스(공정 비교)
    w = build_world()
    red = RedTeamAgent(w, RedAttacker(w), copy.deepcopy(SCHED))
    blue = BlueTeamAgent(w, BlueDefender(w, innov_threshold=3.0), enabled=defense_on)
    orch = Orchestrator(w, red, blue)
    orch.run(steps, dt, np.array(UAV_TARGET, float), UGV)
    return w, red, blue, orch


def summarize(tag, w, red, blue, orch):
    m = orch.metrics
    final = m[-1]
    return {
        "mode": tag,
        "defense": blue.enabled,
        "final_uav_pos_err": final["uav_pos_err"],
        "max_uav_innov": round(max(x["uav_innov"] for x in m), 2),
        "final_ugv_target_err": final["ugv_target_err"],
        "detections": blue.detections,
        "blocks": blue.blocks,
        "recoveries": blue.recoveries,
        "attacker_events": len(red.atk.log),
        "defender_alarms": len(blue.d.alarms),
    }


def make_graphs(orch_off, orch_on, s0, s1):
    t_off = [x["t"] for x in orch_off.metrics]
    t_on = [x["t"] for x in orch_on.metrics]

    # fig1: GPS 스푸핑 탐지(이노베이션)
    plt.figure(figsize=(8, 4))
    plt.plot(t_off, [x["uav_innov"] for x in orch_off.metrics], label="Defense OFF", color="crimson", lw=2)
    plt.plot(t_on, [x["uav_innov"] for x in orch_on.metrics], label="Defense ON", color="seagreen", lw=2)
    plt.axhline(3.0, ls="--", c="gray", label="Detection threshold")
    plt.xlabel("time (s)"); plt.ylabel("EKF innovation |GPS - IMU| (m)")
    plt.title("Fig.1  GPS Spoofing Detection (UAV)")
    plt.legend(); plt.grid(alpha=0.3); plt.tight_layout()
    plt.savefig(os.path.join(RESULTS, "fig1_innovation.png"), dpi=130); plt.close()

    # fig2: UAV 임무 이탈
    plt.figure(figsize=(8, 4))
    plt.plot(t_off, [x["uav_pos_err"] for x in orch_off.metrics], label="Defense OFF", color="crimson", lw=2)
    plt.plot(t_on, [x["uav_pos_err"] for x in orch_on.metrics], label="Defense ON", color="seagreen", lw=2)
    plt.xlabel("time (s)"); plt.ylabel("UAV position error vs mission target (m)")
    plt.title("Fig.2  UAV Mission Deviation under Attack")
    plt.legend(); plt.grid(alpha=0.3); plt.tight_layout()
    plt.savefig(os.path.join(RESULTS, "fig2_uav_error.png"), dpi=130); plt.close()

    # fig3: 영향 스코어보드
    labels = ["UAV pos err (m)", "Max innovation (m)", "UGV target err (m)"]
    off = [s0["final_uav_pos_err"], s0["max_uav_innov"], s0["final_ugv_target_err"]]
    on = [s1["final_uav_pos_err"], s1["max_uav_innov"], s1["final_ugv_target_err"]]
    x = np.arange(len(labels)); wd = 0.35
    plt.figure(figsize=(8, 4))
    plt.bar(x - wd / 2, off, wd, label="Defense OFF", color="crimson")
    plt.bar(x + wd / 2, on, wd, label="Defense ON", color="seagreen")
    plt.xticks(x, labels, fontsize=9); plt.ylabel("value")
    plt.title("Fig.3  Attack Impact: Defense OFF vs ON")
    plt.legend(); plt.grid(alpha=0.3, axis="y"); plt.tight_layout()
    plt.savefig(os.path.join(RESULTS, "fig3_scoreboard.png"), dpi=130); plt.close()


def main():
    w0, red0, blue0, orch0 = run(defense_on=False)
    w1, red1, blue1, orch1 = run(defense_on=True)
    s0 = summarize("ATTACK (defense OFF)", w0, red0, blue0, orch0)
    s1 = summarize("DEFENSE (defense ON)", w1, red1, blue1, orch1)

    make_graphs(orch0, orch1, s0, s1)

    out = {
        "summary": [s0, s1],
        "off_metrics": orch0.metrics,
        "on_metrics": orch1.metrics,
        "attacker_log": [list(map(str, e)) for e in red0.atk.log],
        "defender_alarms_on": [list(map(str, e)) for e in blue1.d.alarms],
        "blue_explain_on": [list(map(str, e)) for e in blue1.explain],
    }
    with open(os.path.join(RESULTS, "engagement_log.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("=" * 72)
    print("JANUS 공방 교전 결과 요약  (Red vs Blue, ArduPilot-style SITL-lite)")
    print("=" * 72)
    for s in (s0, s1):
        print(f"\n[{s['mode']}]  defense={s['defense']}")
        print(f"  UAV 임무위치오차 : {s['final_uav_pos_err']:7.1f} m")
        print(f"  최대 이노베이션  : {s['max_uav_innov']:7.1f} m  (탐지임계 3.0)")
        print(f"  UGV 표적오차     : {s['final_ugv_target_err']:7.1f} m")
        print(f"  탐지/차단/복구   : {s['detections']} / {s['blocks']} / {s['recoveries']}")
    print("\n[설명가능 방어 로그 (Defense ON, 상위 8건)]")
    for rec in blue1.explain[:8]:
        print(f"  t={rec[0]}s  {rec[1]}")
    print(f"\n결과 그래프·로그 저장 위치: {RESULTS}")
    print("  - fig1_innovation.png / fig2_uav_error.png / fig3_scoreboard.png / engagement_log.json")


if __name__ == "__main__":
    main()
