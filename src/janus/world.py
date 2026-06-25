"""교전 환경(Env): UAV/UGV 운동·센서 시뮬레이션 + 협동 게이트웨이.

위치는 로컬 ENU 미터 좌표(x, y, z). 핵심 설계:
- true_pos : 실제 위치 (제어로 이동)
- dr_pos   : IMU 추측항법(dead reckoning) 위치 — GPS 스푸핑 bias의 영향을 받지 않음
- gps      : GPS 측정 = true_pos + gps_bias(공격자 스푸핑) + 잡음
- nav_pos  : 항법/제어에 실제 사용하는 위치(GPS 또는 추측항법)
- innovation = |gps - dr_pos| : 센서 융합 잔차. 스푸핑 시 단조 증가 → 탐지 신호(5장 D1)

GPS 스푸핑이 실제 경로를 왜곡하도록, 제어는 '인식 위치(nav_pos)' 기준으로 수행한다
(드론은 자신이 nav_pos에 있다고 믿고 목표로 이동 → nav_pos가 +로 치우치면 실제는 -로 이탈).
"""
import numpy as np
from . import mavlink_lite as mav


class Vehicle:
    def __init__(self, sysid: int, vtype: str, pos):
        self.sysid = sysid
        self.vtype = vtype                       # 'uav' | 'ugv'
        self.true_pos = np.array(pos, float)
        self.dr_pos = np.array(pos, float)       # IMU 추측항법
        self.nav_pos = np.array(pos, float)      # 항법/제어에 쓰는 위치
        self.vel = np.zeros(3)
        self.target = np.array(pos, float)
        self.gps_bias = np.zeros(3)              # 공격자 GPS 스푸핑 누적 bias
        self.innovation = 0.0
        self.mode = "AUTO"                        # AUTO | SAFE
        self.nav_source = "GPS"                   # GPS | DEAD_RECKONING(복구 시)
        self.telemetry_spoof = None               # 은폐: GCS에 보이는 위조 위치
        self.key = b"mavkey-" + str(sysid).encode()  # MAVLink2 서명 공유키

    def set_target(self, t):
        self.target = np.array(t, float)

    def step(self, dt: float):
        # 제어: '인식 위치(nav_pos)' 기준 비례 제어 (SAFE 모드면 감속)
        if self.mode == "SAFE":
            self.vel *= 0.6
        else:
            err = self.target - self.nav_pos       # ← GPS 스푸핑이 실제 경로를 왜곡하는 핵심
            self.vel = np.clip(err * 0.8, -6.0, 6.0)
        move = self.vel * dt
        self.true_pos = self.true_pos + move

        # IMU 추측항법: 참 운동 + 작은 잡음 (bias 없음)
        self.dr_pos = self.dr_pos + move + np.random.normal(0, 0.05, 3)

        # GPS 측정 (스푸핑 bias 포함)
        gps = self.true_pos + self.gps_bias + np.random.normal(0, 0.2, 3)

        if self.nav_source == "GPS":
            self.innovation = float(np.linalg.norm(gps - self.dr_pos))
            self.nav_pos = gps
        else:  # DEAD_RECKONING: 손상된 GPS 무시, IMU 사용 (복구 R1)
            self.innovation = 0.0
            self.nav_pos = self.dr_pos.copy()

    def reported_pos(self):
        """GCS가 보는 위치 (은폐 공격 시 위조 값)."""
        return self.telemetry_spoof if self.telemetry_spoof is not None else self.true_pos


class Gateway:
    """MAVLink(UAV) ↔ ROS2(UGV) 협동 게이트웨이. 신뢰 연쇄의 단일 지점."""
    def __init__(self, name: str = "COOP-GW"):
        self.name = name
        self.compromised = False     # MITM 장악 여부
        self.tampered = False        # 표적좌표 변조 활성 여부
        self.true_target = None      # UAV가 산출한 진짜 표적좌표
        self.relayed_target = None   # UGV로 실제 중계된 좌표 (변조 시 fake 고정)

    def relay_target(self, target_xyz):
        """UAV→UGV 표적좌표 중계. 변조(tampered) 상태면 fake 값을 유지(횡적확산)."""
        self.true_target = np.array(target_xyz, float)
        if self.compromised and self.tampered and self.relayed_target is not None:
            return self.relayed_target            # 변조된 값 유지
        self.relayed_target = self.true_target.copy()
        return self.relayed_target


class World:
    def __init__(self):
        self.vehicles = []
        self.gateway = Gateway()
        self.t = 0.0
        self.delivered = []   # (t, msg, signed) 전달된 명령 이력

    def add(self, v: Vehicle) -> Vehicle:
        self.vehicles.append(v)
        return v

    def get(self, sysid):
        for v in self.vehicles:
            if v.sysid == sysid:
                return v
        return None

    def deliver(self, msg, signed: bool):
        """명령 메시지를 환경에 투입(기록). 적용 여부는 방어 차단 통과 시 Orchestrator가 결정."""
        self.delivered.append((self.t, msg, signed))

    def step(self, dt: float):
        for v in self.vehicles:
            v.step(dt)
        self.t += dt
