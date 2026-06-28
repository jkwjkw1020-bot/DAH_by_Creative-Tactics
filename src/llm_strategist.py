#!/usr/bin/env python3.12
"""JANUS 실제 LLM 전략가 실증 — 규칙 정책이 LLM의 충실한 대역임을 실측한다 (6.10.4).

6.10의 보안게임과 6.4의 분류(triage)는 본래 LLM이 맡는 자리이며, PoC는 재현성을 위해
규칙으로 구현하였다. 본 모듈은 그 주장을 실측으로 뒷받침한다. 로컬 LLM(Qwen2.5-VL-7B-Instruct,
mlx-vlm, 텍스트 전용)에게 규칙·게임이론 정책과 '동일한 관찰'을 제시하고, 같은 전략적 판단에
이르는지 본다.

Demo-1 (방어 전략 선택): 커버리지 사실·비용·예산 B=3을 주고 LLM이 (a) 어떤 고정 배치도
  안전한가, (b) 어떤 불변식을 켤까, (c) 무작위화할까, (d) 어떤 두 태세를 번갈아 쓸까 를 판단.
  LLM이 고른 태세를 실제 교전 시뮬에 돌려 최악대응 임무영향을 균형값·고정최악과 비교한다.
Demo-2 (분류·대응 triage): 실제 교전에서 관측된 경보를 주고 근본원인과 대응을 LLM이 추론 →
  규칙 _triage의 대응과 일치하는지 확인한다.

그리디 디코딩(temp=0)으로 결정적. 전체 프롬프트·응답은 docs/results/llm_strategist_log.json에 기록.
실행: /opt/homebrew/bin/python3.12 src/llm_strategist.py
"""
import os
import re
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import security_game as sg   # 교전엔진·전술·태세(numpy만 의존, 6.10과 동일 시드)

RESULTS = sg.RESULTS
MODEL = "mlx-community/Qwen2.5-VL-7B-Instruct-4bit"   # 로컬 캐시. 텍스트 전용으로 사용.


# ----------------------------- LLM 래퍼 -----------------------------
_CACHE = {}


def llm(system, user, max_tokens=640):
    """캐시된 Qwen2.5-VL-7B를 이미지 없이 텍스트 전용으로 호출(greedy, temp=0 → 결정적).
    결정 1건의 벽시계 지연을 _CACHE['times']에 기록(2-시간척도 분석, 6.10.5)."""
    import time
    import warnings
    warnings.filterwarnings("ignore")
    from mlx_vlm import load, generate
    from mlx_vlm.prompt_utils import apply_chat_template
    if "m" not in _CACHE:
        _CACHE["m"], _CACHE["p"] = load(MODEL)
    model, proc = _CACHE["m"], _CACHE["p"]
    prompt = system + "\n\n" + user        # VL 템플릿은 단일 턴이 안전 → 시스템+사용자 병합
    fmt = apply_chat_template(proc, model.config, prompt, num_images=0)
    t0 = time.perf_counter()
    res = generate(model, proc, fmt, image=[], max_tokens=max_tokens, temperature=0.0, verbose=False)
    _CACHE.setdefault("times", []).append(time.perf_counter() - t0)
    return res.text if hasattr(res, "text") else str(res)


def clean_mechs(x):
    """LLM이 돌려준 임의 형식(문자열·중첩리스트·비용주석 포함)에서 유효 메커니즘만 추출·중복제거."""
    toks = []
    if isinstance(x, str):
        toks = [t.upper() for t in re.findall(r"CUSUM|NAV|D[1-6]", x, re.I)]
    elif isinstance(x, (list, tuple)):
        for e in x:
            toks += clean_mechs(e)
    out = []
    for m in toks:
        if m in sg.MECH_ORDER and m not in out:
            out.append(m)
    return out


def extract_json(text):
    """응답에서 첫 JSON 객체를 추출."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        # 흔한 흠집 보정(후행 콤마 등)
        s = re.sub(r",\s*([}\]])", r"\1", m.group(0))
        try:
            return json.loads(s)
        except Exception:
            return None


# ----------------------- 시뮬 기반 채점(LLM 선택 평가) -----------------------
def posture_worstcase(mechs):
    """방어 태세(부분집합)의 최악대응 복합점수와 그 전술."""
    p = frozenset(m for m in mechs if m in sg.MECH_ORDER)
    fp = sg.fp_of(p)
    worst, wt = 0.0, None
    for t in sg.TACTIC_ORDER:
        s, _ = sg.combat_score(sg.TACTICS[t], sg.posture_kwargs(p), fp)
        if s > worst:
            worst, wt = s, t
    return round(worst, 2), wt


def mix_worstcase(a, b):
    """두 태세를 50:50으로 번갈아 쓸 때의 최악대응(혼합전략의 LLM 제안 평가)."""
    pa, pb = frozenset(a), frozenset(b)
    fa, fb = sg.fp_of(pa), sg.fp_of(pb)
    worst, wt = 0.0, None
    for t in sg.TACTIC_ORDER:
        sa, _ = sg.combat_score(sg.TACTICS[t], sg.posture_kwargs(pa), fa)
        sb, _ = sg.combat_score(sg.TACTICS[t], sg.posture_kwargs(pb), fb)
        s = 0.5 * sa + 0.5 * sb
        if s > worst:
            worst, wt = s, t
    return round(worst, 2), wt


# ----------------------------- Demo-1: 방어 전략 선택 -----------------------------
COVERAGE_FACTS = """\
Attacker tactics (each inflicts mission failure unless countered):
  - inject        : unsigned command injection  -> countered ONLY by D2
  - spoof_aggro   : aggressive GPS spoofing      -> countered by D1 (or robust-nav NAV)
  - spoof_stealth : GPS bias just below threshold -> countered ONLY by CUSUM or NAV (D1 alone fails)
  - tamper        : target-coordinate tampering   -> countered by D3 or D6
  - forge_gw      : compromised gateway forges its own self-report -> countered ONLY by D6 (D3 is fooled)
  - multi         : coordinated inject+stealth+forge at once -> needs D2 AND (CUSUM or NAV) AND D6 together
Defense mechanisms and cost (in-loop latency/compute/false-positive budget):
  D1=1, CUSUM=1 (requires D1), D2=1, D3=1, D5=1, D6=2, NAV=2.  Full set costs 9.
Detection vs prevention: an attack that causes damage AND is never detected is the worst case
(operators stay blind), so leaving any tactic both un-prevented and un-detected is most costly."""

SYS_STRAT = ("You are JANUS-Blue, the autonomous cyber-defense strategist protecting a UAV-UGV "
             "cooperative gateway. You must allocate a limited detection/response budget across "
             "invariant checks to minimize the worst-case mission impact an adversary can inflict. "
             "Think step by step, then answer.")


def demo1():
    user = (f"{COVERAGE_FACTS}\n\n"
            "Your detection budget is B=3: the SUM of the costs of the mechanisms you enable MUST be "
            "<= 3. Re-check the sum before answering.\n\n"
            "Reason about two questions:\n"
            "(1) Against an adversary who sees your FIXED choice and then best-responds, can any single "
            "posture (cost<=3) avoid a mission failure?\n"
            "(2) Because no single posture covers every tactic, propose TWO complementary postures "
            "(each cost<=3) that you could alternate between unpredictably so the adversary cannot know "
            "which gap to hit. Would alternating lower your worst case?\n\n"
            "Answer with ONLY a JSON object of this exact form:\n"
            '{"single_fixed_posture_safe": <true|false>,'
            ' "enable": [<your single best posture, total cost <=3>],'
            ' "randomize": <true|false>,'
            ' "randomize_between": [[<postureA, cost<=3>], [<postureB, cost<=3>]],'
            ' "priority_mechanism": "<the one mechanism you would never drop>",'
            ' "reasoning": "<two sentences>"}')
    raw = llm(SYS_STRAT, user)
    js = extract_json(raw) or {}

    enable = clean_mechs(js.get("enable", []))
    cost_ok = sg.cost(frozenset(enable)) <= 3
    llm_worst, llm_wt = posture_worstcase(enable) if enable else (None, None)

    rb_raw = js.get("randomize_between") or []
    rb = [clean_mechs(s) for s in rb_raw] if isinstance(rb_raw, list) else []
    rb = [s for s in rb if s]
    mix = None
    if len(rb) >= 2:
        mw, mwt = mix_worstcase(rb[0], rb[1])
        mix = {"between": [sorted(rb[0]), sorted(rb[1])], "worstcase": mw, "worst_tactic": mwt,
               "budget_ok": [sg.cost(frozenset(rb[0])) <= 3, sg.cost(frozenset(rb[1])) <= 3]}

    # 게임이론 기준값(보안게임 로그에서)
    log = json.load(open(os.path.join(RESULTS, "security_game_log.json")))
    V = log["game_value"]                       # 0.68 (minimax 혼합)
    fixed_worst = log["any_fixed_posture_worstcase"]  # 1.5 (어떤 고정태세도 이만큼 뚫림)

    # 일치 판정
    agree_no_fixed = (js.get("single_fixed_posture_safe") is False)
    agree_randomize = (js.get("randomize") is True)
    agree_priority = (js.get("priority_mechanism") in ("D2", "D6"))  # 게임 균형의 하중지지
    return {"raw": raw, "parsed": js, "enable": enable, "cost_ok": cost_ok,
            "llm_posture_worstcase": llm_worst, "llm_posture_worst_tactic": llm_wt,
            "llm_randomization": mix, "game_value_minimax": V, "any_fixed_worstcase": fixed_worst,
            "agree": {"no_fixed_safe": agree_no_fixed, "randomize": agree_randomize,
                      "priority_is_loadbearing": agree_priority}}


# ----------------------------- Demo-2: 분류·대응 triage -----------------------------
def real_alarm(tactic, mechs):
    """실제 교전을 돌려 발생한 경보 태그를 수집(관찰의 근거)."""
    import numpy as np
    np.random.seed(sg.SEED)
    w = sg._world()
    import copy
    from janus.attack import RedAttacker
    from janus.defense import BlueDefender
    from janus.agents import RedTeamAgent, BlueTeamAgent, Orchestrator
    red = RedTeamAgent(w, RedAttacker(w), copy.deepcopy(sg.TACTICS[tactic]))
    blue = BlueTeamAgent(w, BlueDefender(w, **sg.posture_kwargs(frozenset(mechs))), enabled=True)
    Orchestrator(w, red, blue).run(sg.STEPS, sg.DT, __import__("numpy").array(sg.UAV_TARGET, float), sg.UGV)
    tags = sorted({a[1] for a in blue.d.alarms})
    return tags

# (관찰, 규칙정책의 정답 대응) — agents.py _triage 매핑과 일치
TRIAGE_CASES = [
    ("spoof_aggro", {"D1"}, "GPS spoofing",
     "switch navigation to dead-reckoning (R1)"),
    ("tamper", {"D3"}, "target-coordinate tampering (lateral spread)",
     "isolate the gateway and roll back the target (R3)"),
    ("forge_gw", {"D6"}, "compromised gateway forging its self-report",
     "isolate the gateway and roll back the target (R3)"),
]

SYS_TRIAGE = ("You are JANUS-Blue's triage agent for a UAV-UGV cooperative gateway. Given detector "
              "alarms, infer the root-cause attack and choose the single best response. "
              "Possible responses: 'block the unsigned command (D2)', 'switch navigation to "
              "dead-reckoning (R1)', 'failsafe / slow down (R2)', 'isolate the gateway and roll back "
              "the target (R3)', 'no action'.")

ALARM_DESC = {
    "D1_innovation": "UAV EKF innovation |GPS - IMU| exceeded the 3 m threshold and keeps growing",
    "D1_cusum": "cumulative-sum test on the GPS-IMU residual crossed its control limit (slow drift)",
    "D3_gateway_tamper": "the target the gateway relayed to the UGV differs from the gateway's own reported original target (the relay altered the target)",
    "D6_provenance_mismatch": "the gateway is authenticated, yet the UAV's own cryptographic signature on the target does NOT match the coordinates the gateway forwarded to the UGV: the trusted relay itself altered the target",
    "D6_provenance_unsigned": "the end-to-end target provenance token failed the UAV's signature verification, so the relayed target cannot be trusted",
    "BLOCK_unsigned_cmd": "an unsigned SET_POSITION_TARGET command from source 255 was seen",
    "D2_signature_fail": "MAVLink2 signature verification failed on an incoming command",
    "D5_telemetry_spoof": "reported telemetry position disagrees with the independent observation",
}


def demo2():
    out = []
    for tactic, mechs, truth_cause, truth_resp in TRIAGE_CASES:
        tags = real_alarm(tactic, mechs)
        obs = "; ".join(ALARM_DESC.get(t, t) for t in tags) or "no alarms"
        user = (f"Detector alarms observed during the engagement:\n  {obs}\n\n"
                "Answer with ONLY a JSON object: "
                '{"root_cause": "<short>", "response": "<one of the listed responses>"}')
        raw = llm(SYS_TRIAGE, user, max_tokens=240)
        js = extract_json(raw) or {}
        resp = (js.get("response") or "").lower()
        # 핵심 대응코드(R1/R3/D2)가 일치하는지로 판정
        key = ("R1" if "r1" in resp or "dead" in resp else
               "R3" if "r3" in resp or "isolate" in resp or "roll" in resp else
               "D2" if "d2" in resp or "unsigned" in resp or "block" in resp else "?")
        truth_key = ("R1" if "R1" in truth_resp else "R3" if "R3" in truth_resp else "D2")
        out.append({"tactic": tactic, "alarms": tags, "truth_cause": truth_cause,
                    "truth_response": truth_resp, "llm_root_cause": js.get("root_cause"),
                    "llm_response": js.get("response"), "match": key == truth_key, "raw": raw})
    return out


def main():
    print("=" * 84)
    print("JANUS 실제 LLM 전략가 실증 (Qwen2.5-VL-7B-Instruct, mlx-vlm, 텍스트 전용, greedy) — 6.10.4")
    print("=" * 84)

    d1 = demo1()
    print("\n[Demo-1] 방어 전략 선택 (예산 B=3):")
    print(f"  LLM 판단: 고정배치 안전={d1['parsed'].get('single_fixed_posture_safe')}, "
          f"무작위화={d1['parsed'].get('randomize')}, 우선불변식={d1['parsed'].get('priority_mechanism')}")
    print(f"  LLM 1차 태세 {d1['enable']} (예산준수={d1['cost_ok']}) → 최악대응 {d1['llm_posture_worstcase']} "
          f"(전술 {d1['llm_posture_worst_tactic']})")
    if d1["llm_randomization"]:
        r = d1["llm_randomization"]
        print(f"  LLM 무작위화 제안 {r['between']} (예산준수 {r['budget_ok']}) → 혼합 최악대응 {r['worstcase']}"
              f"  vs minimax {d1['game_value_minimax']}")
    print(f"  게임이론 기준: 어떤 고정태세 최악 {d1['any_fixed_worstcase']} / minimax 혼합 {d1['game_value_minimax']}")
    print(f"  일치: 고정불가={d1['agree']['no_fixed_safe']}, 무작위화={d1['agree']['randomize']}, "
          f"우선={d1['agree']['priority_is_loadbearing']}")

    d2 = demo2()
    print("\n[Demo-2] 분류·대응 triage (실제 경보 → 근본원인·대응):")
    for c in d2:
        mark = "OK" if c["match"] else "MISS"
        print(f"  [{mark}] {c['tactic']:12} 경보={c['alarms']}")
        print(f"        LLM: {c['llm_root_cause']} → {c['llm_response']}")
        print(f"        규칙: {c['truth_cause']} → {c['truth_response']}")
    n_match = sum(c["match"] for c in d2)

    import statistics
    times = _CACHE.get("times", [])
    llm_lat = {"calls": len(times), "median_s": round(statistics.median(times), 2) if times else None,
               "all_s": [round(x, 2) for x in times]}
    print(f"\n[지연] LLM 결정 {llm_lat['calls']}건 중앙값 {llm_lat['median_s']} s/건 (2-시간척도 입력, 6.10.5)")
    out = {"model": MODEL, "decoding": "greedy(temp=0)", "demo1_strategy": d1,
           "demo2_triage": d2, "triage_match": f"{n_match}/{len(d2)}", "llm_decision_seconds": llm_lat}
    with open(os.path.join(RESULTS, "llm_strategist_log.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n  triage 일치: {n_match}/{len(d2)}")
    print(f"  결과 저장: {RESULTS}/llm_strategist_log.json")


if __name__ == "__main__":
    main()
