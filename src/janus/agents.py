"""멀티에이전트 공방 오케스트레이션 — 6장.

RedTeamAgent  : 4장 킬체인을 수행하는 공격 에이전트 (FSM/스케줄 기반)
BlueTeamAgent : 5장 탐지·차단·복구를 수행하는 방어 에이전트 (설명가능)
Orchestrator  : 공방 폐루프 진행 + 점수화 + 메트릭 기록

[LLM 통합 지점] RedTeamAgent._decide / BlueTeamAgent._triage 는 실제 시스템에서
LLM(mlx-lm 등)이 환경 관찰을 받아 다음 전술/대응을 추론하는 자리다. 본 PoC는 재현성을 위해
결정적 규칙(rule) 정책을 사용하며, LLM 정책으로 교체 가능하도록 인터페이스를 분리했다.
"""
import numpy as np


class RedTeamAgent:
    """킬체인 스케줄 기반 공격. _decide()가 LLM 정책 교체 지점."""
    def __init__(self, world, attacker, sched):
        self.w = world
        self.atk = attacker
        self.s = sched
        self.done = set()

    def _once(self, key, t, t0, fn):
        if key not in self.done and t >= t0:
            fn()
            self.done.add(key)

    def _decide(self, t):
        s = self.s
        self._once("recon", t, s["recon_t"], self.atk.recon)                                  # ①
        self._once("mitm", t, s["mitm_t"], self.atk.mitm_engage)                               # ②
        self._once("inject", t, s["inject_t"],
                   lambda: self.atk.inject_command(s["uav"], *s["fake_uav_target"]))           # ③ 명령주입
        if s["spoof_t"] <= t < s["spoof_end"]:                                                 # ③ GPS 점진 스푸핑
            self.atk.gps_spoof_step(s["uav"], s["spoof_drift"], s.get("spoof_cap"))
        self._once("lateral", t, s["lateral_t"],
                   lambda: self.atk.tamper_target(s["fake_ugv_target"]))                       # ④
        self._once("evade", t, s["evade_t"],
                   lambda: self.atk.falsify_telemetry(s["uav"], s["telemetry_fake"]))          # ⑥

    def step(self, t):
        self._decide(t)


class BlueTeamAgent:
    """탐지→분류(triage)→대응. enabled=False면 무방비(공격 성공 대조군)."""
    def __init__(self, world, defender, enabled=True):
        self.w = world
        self.d = defender
        self.enabled = enabled
        self.detections = 0
        self.blocks = 0
        self.recoveries = 0
        self.explain = []   # (t, 설명) 설명가능 방어 로그

    def screen_command(self, msg) -> bool:
        """명령 적용 전 차단 판정. True=차단."""
        if not self.enabled:
            return False
        if self.d.block_unsigned(msg):
            self.blocks += 1
            self.explain.append((round(self.w.t, 1),
                                 f"미서명 {msg.name}(src={msg.source_system}) 탐지 → 서명검증 실패, 명령 차단(D2/Block)"))
            return True
        return False

    def _triage(self, t, spoof_hits, gw_ok, tele_hits):
        """[LLM 통합 지점] 경보를 종합해 근본원인 추정·대응 결정 (PoC: 규칙)."""
        for sid in spoof_hits:
            self.detections += 1
            self.d.recover_navigation(sid)
            self.recoveries += 1
            self.explain.append((round(t, 1),
                                 f"노드{sid}: 이노베이션 임계 초과(GPS-IMU 불일치) → GPS 스푸핑 추정 → R1 추측항법 전환"))
        if not gw_ok:
            self.detections += 1
            self.d.isolate_and_rollback()
            self.recoveries += 1
            self.explain.append((round(t, 1),
                                 "게이트웨이 중계 표적 ≠ 원 표적 → 횡적확산(표적 변조) 탐지 → R3 격리·롤백"))
        for sid in tele_hits:
            self.detections += 1
            self.explain.append((round(t, 1),
                                 f"노드{sid}: 보고위치 ≠ 독립관측 → 텔레메트리 위조(은폐) 탐지 → 신뢰소스 전환(D5)"))

    def monitor(self, t):
        if not self.enabled:
            return
        spoof_hits = self.d.innovation_monitor()       # D1
        gw_ok = self.d.gateway_integrity()             # D3
        tele_hits = self.d.telemetry_crosscheck()      # D5
        self._triage(t, spoof_hits, gw_ok, tele_hits)


class Orchestrator:
    """공방 폐루프 진행 + 메트릭 기록."""
    def __init__(self, world, red, blue):
        self.w = world
        self.red = red
        self.blue = blue
        self.metrics = []
        self._applied_idx = 0

    def _process_commands(self):
        """전달된 명령을 방어 스크리닝 후 적용(차단되면 미적용)."""
        while self._applied_idx < len(self.w.delivered):
            _, msg, _signed = self.w.delivered[self._applied_idx]
            self._applied_idx += 1
            if self.blue.screen_command(msg):
                continue  # 차단됨
            tgt = self.w.get(msg.fields.get("target"))
            if tgt is not None and "x" in msg.fields:
                tgt.set_target([msg.fields["x"], msg.fields["y"], msg.fields["z"]])

    def run(self, steps, dt, uav_orig_target, ugv_sysid):
        uav_sysid = self.red.s["uav"]
        for _ in range(steps):
            t = self.w.t
            self.red.step(t)             # 공격 행동
            self._process_commands()     # 주입 명령 스크리닝·적용

            # 협동: 게이트웨이가 UAV 위치를 표적으로 UGV에 중계 (변조 시 fake)
            uav = self.w.get(uav_sysid)
            relayed = self.w.gateway.relay_target(uav.true_pos)
            ugv = self.w.get(ugv_sysid)
            if ugv is not None:
                ugv.set_target(relayed)

            self.w.step(dt)              # 환경 진행
            self.blue.monitor(t)         # 방어 탐지·대응
            self._record(t, uav_orig_target, ugv_sysid)

    def _record(self, t, uav_orig_target, ugv_sysid):
        uav = self.w.get(self.red.s["uav"])
        g = self.w.gateway
        ugv_target_err = 0.0
        if g.relayed_target is not None and g.true_target is not None:
            ugv_target_err = float(np.linalg.norm(g.relayed_target - g.true_target))
        self.metrics.append({
            "t": round(t, 1),
            "uav_innov": round(float(uav.innovation), 3),
            "uav_pos_err": round(float(np.linalg.norm(uav.true_pos - uav_orig_target)), 3),
            "ugv_target_err": round(ugv_target_err, 3),
        })
