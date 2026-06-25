#!/usr/bin/env python3
"""JANUS 스모크 테스트 — 모듈 import 및 1회 공방 교전 동작을 검증한다.

실행: python3 tests/test_smoke.py
"""
import os
import sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from janus.world import World, Vehicle
from janus.attack import RedAttacker
from janus.defense import BlueDefender
from janus.agents import RedTeamAgent, BlueTeamAgent, Orchestrator


def _build():
    w = World()
    w.add(Vehicle(1, "uav", [0.0, 0.0, 20.0]))
    w.add(Vehicle(2, "ugv", [0.0, -40.0, 0.0]))
    w.get(1).set_target([60.0, 0.0, 20.0])
    sched = dict(uav=1, recon_t=2, mitm_t=3, inject_t=4, spoof_t=4, spoof_end=999,
                 lateral_t=6, evade_t=8, fake_uav_target=[60.0, 40.0, 20.0],
                 spoof_drift=[1.0, 0, 0], spoof_cap=None,
                 fake_ugv_target=[-30.0, 60.0, 0.0], telemetry_fake=[60.0, 0.0, 20.0])
    return w, sched


def test_defense_detects_attack():
    """방어가 활성화되면 공격을 탐지하고 임무를 보전해야 한다."""
    np.random.seed(0)
    w, sched = _build()
    red = RedTeamAgent(w, RedAttacker(w), sched)
    blue = BlueTeamAgent(w, BlueDefender(w), enabled=True)
    orch = Orchestrator(w, red, blue)
    orch.run(20, 1.0, np.array([60.0, 0.0, 20.0], float), 2)
    assert len(orch.metrics) == 20, "메트릭 수가 스텝 수와 일치해야 한다"
    assert blue.detections > 0, "방어는 공격을 한 건 이상 탐지해야 한다"
    print(f"[OK] 방어 활성: 탐지 {blue.detections}건, 차단 {blue.blocks}건, 복구 {blue.recoveries}건")


def test_attack_succeeds_without_defense():
    """방어가 없으면 공격이 UAV를 임무 목표에서 유의하게 이탈시켜야 한다."""
    np.random.seed(0)
    w, sched = _build()
    red = RedTeamAgent(w, RedAttacker(w), sched)
    blue = BlueTeamAgent(w, BlueDefender(w), enabled=False)
    orch = Orchestrator(w, red, blue)
    orch.run(20, 1.0, np.array([60.0, 0.0, 20.0], float), 2)
    final_err = orch.metrics[-1]["uav_pos_err"]
    assert final_err > 5.0, f"방어 부재 시 UAV가 이탈해야 한다 (실제 {final_err} m)"
    print(f"[OK] 방어 비활성: UAV 임무 이탈 {final_err} m")


if __name__ == "__main__":
    test_defense_detects_attack()
    test_attack_succeeds_without_defense()
    print("스모크 테스트 통과")
