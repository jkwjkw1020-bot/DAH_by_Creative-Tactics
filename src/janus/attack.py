"""RED 팀 공격 도구 — 4장 킬체인(MIRROR-CRACK) 실행 모듈.

각 메서드가 4장 킬체인 단계에 대응:
 recon            ① 정찰
 mitm_engage      ② 게이트웨이 MITM
 inject_command   ③ 명령 주입 (무서명 → 방어 D2/차단 대상)
 gps_spoof_step   ③ GPS 점진 스푸핑 (페일세이프 우회 시도)
 tamper_target    ④ 표적좌표 변조 횡적확산 (UAV→UGV)
 falsify_telemetry⑥ 텔레메트리 위조 은폐
"""
import numpy as np
from . import mavlink_lite as mav


class RedAttacker:
    def __init__(self, world):
        self.world = world
        self.mitm_active = False
        self.log = []

    def _log(self, *e):
        self.log.append((round(self.world.t, 1),) + e)

    # ① 정찰
    def recon(self):
        nodes = [(v.sysid, v.vtype) for v in self.world.vehicles]
        self._log("recon", nodes, self.world.gateway.name)
        return {"nodes": nodes, "gateway": self.world.gateway.name}

    # ② 게이트웨이 MITM
    def mitm_engage(self):
        self.mitm_active = True
        self.world.gateway.compromised = True
        self._log("mitm_engage", "gateway compromised")

    # ③ 명령 주입 (GCS sysid=255 사칭, 서명 없음)
    def inject_command(self, target_sysid, x, y, z):
        msg = mav.set_position_target(target_sysid, x, y, z, sysid=mav.GCS_SYSID)
        msg.t = self.world.t          # 신선한 명령(시각 위조 아님) → D7이 아닌 D2(미서명)로 잡힘
        # 의도적으로 서명하지 않음 → MAVLink2 미서명 주입
        self.world.deliver(msg, signed=False)
        self._log("inject_command", target_sysid, (round(x, 1), round(y, 1), round(z, 1)))
        return msg

    # ⑤ 리플레이 (과거에 캡처한 '유효 서명' 명령을 stale 타임스탬프로 재전송)
    #    서명이 진짜이므로 서명검증(D2)은 통과한다 → 신선도(D7)만이 막을 수 있다.
    def replay_command(self, target_sysid, x, y, z, stale_age=10.0):
        v = self.world.get(target_sysid)
        msg = mav.set_position_target(target_sysid, x, y, z, sysid=mav.GCS_SYSID)
        mav.sign_message(msg, v.key)          # 과거 캡처한 유효 서명을 재사용(공격자가 키 보유 아님)
        msg.t = self.world.t - stale_age      # 과거 시각 → stale(리플레이)
        self.world.deliver(msg, signed=True)
        self._log("replay_command", target_sysid, (round(x, 1), round(y, 1), round(z, 1)))
        return msg

    # ⑤' 탈동기 (협동 채널의 시간동기 붕괴: stale한 UAV 상태를 UGV에 계속 중계)
    #     중계 내용은 한때 참이었으므로 내용·서명 검증으론 안 잡히고 신선도(D7)만 포착한다.
    def desync_relay(self):
        if self.world.gateway.compromised:
            self.world.gateway.desync = True
            self.world.gateway.desync_t = self.world.t
            self._log("desync_relay", "cooperative channel desynchronized")
            return True
        return False

    # ③ GPS 점진 스푸핑 (한 스텝당 drift만큼 bias 누적)
    #    cap: bias 크기 상한. 탐지 임계 직하로 유지하면 고정임계 탐지를 회피하는 '스텔스 스푸핑'.
    def gps_spoof_step(self, target_sysid, drift_per_step, cap=None):
        v = self.world.get(target_sysid)
        new_bias = v.gps_bias + np.array(drift_per_step, float)
        if cap is not None:
            n = float(np.linalg.norm(new_bias))
            if n > cap:
                new_bias = new_bias / n * cap   # 스텔스: bias 크기를 cap으로 제한
        v.gps_bias = new_bias
        self._log("gps_spoof", target_sysid, np.round(v.gps_bias, 2).tolist())

    # ④ 표적좌표 변조 (게이트웨이 장악 전제) → UGV로 횡적확산
    def tamper_target(self, fake_xyz):
        if self.world.gateway.compromised:
            self.world.gateway.tampered = True
            self.world.gateway.relayed_target = np.array(fake_xyz, float)
            self._log("tamper_target", [round(c, 1) for c in fake_xyz])
            return True
        return False

    # ④' 게이트웨이 자기보고 위조 (장악된 게이트웨이가 보고 원표적을 중계값으로 맞춰 홉바이홉 검증 회피)
    def forge_gateway_provenance(self):
        if self.world.gateway.compromised:
            self.world.gateway.forge_provenance = True
            self._log("forge_provenance", "gateway self-report forged")
            return True
        return False

    # ⑥ 텔레메트리 위조 (은폐)
    def falsify_telemetry(self, target_sysid, fake_xyz):
        v = self.world.get(target_sysid)
        v.telemetry_spoof = np.array(fake_xyz, float)
        self._log("falsify_telemetry", target_sysid)
