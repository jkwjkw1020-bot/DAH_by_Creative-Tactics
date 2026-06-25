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
        # 의도적으로 서명하지 않음 → MAVLink2 미서명 주입
        self.world.deliver(msg, signed=False)
        self._log("inject_command", target_sysid, (round(x, 1), round(y, 1), round(z, 1)))
        return msg

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

    # ⑥ 텔레메트리 위조 (은폐)
    def falsify_telemetry(self, target_sysid, fake_xyz):
        v = self.world.get(target_sysid)
        v.telemetry_spoof = np.array(fake_xyz, float)
        self._log("falsify_telemetry", target_sysid)
