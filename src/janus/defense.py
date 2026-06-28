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
                 use_cusum: bool = False, cusum_slack: float = 1.5, cusum_h: float = 6.0,
                 use_provenance: bool = False, use_robust_nav: bool = False,
                 enable_d1: bool = True, enable_d2: bool = True,
                 enable_d3: bool = True, enable_d5: bool = True,
                 enable_d7: bool = True, freshness_window: float = 3.0):
        self.world = world
        self.innov_threshold = innov_threshold   # 미터; 이노베이션 고정 임계(χ² 유사)
        # 방어 메커니즘 가동 여부(보안게임의 방어 태세/예산 배분 입력). 기본 전부 가동.
        # D1 센서융합·D2 서명·D3 게이트웨이무결성·D5 텔레메트리교차검증 / D6·투표는 아래 use_* 플래그.
        self.enable_d1 = enable_d1
        self.enable_d2 = enable_d2
        self.enable_d3 = enable_d3
        self.enable_d5 = enable_d5
        # D7 신선도(anti-replay): MAVLink2 서명의 타임스탬프처럼, 서명이 유효해도 stale한 메시지·중계를
        # 거부한다 [24]. 리플레이(서명 유효한 옛 명령)·탈동기(stale 협동 중계)를 막는 유일한 축.
        self.enable_d7 = enable_d7
        self.freshness_window = freshness_window  # 초; 이보다 오래된 메시지/중계는 stale로 본다
        # CUSUM(누적합 관리도): 작은 편향도 지속되면 누적 탐지 → 스텔스 스푸핑 대응(보완책)
        self.use_cusum = use_cusum
        self.cusum_slack = cusum_slack           # 허용 잡음 마진
        self.cusum_h = cusum_h                   # 누적 경보 임계
        self._cusum = {}
        # D6 종단간 출처증명: 장악된(인증된) 게이트웨이의 표적 위조까지 탐지
        self.use_provenance = use_provenance
        # 생존성: 다중 항법원 중앙값 투표를 켜 탐지 없이도 스푸핑 편향을 기각
        self.use_robust_nav = use_robust_nav
        if use_robust_nav:
            for v in world.vehicles:
                v.robust_nav = True
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

    # D3: 게이트웨이 무결성 (중계 표적 vs 게이트웨이가 보고한 원표적 = 홉바이홉 자기일관성)
    #     한계: 게이트웨이가 장악되어 자기보고까지 위조하면(forge_provenance) 무력화된다.
    def gateway_integrity(self) -> bool:
        g = self.world.gateway
        rep = g.reported_true_target if g.reported_true_target is not None else g.true_target
        if g.relayed_target is not None and rep is not None:
            d = float(np.linalg.norm(g.relayed_target - rep))
            if d > 5.0:
                self._alarm("D3_gateway_tamper", round(d, 2))
                return False
        return True

    # D6: 종단간 출처증명 (UAV가 서명한 표적 토큰 vs 게이트웨이 중계 표적)
    #     게이트웨이는 UAV 키가 없어 토큰을 위조할 수 없으므로, 자기보고를 위조해도 변조가 드러난다.
    def provenance_check(self) -> bool:
        tok = getattr(self.world, "uav_target_token", None)
        g = self.world.gateway
        if tok is None or g.relayed_target is None:
            return True
        uav = self.world.get(tok.source_system)
        if uav is None or not mav.verify_message(tok, uav.key):
            self._alarm("D6_provenance_unsigned", tok.name)
            return False
        claimed = np.array([tok.fields["x"], tok.fields["y"], tok.fields["z"]], float)
        d = float(np.linalg.norm(g.relayed_target - claimed))
        if d > 5.0:
            self._alarm("D6_provenance_mismatch", round(d, 2))
            return False
        return True

    # D7: 신선도(anti-replay) — 명령. 서명이 유효해도(=D2 통과) stale하면 리플레이로 차단.
    #   본 시뮬레이터의 명령은 msg.t에 '시뮬레이션 시각'을 싣는다(주입=현재 t, 리플레이=과거 t).
    #   가드 `t <= now+1`은 시뮬타임 타임스탬프를 가진 메시지에만 신선도 검사를 적용하기 위함이다.
    #   타임스탬프가 없거나 벽시계(time.time) 기본값인 메시지는 시뮬 신선도를 판정할 근거가 없어 건너뛴다.
    def is_replayed_command(self, msg) -> bool:
        t = getattr(msg, "t", None)
        if t is None:
            return False
        age = self.world.t - t
        if age > self.freshness_window and t <= self.world.t + 1:
            self._alarm("D7_replay", msg.name, round(age, 1))
            return True
        return False

    # D7: 신선도 — 협동 중계(탈동기). 게이트웨이가 stale한 UAV 상태를 UGV에 중계하면 포착.
    def cooperative_fresh(self) -> bool:
        g = self.world.gateway
        rt = getattr(g, "relay_t", None)
        if rt is None:
            return True
        if self.world.t - rt > self.freshness_window:
            self._alarm("D7_desync", round(self.world.t - rt, 1))
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
        g.desync = False                       # 탈동기 해제(재동기화)
        if g.true_target is not None:
            g.relayed_target = g.true_target.copy()
        return self._alarm("R3_isolate_rollback", g.name)
