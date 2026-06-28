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


def _run(sched, defense_kwargs, steps=32, seed=42):
    np.random.seed(seed)
    w = World()
    w.add(Vehicle(1, "uav", [0.0, 0.0, 20.0]))
    w.add(Vehicle(2, "ugv", [0.0, -40.0, 0.0]))
    w.get(1).set_target([60.0, 0.0, 20.0])
    red = RedTeamAgent(w, RedAttacker(w), dict(sched))
    blue = BlueTeamAgent(w, BlueDefender(w, **defense_kwargs), enabled=True)
    orch = Orchestrator(w, red, blue)
    orch.run(steps, 1.0, np.array([60.0, 0.0, 20.0], float), 2)
    return w, red, blue, orch


_OFF = 99999.0


def test_provenance_beats_compromised_gateway():
    """장악된 게이트웨이가 자기보고까지 위조하면 홉바이홉(D3)은 뚫리지만, 종단간 출처증명(D6)은 막아야 한다."""
    sched = dict(uav=1, recon_t=2, mitm_t=3, inject_t=_OFF, spoof_t=_OFF, spoof_end=_OFF,
                 spoof_drift=[0, 0, 0], spoof_cap=None, lateral_t=6, forge_t=6, evade_t=_OFF,
                 fake_uav_target=[60.0, 0.0, 20.0], fake_ugv_target=[-30.0, 60.0, 0.0],
                 telemetry_fake=[60.0, 0.0, 20.0])
    _, _, b_hop, o_hop = _run(sched, dict(use_provenance=False))
    _, _, b_e2e, o_e2e = _run(sched, dict(use_provenance=True))
    d3 = sum(1 for a in b_hop.d.alarms if a[1] == "D3_gateway_tamper")
    d6 = sum(1 for a in b_e2e.d.alarms if a[1].startswith("D6_"))
    assert d3 == 0 and o_hop.metrics[-1]["ugv_target_err"] > 50.0, "홉바이홉은 위조된 자기보고에 뚫려야 한다"
    assert d6 > 0 and o_e2e.metrics[-1]["ugv_target_err"] < 5.0, "종단간 출처증명은 변조를 탐지·복구해야 한다"
    print(f"[OK] 출처증명: 홉바이홉 D3 {d3}건/오차 {o_hop.metrics[-1]['ugv_target_err']:.1f}m "
          f"→ 종단간 D6 {d6}건/오차 {o_e2e.metrics[-1]['ugv_target_err']:.1f}m")


def test_resilient_nav_survives_undetected_stealth():
    """임계 직하 스텔스 스푸핑(탐지 0건)에서도 다중 항법원 투표는 이탈을 잡음 수준으로 묶어야 한다."""
    sched = dict(uav=1, recon_t=2, mitm_t=3, inject_t=_OFF, lateral_t=_OFF, evade_t=_OFF,
                 spoof_t=4, spoof_end=_OFF, spoof_drift=[1.0, 0, 0], spoof_cap=2.5,
                 fake_uav_target=[60.0, 0.0, 20.0], fake_ugv_target=[0.0, -40.0, 0.0],
                 telemetry_fake=[60.0, 0.0, 20.0])
    _, _, b_det, o_det = _run(sched, dict(innov_threshold=3.0, use_robust_nav=False))
    _, _, b_rob, o_rob = _run(sched, dict(innov_threshold=3.0, use_robust_nav=True))
    det_only = sum(1 for a in b_det.d.alarms if a[1].startswith("D1_"))
    det_rob = sum(1 for a in b_rob.d.alarms if a[1].startswith("D1_"))
    assert det_only == 0 and o_det.metrics[-1]["uav_pos_err"] > 1.5, "스텔스는 탐지를 피하며 이탈을 만들어야 한다"
    assert det_rob == 0 and o_rob.metrics[-1]["uav_pos_err"] < 1.0, "투표는 무탐지에도 이탈을 억제해야 한다"
    print(f"[OK] 생존성: 탐지전용 {det_only}탐지/{o_det.metrics[-1]['uav_pos_err']:.1f}m "
          f"→ 다중항법원 {det_rob}탐지/{o_rob.metrics[-1]['uav_pos_err']:.1f}m")


def test_security_game_mixing_beats_any_fixed_posture():
    """전술공간 보안게임 B=3: 어떤 고정 방어 태세도 뚫리며, 혼합전략이 그보다 우월해야 한다."""
    import security_game as sg
    P = sg.feasible_postures(3)
    M, _, _ = sg.payoff_matrix(P)
    V, x, y = sg.solve_zero_sum(M)
    fixed_worst = min(float(M[:, j].max()) for j in range(len(P)))
    assert abs(x.sum() - 1) < 1e-6 and abs(y.sum() - 1) < 1e-6, "혼합전략은 확률분포여야 한다"
    assert V < fixed_worst - 0.1, f"혼합전략이 최선의 고정 태세보다 우월해야 한다(V={V:.2f}, 고정={fixed_worst:.2f})"
    print(f"[OK] 보안게임 B=3: 고정 최악 {fixed_worst:.2f} → 혼합 V {V:.2f} (가용태세 {len(P)})")


def test_security_game_budget_monotone():
    """방어 예산이 늘면 균형 게임값(잔여 임무영향)이 감소(또는 유지)해야 한다."""
    import security_game as sg

    def value(B):
        P = sg.feasible_postures(B)
        M, _, _ = sg.payoff_matrix(P)
        return sg.solve_zero_sum(M)[0]

    v_low, v_high = value(2), value(5)
    assert v_low >= v_high - 1e-6, f"예산↑ → 게임값↓ 이어야 한다(V2={v_low:.2f}, V5={v_high:.2f})"
    print(f"[OK] 보안-비용 단조성: V(B=2)={v_low:.2f} ≥ V(B=5)={v_high:.2f}")


def test_replay_defeats_signature_only_freshness_stops():
    """리플레이는 서명검증(D2)을 통과하고 오직 신선도 검사(D7)만이 막아야 한다."""
    import security_game as sg
    rep = sg._base(); rep["replay_t"] = 6.0; rep["replay_target"] = [0.0, 0.0, 20.0]; rep["replay_stale"] = 10.0
    d_d2 = sg.engage(rep, sg.posture_kwargs(frozenset({"D2"})))["damage"]
    d_d7 = sg.engage(rep, sg.posture_kwargs(frozenset({"D7"})))["damage"]
    assert d_d2 > 50.0, f"서명검증만으로는 리플레이를 막지 못해야 한다(피해 {d_d2:.1f} m)"
    assert d_d7 < 5.0, f"신선도 검사가 리플레이를 막아야 한다(피해 {d_d7:.1f} m)"
    print(f"[OK] 리플레이: D2만 {d_d2:.1f}m(관통) → D7 {d_d7:.1f}m(차단)")


def test_portfolio_extension_rebalances_to_d7():
    """공격에 리플레이·탈동기가 더해지면 D7이 새 하중지지 불변식으로 부상해야 한다."""
    import portfolio_extension as pe
    base, ext = pe.base_eq(4), pe.ext_eq(4)
    assert base["marg"].get("D7", 0.0) < 0.05, "기존 포트폴리오에서는 D7이 사용되지 않아야 한다"
    assert ext["marg"]["D7"] > 0.3, f"확장 포트폴리오에서는 D7이 하중지지여야 한다(가동 {ext['marg']['D7']:.2f})"
    print(f"[OK] 포트폴리오 확장: D7 가동확률 base {base['marg'].get('D7', 0.0):.2f} → ext {ext['marg']['D7']:.2f}")


def test_robustness_gap_holds_across_seeds():
    """헤드라인(방어 효과)이 단일 시드가 아니라 여러 시드에서 분포적으로 성립해야 한다."""
    import run_engagement as eng
    for seed in (1, 7, 13):
        off = eng.run(defense_on=False, seed=seed)[3].metrics[-1]["uav_pos_err"]
        on = eng.run(defense_on=True, seed=seed)[3].metrics[-1]["uav_pos_err"]
        assert off > 40.0, f"seed {seed}: 방어 미적용 이탈이 충분히 커야 한다({off:.1f} m)"
        assert on < 2.0, f"seed {seed}: 방어 적용 시 임무가 보전돼야 한다({on:.1f} m)"
    print("[OK] 강건성: 3개 시드 모두 방어 미적용>40m·적용<2m (헤드라인 분포 안정)")


def test_formal_verification_minimal_safe_set():
    """형식검증(z3): {D2,D6,D7}는 전 공격 UNSAT(증명적 안전), 홉바이홉(D2,D3)은 forge가 SAT(반례 존재),
    임계탐지(D1)는 스텔스 사각지대(SAT)·다중항법원 투표(NAV)는 안전(UNSAT)."""
    import formal_verification as fv
    assert fv.authenticity_safe({"D2", "D6", "D7"}), "최소 안전 집합 {D2,D6,D7}은 모든 공격을 막아야 한다"
    assert fv.authenticity_query({"D2", "D3"}, "forge")[0] == "SAT", "홉바이홉은 forge에 뚫려야 한다(z3 반례)"
    assert fv.minimal_safe_sets()[0] == [{"D2", "D6", "D7"}], "유일한 극소 안전 집합은 {D2,D6,D7}이어야 한다"
    assert fv.survivability_query({"D1"})[0] == "SAT" and fv.survivability_query({"NAV"})[0] == "UNSAT", \
        "임계탐지는 스텔스 사각지대(SAT), 투표는 탐지 없이 안전(UNSAT)이어야 한다"
    print("[OK] 형식검증: {D2,D6,D7} 증명적 안전·홉바이홉 forge 반례·투표 생존성(z3)")


if __name__ == "__main__":
    test_defense_detects_attack()
    test_attack_succeeds_without_defense()
    test_provenance_beats_compromised_gateway()
    test_resilient_nav_survives_undetected_stealth()
    test_security_game_mixing_beats_any_fixed_posture()
    test_security_game_budget_monotone()
    test_replay_defeats_signature_only_freshness_stops()
    test_portfolio_extension_rebalances_to_d7()
    test_robustness_gap_holds_across_seeds()
    test_formal_verification_minimal_safe_set()
    print("스모크 테스트 통과")
