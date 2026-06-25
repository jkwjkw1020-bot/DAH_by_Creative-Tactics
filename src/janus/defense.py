"""BLUE 팀 방어 도구 — 5장 탐지·차단·복구 모듈.

탐지:
 verify_command       D2 MAVLink 서명 검증 (명령 주입)
 innovation_monitor   D1 센서융합 이상탐지 (GPS 스푸핑)
 gateway_integrity    D3 게이트웨이 무결성 (표적좌표 변조 횡적확산)
 telemetry_crosscheck D5 텔레메트리 교차검증 (은폐)
차단:
 block_unsigned       MAVLink2 서명 강제 (미서명 거부)
복구:
 recover_navigation   R1 진단기반 추측항법 전환
 failsafe             R2 페일세이프
 isolate_and_rollback R3 게이트웨이 격리 + 표적 롤백
"""
import numpy as np
from . import mavlink_lite as mav


class BlueDefender:
    def __init__(self, world, innov_threshold: float = 3.0,
                 use_cusum: bool = False, cusum_slack: float = 1.5, cusum_h: float = 6.0):
        self.world = world
        self.innov_threshold = innov_threshold   # 미터; 이노베이션 고정 임계(χ² 유사)
        # CUSUM(누적합 관리도): 작은 편향도 지속되면 누적 탐지 → 스텔스 스푸핑 대응(보완책)
        self.use_cusum = use_cusum
        self.cusum_slack = cusum_slack           # 허용 잡음 마진
        self.cusum_h = cusum_h                   # 누적 경보 임계
        self._cusum = {}
        self.alarms = []

    def _alarm(self, *e):
        rec = (round(self.world.t, 1),) + e
        self.alarms.append(rec)
        return rec

    # --- 탐지 ---
    # D2: MAVLink 서명 검증
    def verify_command(self, msg) -> bool:
        v = self.world.get(msg.fields.get("target"))
        if v is None:
            return False
        ok = mav.verify_message(msg, v.key)
        if not ok:
            self._alarm("D2_signature_fail", msg.name, f"src={msg.source_system}")
        return ok

    # D1: 센서융합 이상탐지 (GPS 스푸핑) — 임계 초과 차량 반환
    #     고정 임계 + (보완) CUSUM 누적합 검정으로 스텔스(임계 직하) 스푸핑까지 포착.
    def innovation_monitor(self):
        hits = []
        for v in self.world.vehicles:
            triggered = v.innovation > self.innov_threshold
            tag = "D1_innovation"
            if self.use_cusum:
                s = max(0.0, self._cusum.get(v.sysid, 0.0) + (v.innovation - self.cusum_slack))
                self._cusum[v.sysid] = s
                if not triggered and s > self.cusum_h:
                    triggered = True
                    tag = "D1_cusum"   # 누적합 검정으로 스텔스 스푸핑 탐지
            if triggered:
                self._alarm(tag, v.sysid, round(float(v.innovation), 2))
                hits.append(v.sysid)
        return hits

    # D3: 게이트웨이 무결성 (중계 표적 vs 진짜 표적 불일치)
    def gateway_integrity(self) -> bool:
        g = self.world.gateway
        if g.relayed_target is not None and g.true_target is not None:
            d = float(np.linalg.norm(g.relayed_target - g.true_target))
            if d > 5.0:
                self._alarm("D3_gateway_tamper", round(d, 2))
                return False
        return True

    # D5: 텔레메트리 교차검증 (보고 위치 vs 독립 관측=true_pos)
    def telemetry_crosscheck(self):
        hits = []
        for v in self.world.vehicles:
            if v.telemetry_spoof is not None:
                d = float(np.linalg.norm(v.reported_pos() - v.true_pos))
                if d > 5.0:
                    self._alarm("D5_telemetry_spoof", v.sysid, round(d, 2))
                    hits.append(v.sysid)
        return hits

    # --- 차단 ---
    def block_unsigned(self, msg) -> bool:
        """미서명/위조 명령이면 True(차단)."""
        v = self.world.get(msg.fields.get("target"))
        if v is not None and not mav.verify_message(msg, v.key):
            self._alarm("BLOCK_unsigned_cmd", msg.name, f"src={msg.source_system}")
            return True
        return False

    # --- 복구 ---
    def recover_navigation(self, sysid):
        v = self.world.get(sysid)
        v.nav_source = "DEAD_RECKONING"   # 손상 GPS 무시, IMU 사용
        return self._alarm("R1_recover_nav", sysid)

    def failsafe(self, sysid):
        v = self.world.get(sysid)
        v.mode = "SAFE"
        return self._alarm("R2_failsafe", sysid)

    def isolate_and_rollback(self):
        g = self.world.gateway
        g.compromised = False
        g.tampered = False
        if g.true_target is not None:
            g.relayed_target = g.true_target.copy()
        return self._alarm("R3_isolate_rollback", g.name)
