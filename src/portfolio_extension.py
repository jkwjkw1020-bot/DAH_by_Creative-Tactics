#!/usr/bin/env python3
"""JANUS 공격 포트폴리오 확장과 균형의 재조정 — 6.10.6.

6.10의 보안게임은 공격 포트폴리오가 고정일 때의 균형이었다. 실제 적은 전술을 늘린다.
본 모듈은 공격에 두 신규 전술을 더했을 때 방어 균형이 어떻게 스스로 재조정되는지를 보인다.
  - 리플레이(replay): 과거에 캡처한 '유효 서명' 명령을 stale 타임스탬프로 재전송. 서명검증(D2)은
    통과하므로 신선도 검사(D7)만이 막는다.
  - 탈동기(desync): 협동 채널의 시간동기를 깨 UGV가 옛 UAV 상태를 추종. 내용은 한때 참이므로
    홉 무결성(D3)은 통과하고, 종단간 출처증명(D6) 또는 신선도(D7)만이 막는다.
이 둘을 막는 신규 불변식 D7(anti-replay/freshness)을 예산 항목으로 추가하고, 확장된 게임의
minimax 균형을 base와 비교한다. 핵심 결과: 공격이 새 전술을 얻으면 D7이 새로운 '하중지지'
불변식이 되어 균형이 자동으로 재조정된다 = 6.10 프레임워크가 정적이지 않고 적응적임.

실행: PYTHONPATH=src python3 src/portfolio_extension.py
"""
import os
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import security_game as sg

RESULTS = sg.RESULTS
ATTACK_START = sg.ATTACK_START

# --- 확장 포트폴리오: 기존 6전술 + 리플레이 + 탈동기 ---
_rep = sg._base(); _rep["replay_t"] = ATTACK_START; _rep["replay_target"] = [0.0, 0.0, 20.0]; _rep["replay_stale"] = 10.0
_des = sg._base(); _des["desync_t"] = ATTACK_START
EXT_TMAP = dict(sg.TACTICS); EXT_TMAP["replay"] = _rep; EXT_TMAP["desync"] = _des
EXT_TACTICS = sg.TACTIC_ORDER + ["replay", "desync"]
EXT_LABEL = dict(sg.TACTIC_LABEL); EXT_LABEL.update({"replay": "Replay", "desync": "Desync"})

# --- 확장 메커니즘: 기존 7 + D7(신선도, cost 1) ---
EXT_MECHS = sg.MECH_ORDER + ["D7"]
EXT_COSTS = dict(sg.MECH_COST); EXT_COSTS["D7"] = 1
EXT_MECH_LABEL = dict(sg.MECH_LABEL); EXT_MECH_LABEL["D7"] = "D7 fresh"


def base_eq(B):
    P = sg.feasible_postures(B)
    M, _, _ = sg.payoff_matrix(P)
    V, x, y = sg.solve_zero_sum(M)
    return {"V": round(V, 3), "marg": sg.mech_marginals(P, y),
            "mix": {sg.TACTIC_ORDER[i]: round(float(x[i]), 3) for i in range(len(x))}}


def ext_eq(B):
    P = sg.feasible_postures(B, EXT_MECHS, EXT_COSTS)
    M, _, _ = sg.payoff_matrix(P, EXT_TACTICS, EXT_TMAP)
    V, x, y = sg.solve_zero_sum(M)
    return {"V": round(V, 3), "marg": sg.mech_marginals(P, y, EXT_MECHS),
            "mix": {EXT_TACTICS[i]: round(float(x[i]), 3) for i in range(len(x))},
            "n_postures": len(P)}


def coverage_new():
    """신규 전술이 단일 메커니즘에서 입는 피해(m) — D7의 고유 역할 확인."""
    cols = [("None", set()), ("D2", {"D2"}), ("D3", {"D3"}), ("D6", {"D6"}),
            ("D7", {"D7"}), ("NAV", {"NAV"}), ("All", set(EXT_MECHS))]
    out = {}
    for nm in ("replay", "desync"):
        out[nm] = {c: round(sg.engage(EXT_TMAP[nm], sg.posture_kwargs(frozenset(s)))["damage"], 1)
                   for c, s in cols}
    return [c for c, _ in cols], out


def fig_rebalance(B, base, ext):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.0, 4.7))
    # (a) 방어 메커니즘별 균형 가동확률: base(D7 없음) vs ext
    mechs = EXT_MECHS
    bvals = [base["marg"].get(m, 0.0) for m in mechs]
    evals = [ext["marg"].get(m, 0.0) for m in mechs]
    xi = np.arange(len(mechs)); wd = 0.38
    ax1.bar(xi - wd / 2, bvals, wd, label="Base portfolio (6 tactics)", color="0.7", edgecolor="black", linewidth=0.4)
    ax1.bar(xi + wd / 2, evals, wd, label="Extended (+ replay, desync)", color="0.3", edgecolor="black", linewidth=0.4)
    ax1.set_xticks(xi); ax1.set_xticklabels([EXT_MECH_LABEL[m] for m in mechs], rotation=35, fontsize=8)
    ax1.set_ylabel("equilibrium activation probability"); ax1.set_ylim(0, 1.05)
    ax1.set_title(f"Fig.11a  Defender equilibrium rebalances when attacker innovates (B={B})", fontsize=9.5)
    ax1.legend(fontsize=8)
    # D7 강조
    d7i = mechs.index("D7")
    ax1.annotate("D7 emerges\nas load-bearing", (d7i + wd / 2, evals[d7i]),
                 textcoords="offset points", xytext=(0, 12), fontsize=7.5, ha="center",
                 arrowprops=dict(arrowstyle="->", lw=0.8))

    # (b) 공격 균형 혼합: ext (신규 전술 비중)
    tk = [t for t in EXT_TACTICS if ext["mix"].get(t, 0) > 0.005]
    tv = [ext["mix"][t] for t in tk]
    colors = ["0.3" if t not in ("replay", "desync") else "crimson" for t in tk]
    ax2.bar([EXT_LABEL[t] for t in tk], tv, color=colors, edgecolor="black", linewidth=0.4, width=0.6)
    for i, v in enumerate(tv):
        ax2.text(i, v + 0.01, f"{v:.2f}", ha="center", fontsize=8)
    ax2.set_ylabel("equilibrium probability"); ax2.set_ylim(0, max(tv) * 1.25 if tv else 1)
    ax2.set_title(f"Fig.11b  Attacker equilibrium mix now exploits new tactics (B={B})", fontsize=9.5)
    ax2.tick_params(axis="x", rotation=35, labelsize=8)
    plt.tight_layout(); plt.savefig(os.path.join(RESULTS, "fig11_portfolio.png"), dpi=130); plt.close()


def main():
    print("=" * 84)
    print("JANUS 공격 포트폴리오 확장과 균형의 재조정 (6.10.6)")
    print("=" * 84)

    cols, cov = coverage_new()
    print("\n[신규 전술 커버리지] 단일 메커니즘별 임무피해(m):")
    print("  " + "전술".ljust(10) + "".join(f"{c:>7}" for c in cols))
    for nm in ("replay", "desync"):
        print("  " + EXT_LABEL[nm].ljust(10) + "".join(f"{cov[nm][c]:>7.1f}" for c in cols))
    print("  → 리플레이는 오직 D7이, 탈동기는 D6 또는 D7이 막는다(서명·홉무결성으론 불가).")

    print("\n[예산별 base vs 확장 균형] (게임값 V / D7 가동확률):")
    print(f"  {'B':>2} | {'base V':>7} | {'ext V':>7} | {'ext D7 가동확률':>14}")
    print("  " + "-" * 44)
    sweep = []
    for B in [3, 4, 5, 6]:
        b, e = base_eq(B), ext_eq(B)
        sweep.append({"B": B, "base_V": b["V"], "ext_V": e["V"], "ext_d7": round(e["marg"]["D7"], 3)})
        print(f"  {B:>2} | {b['V']:>7.2f} | {e['V']:>7.2f} | {e['marg']['D7']:>14.2f}")

    B_star = 4
    base, ext = base_eq(B_star), ext_eq(B_star)
    fig_rebalance(B_star, base, ext)

    print(f"\n[균형 재조정 @ B={B_star}]")
    print(f"  공격 균형 혼합(확장): " +
          ", ".join(f"{EXT_LABEL[t]} {p:.2f}" for t, p in ext["mix"].items() if p > 0.01))
    print(f"  방어 D7 가동확률: base {base['marg'].get('D7',0.0):.2f} → 확장 {ext['marg']['D7']:.2f}  "
          f"(새 하중지지 불변식으로 부상)")
    print("  방어 균형(확장) 하중지지 순:")
    for m, p in sorted(ext["marg"].items(), key=lambda kv: -kv[1]):
        if p > 0.01:
            print(f"     {EXT_MECH_LABEL[m]:12} {p:.2f}")

    out = {"coverage_new": cov, "budget_sweep": sweep, "featured_B": B_star,
           "base": base, "ext": ext}
    with open(os.path.join(RESULTS, "portfolio_extension_log.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {RESULTS}/fig11_portfolio.png, portfolio_extension_log.json")


if __name__ == "__main__":
    main()
