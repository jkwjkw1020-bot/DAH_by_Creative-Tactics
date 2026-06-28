#!/usr/bin/env python3
"""JANUS 다중시드 강건성 점검 — 헤드라인 수치가 단일 시드(42)의 우연이 아님을 입증한다.

6장의 모든 핵심 결과는 재현성을 위해 seed=42로 고정되어 있다. 그러나 세계 모델에는
실제 센서 잡음(GPS σ=0.2 m, 추측항법 σ=0.05 m, 보조 항법원 σ=0.3 m)이 들어 있어
시드를 바꾸면 잡음 시퀀스가 달라진다. 본 모듈은 동일한 시나리오·방어 구성을 N개의
독립 시드로 반복 실행하여, 각 헤드라인 지표의 평균±표준편차와 seed=42 값이 그 분포
안에 들어오는지를 보고한다. 즉 "결론은 특정 시드의 산물이 아니라 분포적으로 견고하다".

대상 지표(전부 기존 스크립트의 함수를 시드만 바꿔 재호출 — 기존 로그·결과는 불변):
  - 공방 교전(run_engagement)      : 방어 OFF/ON의 UAV 임무오차·UGV 표적오차
  - 출처증명(advanced, Exp-A)      : 홉바이홉(D3) vs 종단간(D6)의 UGV 표적오차
  - 탐지없는 생존성(advanced, Exp-B): 탐지전용 vs 다중항법원 투표의 평균 임무이탈
  - 보안게임(security_game)         : B=3 균형 게임값 V와 최선 고정태세 최악대응

실행: PYTHONPATH=src python3 src/robustness.py
"""
import os
import sys
import json
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import run_engagement as eng
import advanced_engagement as adv
import security_game as sg

RESULTS = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "docs", "results"))
os.makedirs(RESULTS, exist_ok=True)

# 시드 집합: 헤드라인 시드(42)를 맨 앞에 두고 추가 시드들로 분포를 본다.
SEEDS = [42] + [s for s in range(20) if s != 42]


def _engagement(seed):
    """공방 교전 한 회(방어 OFF/ON) → 4개 핵심 지표."""
    s_off = eng.summarize("off", *eng.run(defense_on=False, seed=seed))
    s_on = eng.summarize("on", *eng.run(defense_on=True, seed=seed))
    return {
        "uav_off": s_off["final_uav_pos_err"], "ugv_off": s_off["final_ugv_target_err"],
        "uav_on": s_on["final_uav_pos_err"], "ugv_on": s_on["final_ugv_target_err"],
    }


def _provenance(seed):
    """Exp-A: 장악 게이트웨이의 자기보고 위조 하에서 D3 vs D6의 UGV 표적오차."""
    _, _, _, o3 = adv.run(adv.SCHED_FORGE, dict(innov_threshold=3.0, use_provenance=False),
                          defense_on=True, seed=seed)
    _, _, _, o6 = adv.run(adv.SCHED_FORGE, dict(innov_threshold=3.0, use_provenance=True),
                          defense_on=True, seed=seed)
    return {"d3_ugv_err": o3.metrics[-1]["ugv_target_err"],
            "d6_ugv_err": o6.metrics[-1]["ugv_target_err"]}


def _resilient_nav(seed):
    """Exp-B: 임계 직하 스텔스 스푸핑 하에서 탐지전용 vs 다중항법원 투표의 평균 이탈."""
    out = {}
    for key, dk in (("detect_only", dict(innov_threshold=3.0, use_cusum=False, use_robust_nav=False)),
                    ("voting", dict(innov_threshold=3.0, use_cusum=False, use_robust_nav=True))):
        _, _, _, o = adv.run(adv.SCHED_STEALTH, dk, defense_on=True, seed=seed)
        err = [x["uav_pos_err"] for x in o.metrics]
        out[key] = float(np.mean(err[12:]))     # 공격 정착 후 구간 평균(원 스크립트와 동일)
    return out


def _security_game(seed):
    """B=3 보안게임 균형 게임값 V와 최선 고정태세의 최악대응(둘 다 잡음 의존)."""
    sg.SEED = seed                               # engage()가 호출 시점에 읽는 모듈 전역
    P = sg.feasible_postures(3)
    M, _, _ = sg.payoff_matrix(P)
    V, _, _ = sg.solve_zero_sum(M)
    best_pure_worst = min(float(M[:, j].max()) for j in range(len(P)))
    return {"game_V": float(V), "best_fixed_worst": best_pure_worst}


def _stats(values):
    a = np.array(values, float)
    return {"mean": round(float(a.mean()), 3), "std": round(float(a.std()), 3),
            "min": round(float(a.min()), 3), "max": round(float(a.max()), 3),
            "seed42": round(float(a[0]), 3)}     # SEEDS[0] == 42


def main():
    collectors = {}

    def add(d):
        for k, v in d.items():
            collectors.setdefault(k, []).append(v)

    print("=" * 78)
    print(f"JANUS 다중시드 강건성 점검 — N={len(SEEDS)} 시드 (헤드라인 seed=42 포함)")
    print("=" * 78)
    for i, s in enumerate(SEEDS):
        add(_engagement(s))
        add(_provenance(s))
        add(_resilient_nav(s))
        add(_security_game(s))
        print(f"  seed {s:>3} 완료 ({i + 1}/{len(SEEDS)})", end="\r")
    print(" " * 40, end="\r")

    stats = {k: _stats(v) for k, v in collectors.items()}

    labels = [
        ("uav_off", "교전 UAV 임무오차 (방어 OFF)", "m"),
        ("ugv_off", "교전 UGV 표적오차 (방어 OFF)", "m"),
        ("uav_on", "교전 UAV 임무오차 (방어 ON)", "m"),
        ("ugv_on", "교전 UGV 표적오차 (방어 ON)", "m"),
        ("d3_ugv_err", "출처증명 홉바이홉 D3 표적오차", "m"),
        ("d6_ugv_err", "출처증명 종단간 D6 표적오차", "m"),
        ("detect_only", "생존성 탐지전용 평균이탈", "m"),
        ("voting", "생존성 다중항법원 투표 평균이탈", "m"),
        ("game_V", "보안게임 B=3 균형 게임값 V", ""),
        ("best_fixed_worst", "보안게임 B=3 최선 고정태세 최악대응", ""),
    ]
    print(f"\n  {'지표':32} {'평균±표준편차':>18}   {'[min, max]':>16}   {'seed42':>8}")
    print("  " + "-" * 78)
    for key, name, unit in labels:
        st = stats[key]
        u = (" " + unit) if unit else ""
        print(f"  {name:32} {st['mean']:8.2f} ± {st['std']:6.2f}{u:>3}"
              f"   [{st['min']:6.2f}, {st['max']:6.2f}]   {st['seed42']:8.2f}")

    out = {"n_seeds": len(SEEDS), "seeds": SEEDS, "stats": stats}
    with open(os.path.join(RESULTS, "robustness_log.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {RESULTS}/robustness_log.json")


if __name__ == "__main__":
    main()
