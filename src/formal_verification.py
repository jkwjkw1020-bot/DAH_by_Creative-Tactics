#!/usr/bin/env python3
"""JANUS 형식 검증 — 방어 불변식의 '충분성'을 기계검증으로 증명한다 (6.11).

6.7~6.9는 시뮬레이션으로, 6.10은 게임이론 균형으로 방어를 입증하였다. 본 모듈은 마지막
차원, 곧 형식 증명을 더한다. 공격자의 능력을 SMT(z3) 자유변수로, 각 방어 불변식을 제약으로
인코딩하고, 다음을 기계검증한다.

  정리 1 (인증성). 공격 클래스 {미서명 주입, 표적 변조, 게이트웨이 자기보고 위조, 리플레이}에
    대해 "임무 훼손 ∧ 모든 가동 탐지기 회피"가 충족 가능(SAT)한지 판정한다.
    - 약한 방어(홉바이홉 D2+D3)에서는 SAT → z3가 공격을 자동 합성(반례 = MIRROR-CRACK forge).
    - 최소 안전 집합은 {D2, D6, D7}이며 이때 모든 공격 클래스가 UNSAT = 증명적으로 안전.
    - D6(종단간 출처증명)는 D3(홉바이홉)를 포섭한다: forge는 D6만, replay는 D7만 막는다.

  정리 2 (생존성). 어떤 임계 기반 탐지기(D1)도 임계 직하 스텔스 편향을 막지 못한다(SAT,
    사각지대의 존재를 증명). 다중 항법원 중앙값 투표(NAV, 3원 중 ≤1 오염 가정)는 탐지 없이도
    오차를 잡음 수준으로 묶어 UNSAT = 증명적으로 안전.

핵심 함의: 형식적으로 '필수'인 불변식({D2, D6, D7} + NAV)이 6.10 게임 균형의 하중지지
불변식, 그리고 6.7~6.9 시뮬 결과와 일치한다 → 시뮬·게임·증명 세 독립 방법의 수렴.

암호 가정: 공격자는 UAV 키를 갖지 못한다(HMAC 위조 불가). 이를 "UAV가 서명한 토큰은
내용이 참 표적과 같을 때만 검증을 통과한다"는 제약으로 인코딩한다.

실행: python3 src/formal_verification.py   (의존: z3-solver)
"""
import os
import json
from z3 import Solver, Int, Real, Bool, And, Or, Implies, Not, sat, unsat

RESULTS = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "docs", "results"))
os.makedirs(RESULTS, exist_ok=True)

TAU_MISS = 5      # 표적 오지정이 이보다 크면 임무 훼손(m)
TAU_DET = 3       # 이노베이션 탐지 임계(m) — 6.7과 동일
EPS = 1           # 임무 허용 오차(m): 이하이면 임무 정상
FRESH = 3         # 신선도 창(초) — defense.py freshness_window와 동일

ATTACKS = ["inject", "tamper", "forge", "replay"]
ATTACK_LABEL = {"inject": "Inject\n(unsigned cmd)", "tamper": "Tamper\n(relay altered)",
                "forge": "ForgeGW\n(self-report forged)", "replay": "Replay\n(valid+stale)"}


# ============================ 정리 1: 인증성 ============================
def authenticity_query(defenses, attack):
    """(가동 방어 집합, 공격 클래스) → (sat|unsat, 반례 모델). SAT=공격 성립(취약)."""
    s = Solver()
    T = Int("true_target")          # UAV가 산출한 참 표적
    R = Int("relayed_target")       # UGV로 중계된 표적 (장악 시 공격자 제어)
    S = Int("gw_self_report")       # 게이트웨이 자기보고 원표적 (위조 시 공격자 제어)
    U = Int("token_target")         # UAV 서명 출처증명 토큰의 표적값
    tok_present = Bool("token_present")
    Ccmd = Int("cmd_target")        # 주입/리플레이 명령이 설정하려는 표적
    cmd_present = Bool("cmd_present")
    cmd_sig = Bool("cmd_sig_valid")  # 명령 서명 유효 여부(진짜 캡처분만 True 가능)
    age = Int("cmd_age")
    s.add(age >= 0)

    # 암호 위조불가: 토큰은 내용이 참 표적과 같을 때만 UAV 서명 검증을 통과.
    tok_sig_ok = And(tok_present, U == T)
    # 신선하고 유효한 명령은 합법 명령(=참 표적)뿐 — 공격자가 새 유효서명을 위조할 수 없음.
    s.add(Implies(And(cmd_present, cmd_sig, age <= FRESH), Ccmd == T))

    # 탐지기 '무경보(=회피)' 조건
    D3_silent = (R == S)                          # 홉바이홉: 중계=자기보고면 조용
    D6_silent = And(tok_sig_ok, R == U)           # 종단간: 유효토큰 ∧ 중계=토큰표적
    D2_silent = Implies(cmd_present, cmd_sig)      # 서명검증: 명령 있으면 서명 유효해야
    D7_silent = Implies(cmd_present, age <= FRESH)  # 신선도: 명령 있으면 신선해야

    far = lambda a, b: Or(a - b > TAU_MISS, b - a > TAU_MISS)
    if attack == "inject":          # 미서명 명령으로 표적 오설정
        s.add(cmd_present, Not(cmd_sig), far(Ccmd, T), R == T, S == T, tok_present, U == T)
    elif attack == "tamper":        # 중계만 변조(자기보고는 정직)
        s.add(far(R, T), S == T, Not(cmd_present), tok_present, U == T)
    elif attack == "forge":         # 중계 변조 + 자기보고까지 일치 위조
        s.add(far(R, T), S == R, Not(cmd_present), tok_present, U == T)
    elif attack == "replay":        # 유효서명 명령을 stale 타임스탬프로 재전송
        s.add(cmd_present, cmd_sig, age > FRESH, far(Ccmd, T), R == T, S == T, tok_present, U == T)

    for name, cond in (("D2", D2_silent), ("D3", D3_silent), ("D6", D6_silent), ("D7", D7_silent)):
        if name in defenses:
            s.add(cond)             # 가동 탐지기는 모두 회피되어야(무경보)

    r = s.check()
    if r == sat:
        m = s.model()
        ce = {str(d): m[d].as_long() if m[d] is not None and hasattr(m[d], "as_long") else str(m[d])
              for d in m.decls()}
        return "SAT", ce
    return "UNSAT", None


def authenticity_safe(defenses):
    """모든 인증성 공격이 UNSAT이면 증명적으로 안전."""
    return all(authenticity_query(defenses, a)[0] == "UNSAT" for a in ATTACKS)


def minimal_safe_sets(universe=("D2", "D3", "D6", "D7")):
    """전 공격을 막는 방어 부분집합 중 극소(minimal) 집합들을 찾는다."""
    from itertools import combinations
    safe = []
    for r in range(len(universe) + 1):
        for c in combinations(universe, r):
            if authenticity_safe(set(c)):
                safe.append(set(c))
    minimal = [s for s in safe if not any(o < s for o in safe)]   # 진부분집합이 안전이면 제외
    return minimal, safe


# ============================ 정리 2: 생존성 ============================
def survivability_query(defenses):
    """임계탐지(D1) vs 다중항법원 투표(NAV) — 스텔스 편향에 대한 생존성."""
    s = Solver()
    b = Real("gps_bias")            # 공격자 GPS 편향(m)
    err = Real("nav_error")         # 항법/제어에 쓰이는 위치오차(m)
    s.add(b >= 0)
    if "NAV" in defenses:
        s.add(err <= EPS)           # 투표 보장: 3원 중 ≤1 오염 → 단일 편향원 기각
    else:
        s.add(err == b)             # 탐지전용: 스푸핑된 GPS가 그대로 항법에 사용
    if "D1" in defenses:
        s.add(b <= TAU_DET)         # 임계 탐지기 무경보(회피) = 편향이 임계 이하
    s.add(err > EPS)                # 임무 훼손(오차가 허용치 초과)
    r = s.check()
    if r == sat:
        m = s.model()
        return "SAT", {str(d): str(m[d]) for d in m.decls()}
    return "UNSAT", None


# ============================ 그림 ============================
def fig_proof_grid(grid, configs):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    cols = ATTACKS + ["stealth_spoof"]
    col_labels = [ATTACK_LABEL[a] for a in ATTACKS] + ["StealthSpoof\n(below thresh.)"]
    M = np.zeros((len(configs), len(cols)))
    for i, cfg in enumerate(configs):
        for j, atk in enumerate(cols):
            M[i, j] = 0 if grid[cfg["key"]][atk] == "UNSAT" else 1   # 0=safe,1=vuln
    fig, ax = plt.subplots(figsize=(9.6, 4.6))
    # 무채색 배경 + 취약=빨강(공격), 안전=짙은회색
    cmap = plt.matplotlib.colors.ListedColormap(["0.85", "#b00000"])
    ax.imshow(M, cmap=cmap, aspect="auto", vmin=0, vmax=1)
    ax.set_xticks(range(len(cols))); ax.set_xticklabels(col_labels, fontsize=8)
    ax.set_yticks(range(len(configs))); ax.set_yticklabels([c["label"] for c in configs], fontsize=8.5)
    for i in range(len(configs)):
        for j in range(len(cols)):
            safe = M[i, j] == 0
            ax.text(j, i, "SAFE\n(proven)" if safe else "ATTACK\n(z3 found)",
                    ha="center", va="center", fontsize=6.8,
                    color="black" if safe else "white", fontweight="bold" if not safe else "normal")
    ax.set_title("Fig.12  Machine-checked defense sufficiency (z3): proven-safe vs auto-synthesized attack",
                 fontsize=9.5)
    ax.set_xlabel("attack class"); ax.set_ylabel("defense configuration")
    plt.tight_layout(); plt.savefig(os.path.join(RESULTS, "fig12_formal.png"), dpi=130); plt.close()


# ============================ main ============================
def main():
    print("=" * 86)
    print("JANUS 형식 검증 — 방어 불변식 충분성의 기계검증 증명 (6.11, z3 SMT)")
    print("=" * 86)

    configs = [
        {"key": "none", "label": "None", "auth": set(), "spoof": set()},
        {"key": "hop", "label": "Hop-by-hop (D2+D3)", "auth": {"D2", "D3"}, "spoof": {"D1"}},
        {"key": "d6", "label": "D2+D3+D6", "auth": {"D2", "D3", "D6"}, "spoof": {"D1"}},
        {"key": "min", "label": "Minimal (D2+D6+D7 / NAV)", "auth": {"D2", "D6", "D7"}, "spoof": {"NAV"}},
        {"key": "all", "label": "All (D2+D3+D6+D7 / D1+NAV)", "auth": {"D2", "D3", "D6", "D7"}, "spoof": {"D1", "NAV"}},
    ]

    grid = {}
    print("\n[정리 1] 인증성 — (방어구성 × 공격) 충족성: SAFE=UNSAT(증명적 안전), ATTACK=SAT(z3 반례)")
    hdr = "  " + "구성".ljust(28) + "".join(f"{a:>10}" for a in ATTACKS)
    print(hdr); print("  " + "-" * (len(hdr)))
    for cfg in configs:
        row = {}
        for a in ATTACKS:
            res, _ = authenticity_query(cfg["auth"], a)
            row[a] = res
        # 생존성(스텔스 스푸핑) 칸도 채움
        row["stealth_spoof"] = survivability_query(cfg["spoof"])[0]
        grid[cfg["key"]] = row
        print("  " + cfg["label"].ljust(28) +
              "".join(f"{('SAFE' if row[a]=='UNSAT' else 'ATTACK'):>10}" for a in ATTACKS))

    # 약한 방어의 자동 합성 반례(forge under hop-by-hop)
    res, ce = authenticity_query({"D2", "D3"}, "forge")
    print(f"\n  ▸ 홉바이홉(D2+D3) vs ForgeGW: {res} → z3가 합성한 공격 반례:")
    if ce:
        print(f"      참표적 T={ce.get('true_target')}, 중계 R={ce.get('relayed_target')}, "
              f"자기보고 S={ce.get('gw_self_report')}  (R≠T인데 R==S라 홉바이홉이 속음)")
    res2, ce2 = authenticity_query({"D2", "D6"}, "replay")
    print(f"  ▸ D2+D6(신선도 없음) vs Replay: {res2} → z3 반례: "
          f"유효서명·stale 명령으로 표적 {ce2.get('cmd_target') if ce2 else '?'} 설정(참 {ce2.get('true_target') if ce2 else '?'})")

    # 최소 안전 집합
    minimal, _ = minimal_safe_sets()
    min_sets = [sorted(m) for m in minimal]
    print(f"\n  ▸ 인증성 최소 안전 집합(극소): {min_sets}")
    d6_in_all = all("D6" in m for m in minimal)
    d3_in_any = any("D3" in m for m in minimal)
    print(f"      → 모든 극소집합이 D6 포함={d6_in_all}, D3 포함={d3_in_any}  "
          f"⇒ D6가 D3를 포섭(홉바이홉은 불필요)")

    print("\n[정리 2] 생존성 — 임계탐지 vs 다중항법원 투표 (스텔스 편향):")
    for cfg_name, dset in (("탐지전용 (D1)", {"D1"}), ("투표 (NAV)", {"NAV"}), ("D1+NAV", {"D1", "NAV"})):
        r, ce = survivability_query(dset)
        note = ("사각지대 존재: " + ce.get("gps_bias", "") + " m 편향이 미탐지·임무훼손") if r == "SAT" else "탐지 없이도 안전"
        print(f"  {cfg_name:14}: {('ATTACK(SAT)' if r=='SAT' else 'SAFE(UNSAT)'):14} {note}")

    fig_proof_grid(grid, configs)

    print("\n[삼중 수렴] 형식적 필수 불변식 = 게임 하중지지 = 시뮬 결과:")
    print("  • 형식 증명: 인증성 {D2, D6, D7} + 생존성 NAV 가 최소 안전 집합")
    print("  • 게임 균형(6.10): D2·D6 하중지지, 포트폴리오 확장 시 D7 부상")
    print("  • 시뮬(6.7~6.9): D6 0 m(D3 110 m), 투표 0.44 m(탐지전용 2.53 m)")

    out = {
        "params": {"tau_miss_m": TAU_MISS, "tau_det_m": TAU_DET, "eps_m": EPS, "fresh_s": FRESH},
        "crypto_assumption": "attacker lacks UAV key (HMAC unforgeable): a token verifies only if its content == true target",
        "authenticity_grid": {cfg["key"]: {a: grid[cfg["key"]][a] for a in ATTACKS} for cfg in configs},
        "survivability": {"detection_only_D1": survivability_query({"D1"})[0],
                          "voting_NAV": survivability_query({"NAV"})[0]},
        "forge_counterexample_hopbyhop": ce,
        "minimal_safe_sets_authenticity": min_sets,
        "d6_subsumes_d3": bool(d6_in_all and not d3_in_any),
        "triangulation": {"formal_required": ["D2", "D6", "D7", "NAV"],
                          "game_loadbearing": ["D2", "D6", "D7"],
                          "sim": {"D6_m": 0.0, "D3_m": 110.0, "voting_m": 0.44, "detect_only_m": 2.53}},
    }
    with open(os.path.join(RESULTS, "formal_verification_log.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {RESULTS}/fig12_formal.png, formal_verification_log.json")


if __name__ == "__main__":
    main()
