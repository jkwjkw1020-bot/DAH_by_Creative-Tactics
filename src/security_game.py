#!/usr/bin/env python3
"""JANUS 전술공간 보안게임(Security Game) — 6장 확장(6.10).

6.8의 공진화는 단일 파라미터(스텔스 cap) 탐색이었다. 본 모듈은 이를 진짜 '전략 대결'로
일반화한다. 공격은 킬체인 전술의 *포트폴리오*에서 무엇을 칠지 고르고, 방어는 제한된
탐지·대응 *예산* 안에서 어떤 불변식을 가동할지 고른다. 이것은 Stackelberg 보안게임
(제한된 자원으로 표적을 커버, 공격은 빈틈을 침투)의 구조와 같다 [16, 19].

각 (공격 전술, 방어 태세) 쌍을 실제 교전 시뮬레이터로 돌려 복합 교전점수(본선 채점
하버스의 원형)를 산출하고, 그 행렬에서 minimax 혼합전략 균형을 LP로 푼다. 결과로
  (1) 어떤 단일 방어 태세도 공격 최적대응에 뚫린다 → 무작위·다변화 방어의 필요(정량적 심층방어)
  (2) 균형 방어는 예산을 여러 불변식에 분산하는 혼합전략
  (3) 예산 B↑ → 게임값(잔여 임무피해)↓ : 보안-비용 트레이드오프 곡선
  (4) 균형에서 확률이 높은 '하중지지' 불변식 식별 → 우선순위
을 입증한다.

실행: PYTHONPATH=src python3 src/security_game.py
"""
import os
import sys
import json
import copy
import itertools
import numpy as np
# matplotlib·scipy는 그림/LP에서만 필요하므로 지연 임포트한다(엔진부는 numpy만 의존 →
# mlx-lm 등 numpy만 있는 런타임에서도 본 모듈의 교전엔진을 재사용할 수 있게 함, 6.10.4).

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
OFF = 99999.0
STEPS, DT, SEED = 32, 1.0, 42
ATTACK_START = 6.0          # 본 공격 행동이 시작되는 시점(정찰·MITM 이후)

# 임무영향 정규화: 표적오차가 임무실패 임계 D_CRIT(m)를 넘으면 '임무 실패'로 포화(1.0).
# 110 m·40 m 오차는 절대값은 다르나 임무 관점에선 똑같이 '실패'이므로 동급으로 본다.
# 이 포화가 없으면 큰 피해 전술만 덮는 순수전략으로 게임이 퇴화한다. 임계는 보수적 10 m.
D_CRIT = 10.0

# 복합 교전점수 가중치(본선 채점 하버스). 임무영향(0~1)이 지배항, 미탐지·오탐은 보조항.
ALPHA_UNDETECTED = 0.5      # 탐지조차 못한 공격은 같은 피해라도 1.5배로 가중(운용자가 모름)
BETA_FP = 0.3              # 정상 비행 오탐 1건당 영향-환산 비용(과민 방어의 자기비용)


def impact(damage_m):
    """원시 표적오차(m) → 임무영향(0=정상, 1=임무 실패)로 포화 정규화."""
    return min(1.0, damage_m / D_CRIT)


# ============================ 공격 전술 포트폴리오 ============================
def _base():
    return dict(uav=UAV, recon_t=2.0, mitm_t=3.0,
                inject_t=OFF, spoof_t=OFF, spoof_end=OFF, spoof_drift=[0.0, 0.0, 0.0],
                spoof_cap=None, lateral_t=OFF, evade_t=OFF,
                fake_uav_target=[60.0, 40.0, 20.0], fake_ugv_target=[-30.0, 60.0, 0.0],
                telemetry_fake=UAV_TARGET)


def _tactics():
    t = {}
    s = _base(); s["inject_t"] = ATTACK_START
    t["inject"] = s                                          # 미서명 명령 주입 → D2가 막음
    s = _base(); s["spoof_t"] = ATTACK_START; s["spoof_drift"] = [1.2, 0, 0]; s["spoof_cap"] = None
    t["spoof_aggro"] = s                                     # 공격적 GPS 스푸핑 → D1이 막음
    s = _base(); s["spoof_t"] = ATTACK_START; s["spoof_drift"] = [1.0, 0, 0]; s["spoof_cap"] = 2.5
    t["spoof_stealth"] = s                                   # 임계 직하 스텔스 → CUSUM 또는 투표(NAV)
    s = _base(); s["lateral_t"] = ATTACK_START
    t["tamper"] = s                                          # 표적좌표 변조 → D3 또는 D6
    s = _base(); s["lateral_t"] = ATTACK_START; s["forge_t"] = ATTACK_START
    t["forge_gw"] = s                                        # 장악 게이트웨이 자기보고 위조 → D6만
    s = _base(); s["inject_t"] = ATTACK_START
    s["spoof_t"] = ATTACK_START; s["spoof_drift"] = [1.0, 0, 0]; s["spoof_cap"] = 2.5
    s["lateral_t"] = ATTACK_START; s["forge_t"] = ATTACK_START
    t["multi"] = s                                           # 협동 다중벡터(주입+스텔스+위조변조)
    return t


TACTICS = _tactics()
TACTIC_ORDER = ["inject", "spoof_aggro", "spoof_stealth", "tamper", "forge_gw", "multi"]
TACTIC_LABEL = {"inject": "Inject", "spoof_aggro": "Spoof(aggr)", "spoof_stealth": "Spoof(stealth)",
                "tamper": "Tamper", "forge_gw": "ForgeGW", "multi": "Multi-vector"}


# ====================== 방어 메커니즘과 비용(예산 모델) =======================
# 비용은 인루프 지연·연산부담·오탐위험의 추상화. 경량 통계검사=1, 암호 종단증명/다중
# 항법원 상시가동=2. 합 9. 예산 B<9면 전부는 못 켜므로 '무엇을 커버할지' 배분이 강제된다.
MECH_COST = {"D1": 1, "CUSUM": 1, "D2": 1, "D3": 1, "D5": 1, "D6": 2, "NAV": 2}
MECH_ORDER = ["D1", "CUSUM", "D2", "D3", "D5", "D6", "NAV"]
MECH_LABEL = {"D1": "D1 innov", "CUSUM": "D1+CUSUM", "D2": "D2 sign",
              "D3": "D3 hop", "D5": "D5 tele", "D6": "D6 prov", "NAV": "Robust-nav"}


def posture_kwargs(mechs):
    """방어 메커니즘 부분집합 → BlueDefender 생성 인자."""
    return dict(innov_threshold=3.0,
                enable_d1=("D1" in mechs), enable_d2=("D2" in mechs),
                enable_d3=("D3" in mechs), enable_d5=("D5" in mechs),
                enable_d7=("D7" in mechs),
                use_cusum=("CUSUM" in mechs), use_provenance=("D6" in mechs),
                use_robust_nav=("NAV" in mechs))


def cost(mechs, costs=None):
    costs = costs or MECH_COST
    return sum(costs[m] for m in mechs)


def feasible_postures(budget, mechs=None, costs=None):
    """예산 이하이며 CUSUM⊆D1 제약을 만족하는 모든 방어 태세(부분집합).
    mechs/costs를 주면 확장 메커니즘 집합으로 게임을 일반화한다(포트폴리오 확장, 6.10.6)."""
    mechs = mechs or MECH_ORDER
    costs = costs or MECH_COST
    out = []
    for r in range(len(mechs) + 1):
        for combo in itertools.combinations(mechs, r):
            s = frozenset(combo)
            if "CUSUM" in s and "D1" not in s:      # CUSUM은 D1 위에서만 동작
                continue
            if cost(s, costs) <= budget:
                out.append(s)
    return out


# ============================ 교전 1회 실행 ============================
def _world():
    w = World()
    w.add(Vehicle(UAV, "uav", [0.0, 0.0, 20.0]))
    w.add(Vehicle(UGV, "ugv", UGV_START))
    w.get(UAV).set_target(UAV_TARGET)
    return w


def engage(sched, def_kwargs, attack_on=True):
    np.random.seed(SEED)
    w = _world()
    s = copy.deepcopy(sched)
    if not attack_on:                                # 정상 비행(오탐 측정용)
        for k in ("recon_t", "mitm_t", "inject_t", "spoof_t", "lateral_t", "evade_t"):
            s[k] = OFF
        s.pop("forge_t", None)
    red = RedTeamAgent(w, RedAttacker(w), s)
    blue = BlueTeamAgent(w, BlueDefender(w, **def_kwargs), enabled=True)
    orch = Orchestrator(w, red, blue)
    orch.run(STEPS, DT, np.array(UAV_TARGET, float), UGV)
    m = orch.metrics[-1]
    damage = float(m["uav_pos_err"] + m["ugv_target_err"])
    alarms = blue.d.alarms
    first_t = min((a[0] for a in alarms), default=None)
    delay = (STEPS * DT - ATTACK_START) if first_t is None else max(0.0, first_t - ATTACK_START)
    return {"damage": round(damage, 2), "n_alarms": len(alarms),
            "undetected": len(alarms) == 0, "delay": round(float(delay), 1)}


def combat_score(sched, def_kwargs, fp):
    """복합 교전점수 = 임무영향 + α·(미탐지면 영향 가중) + β·오탐비용. 공격이 최대화."""
    r = engage(sched, def_kwargs, attack_on=True)
    imp = impact(r["damage"])
    s = imp + (ALPHA_UNDETECTED * imp if r["undetected"] else 0.0) + BETA_FP * fp
    return s, r


# ============================ 영점합 게임 풀이(minimax) ============================
def solve_zero_sum(M):
    """행=공격(최대화), 열=방어(최소화). minimax 혼합전략 균형을 LP로. → (V, x공격, y방어)."""
    from scipy.optimize import linprog
    m, n = M.shape
    # 방어자: min v  s.t.  M y ≤ v·1, Σy=1, y≥0
    c = np.concatenate([np.zeros(n), [1.0]])
    A_ub = np.hstack([M, -np.ones((m, 1))]); b_ub = np.zeros(m)
    A_eq = np.concatenate([np.ones(n), [0.0]]).reshape(1, -1); b_eq = [1.0]
    bnd = [(0, None)] * n + [(None, None)]
    rd = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bnd, method="highs")
    y = rd.x[:n]; V = rd.x[n]
    # 공격자: max u  s.t.  Mᵀx ≥ u·1, Σx=1, x≥0  →  min -u
    c2 = np.concatenate([np.zeros(m), [-1.0]])
    A_ub2 = np.hstack([-M.T, np.ones((n, 1))]); b_ub2 = np.zeros(n)
    A_eq2 = np.concatenate([np.ones(m), [0.0]]).reshape(1, -1)
    bnd2 = [(0, None)] * m + [(None, None)]
    ra = linprog(c2, A_ub=A_ub2, b_ub=b_ub2, A_eq=A_eq2, b_eq=[1.0], bounds=bnd2, method="highs")
    x = ra.x[:m]; U = ra.x[m]   # u 변수 자체가 공격자 보장값
    assert abs(V - U) < 1e-4, f"minimax 값 불일치 V={V} U={U}"
    return float(V), np.clip(x, 0, None), np.clip(y, 0, None)


# ============================ 게임 구성 ============================
def fp_of(mechs):
    return engage(TACTICS["inject"], posture_kwargs(mechs), attack_on=False)["n_alarms"]


def payoff_matrix(postures, tactics=None, tmap=None):
    """전술 × 방어 태세 → 복합 교전점수 행렬과 원시 피해 행렬. tactics/tmap로 일반화 가능."""
    tactics = tactics or TACTIC_ORDER
    tmap = tmap or TACTICS
    fps = [fp_of(p) for p in postures]
    M = np.zeros((len(tactics), len(postures)))
    Dmg = np.zeros_like(M)
    for i, tname in enumerate(tactics):
        for j, p in enumerate(postures):
            s, r = combat_score(tmap[tname], posture_kwargs(p), fps[j])
            M[i, j] = s; Dmg[i, j] = r["damage"]
    return M, Dmg, fps


def mech_marginals(postures, y, mechs=None):
    """방어 균형 혼합전략 y를 메커니즘별 가동확률로 집계 → 하중지지 불변식."""
    mechs = mechs or MECH_ORDER
    return {mch: float(sum(y[j] for j, p in enumerate(postures) if mch in p))
            for mch in mechs}


# ============================ 실험 실행 ============================
def run_budget_sweep(budgets):
    rows = []
    for B in budgets:
        P = feasible_postures(B)
        M, _, _ = payoff_matrix(P)
        V, x, y = solve_zero_sum(M)
        rows.append({"budget": B, "value": round(V, 2), "n_postures": len(P)})
    return rows


def coverage_panel():
    """단일 메커니즘만 가동한 태세에서의 원시 피해(전술×메커니즘) — 커버리지 빈틈 시각화."""
    cols = [("None", frozenset()), ("D1", frozenset({"D1"})),
            ("D1+CUSUM", frozenset({"D1", "CUSUM"})), ("D2", frozenset({"D2"})),
            ("D3", frozenset({"D3"})), ("D5", frozenset({"D5"})),
            ("D6", frozenset({"D6"})), ("Robust-nav", frozenset({"NAV"})),
            ("All (B=9)", frozenset(MECH_ORDER))]
    Dmg = np.zeros((len(TACTIC_ORDER), len(cols)))
    for i, tname in enumerate(TACTIC_ORDER):
        for j, (_, mechs) in enumerate(cols):
            Dmg[i, j] = engage(TACTICS[tname], posture_kwargs(mechs))["damage"]
    return [c[0] for c in cols], Dmg


# ============================ 그림 ============================
def fig_game(col_labels, Dmg, sweep):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.0, 4.8))
    im = ax1.imshow(Dmg, cmap="Greys", aspect="auto", vmin=0, vmax=Dmg.max())
    ax1.set_xticks(range(len(col_labels))); ax1.set_xticklabels(col_labels, rotation=40, ha="right", fontsize=8)
    ax1.set_yticks(range(len(TACTIC_ORDER)))
    ax1.set_yticklabels([TACTIC_LABEL[t] for t in TACTIC_ORDER], fontsize=8)
    for i in range(Dmg.shape[0]):
        for j in range(Dmg.shape[1]):
            v = Dmg[i, j]
            ax1.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=7,
                     color="white" if v > Dmg.max() * 0.55 else "black")
    ax1.set_title("Fig.8a  Mission damage (m): no single mechanism covers all tactics", fontsize=9.5)
    ax1.set_xlabel("defense mechanism (single)"); ax1.set_ylabel("attacker tactic")
    fig.colorbar(im, ax=ax1, fraction=0.046, pad=0.04, label="damage (m)")

    B = [r["budget"] for r in sweep]; V = [r["value"] for r in sweep]
    ax2.plot(B, V, "o-", color="black", lw=2)
    for r in sweep:
        ax2.annotate(f"{r['value']:.1f}", (r["budget"], r["value"]),
                     textcoords="offset points", xytext=(0, 8), fontsize=8, ha="center")
    ax2.set_xlabel("defense budget B (Σ mechanism cost)")
    ax2.set_ylabel("game value V (equilibrium mission-impact, 0=safe .. 1=fail)")
    ax2.set_title("Fig.8b  Security-cost frontier: budget vs residual mission-impact", fontsize=9.5)
    ax2.grid(alpha=0.3)
    plt.tight_layout(); plt.savefig(os.path.join(RESULTS, "fig8_security_game.png"), dpi=130); plt.close()


def fig_equilibrium(B_star, x, y, postures):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    marg = mech_marginals(postures, y)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.0, 4.6))
    xi = [TACTIC_LABEL[t] for t in TACTIC_ORDER]
    ax1.bar(xi, x, color="crimson", width=0.6)
    for i, v in enumerate(x):
        if v > 0.01:
            ax1.text(i, v + 0.01, f"{v:.2f}", ha="center", fontsize=8)
    ax1.set_ylabel("equilibrium probability"); ax1.set_ylim(0, max(x.max(), 0.1) * 1.25)
    ax1.set_title(f"Fig.9a  Attacker equilibrium mix (B={B_star})", fontsize=9.5)
    ax1.tick_params(axis="x", rotation=35, labelsize=8)

    mlabs = [MECH_LABEL[m] for m in MECH_ORDER]; mv = [marg[m] for m in MECH_ORDER]
    ax2.bar(mlabs, mv, color="seagreen", width=0.6)
    for i, v in enumerate(mv):
        if v > 0.01:
            ax2.text(i, v + 0.01, f"{v:.2f}", ha="center", fontsize=8)
    ax2.set_ylabel("equilibrium activation probability"); ax2.set_ylim(0, 1.05)
    ax2.set_title(f"Fig.9b  Defender equilibrium: load-bearing invariants (B={B_star})", fontsize=9.5)
    ax2.tick_params(axis="x", rotation=35, labelsize=8)
    plt.tight_layout(); plt.savefig(os.path.join(RESULTS, "fig9_equilibrium.png"), dpi=130); plt.close()


# ============================ main ============================
def main():
    budgets = [2, 3, 4, 5, 6, 7, 8, 9]
    sweep = run_budget_sweep(budgets)
    col_labels, Dmg = coverage_panel()
    fig_game(col_labels, Dmg, sweep)

    B_star = 3   # 예산이 전수 커버(B=5)에 못 미쳐 '어느 빈틈을 비울지' 무작위화가 강제되는 구간
    P = feasible_postures(B_star)
    M, Dmg_star, fps = payoff_matrix(P)
    V, x, y = solve_zero_sum(M)
    fig_equilibrium(B_star, x, y, P)
    marg = mech_marginals(P, y)

    # 단일 태세 최악대응: 어떤 고정 방어 태세도 공격 최적대응에 최소 이만큼 뚫린다.
    # 혼합전략 V가 이보다 작으면, 방어를 무작위화하는 것이 '어떤' 고정 배치보다도 우월함을 뜻한다.
    worsts = [float(M[:, j].max()) for j in range(len(P))]
    best_pure_worst = min(worsts)                       # 가장 잘 버티는 고정 태세조차 이만큼 뚫림
    n_at_min = sum(1 for w in worsts if w <= best_pure_worst + 1e-9)

    print("=" * 84)
    print("JANUS 전술공간 보안게임 — 균형 기반 자원배분 방어 (6.10)")
    print("=" * 84)
    print("\n[커버리지] 단일 메커니즘 태세별 임무피해(m) — 빈틈 존재(Fig.8a):")
    hdr = "  " + "전술".ljust(14) + "".join(f"{c:>11}" for c in col_labels)
    print(hdr); print("  " + "-" * (len(hdr) - 2))
    for i, t in enumerate(TACTIC_ORDER):
        print("  " + TACTIC_LABEL[t].ljust(14) + "".join(f"{Dmg[i, j]:>11.1f}" for j in range(len(col_labels))))

    print("\n[보안-비용 곡선] 예산 B vs 균형 게임값 V (Fig.8b):")
    print("  " + " ".join(f"B={r['budget']}:{r['value']:.1f}" for r in sweep))

    print(f"\n[균형 @ B={B_star}]  혼합전략 게임값 V = {V:.2f}  (가용 태세 {len(P)}개, 영향 0~1)")
    print(f"  어떤 고정 태세든 최악대응 ≥ {best_pure_worst:.2f} ({len(P)}개 중 {n_at_min}개가 이 최소값)")
    print(f"  → 무작위 방어가 '최선의 고정 배치'보다 임무영향을 {best_pure_worst:.2f}→{V:.2f}로 낮춤"
          f" ({(1 - V / best_pure_worst) * 100:.0f}% 감소)")
    print("  공격 균형 혼합전략:")
    for t, p in zip(TACTIC_ORDER, x):
        if p > 0.01:
            print(f"     {TACTIC_LABEL[t]:16} {p:5.2f}")
    print("  방어 균형 — 불변식별 가동확률(하중지지 순):")
    for mch, p in sorted(marg.items(), key=lambda kv: -kv[1]):
        if p > 0.01:
            print(f"     {MECH_LABEL[mch]:16} {p:5.2f}  (cost {MECH_COST[mch]})")

    out = {
        "weights": {"alpha_undetected": ALPHA_UNDETECTED, "beta_fp": BETA_FP},
        "mech_cost": MECH_COST,
        "coverage_damage": {TACTIC_ORDER[i]: {col_labels[j]: round(float(Dmg[i, j]), 2)
                            for j in range(len(col_labels))} for i in range(len(TACTIC_ORDER))},
        "budget_sweep": sweep,
        "equilibrium_B": B_star, "game_value": round(V, 2),
        "any_fixed_posture_worstcase": round(best_pure_worst, 2), "n_postures_at_min": n_at_min,
        "attacker_mix": {TACTIC_ORDER[i]: round(float(x[i]), 3) for i in range(len(TACTIC_ORDER))},
        "defender_mech_marginals": {m: round(v, 3) for m, v in marg.items()},
    }
    with open(os.path.join(RESULTS, "security_game_log.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {RESULTS}/fig8_security_game.png, fig9_equilibrium.png, security_game_log.json")


if __name__ == "__main__":
    main()
