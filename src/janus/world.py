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
        self.aux_pos = np.array(pos, float)      # 독립 절대 항법원(지형/영상 정합 등) — GPS와 무관, bias 없음
        self.nav_pos = np.array(pos, float)      # 항법/제어에 쓰는 위치
        self.robust_nav = False                  # True면 다중 항법원 중앙값 투표(생존성, 무탐지 편향 기각)
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
            if self.robust_nav:
                # 다중 항법원(GPS·IMU·독립원) 좌표별 중앙값 투표: 단일 편향 정보원을 기각.
                # 탐지(임계) 없이도 스푸핑 bias를 무력화하는 생존성 계층(5.3 다중 항법원 다수결).
                self.aux_pos = self.true_pos + np.random.normal(0, 0.3, 3)
                self.nav_pos = np.median(np.vstack([gps, self.dr_pos, self.aux_pos]), axis=0)
            else:
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
        self.forge_provenance = False  # 장악된 게이트웨이가 자기보고(reported_true_target)까지 위조 → 홉바이홉 검증 회피
        self.desync = False          # 탈동기: stale(시간 지연)한 UAV 상태를 계속 중계
        self.desync_pos = None       # 탈동기 온셋 시점의 (한때 참이던) 위치 — 이후 고정 중계
        self.desync_t = 0.0          # 탈동기 온셋 시각(중계 데이터의 신선도 기준 → 시간 지나면 stale)
        self.relay_t = None          # 마지막 중계의 신선도 타임스탬프(D7 입력)
        self.true_target = None      # UAV가 산출한 진짜 표적좌표 (정직한 그라운드트루스, 지표용)
        self.reported_true_target = None  # 게이트웨이가 방어에 자기보고하는 원표적 (위조 가능 → D3 홉바이홉 입력)
        self.relayed_target = None   # UGV로 실제 중계된 좌표 (변조 시 fake 고정)

    def relay_target(self, target_xyz, now=0.0):
        """UAV→UGV 표적좌표 중계. 변조(tampered)면 fake 유지, 탈동기(desync)면 stale 값 유지."""
        self.true_target = np.array(target_xyz, float)
        if self.desync:
            # 탈동기: 온셋 시점의 위치를 계속 중계 → UGV가 옛 UAV 위치를 추종(협동 시간동기 붕괴).
            # 내용은 한때 참이었으므로 보고도 일관(D3 통과)·서명/내용 검증으로는 안 잡힘. 신선도(D7)만 포착.
            if self.desync_pos is None:
                self.desync_pos = self.true_target.copy()
            self.relay_t = self.desync_t           # 중계 신선도가 온셋에 멈춤 → 시간 지나면 stale
            self.relayed_target = self.desync_pos
            self.reported_true_target = self.desync_pos.copy()
            return self.relayed_target
        self.relay_t = now                          # 정상: 매 중계가 신선
        if self.compromised and self.tampered and self.relayed_target is not None:
            relayed = self.relayed_target         # 변조된 값 유지
        else:
            self.relayed_target = self.true_target.copy()
            relayed = self.relayed_target
        # 게이트웨이가 방어 측에 보고하는 '원표적'. 장악+위조 시 중계값(fake)으로 위조해
        # 홉바이홉 자기일관성 검증(D3)을 무력화한다. 정상이면 진짜 원표적을 보고.
        if self.compromised and self.tampered and self.forge_provenance:
            self.reported_true_target = self.relayed_target.copy()
        else:
            self.reported_true_target = self.true_target.copy()
        return relayed


class World:
    def __init__(self):
        self.vehicles = []
        self.gateway = Gateway()
        self.t = 0.0
        self.delivered = []   # (t, msg, signed) 전달된 명령 이력
        self.uav_target_token = None  # UAV가 자신의 키로 서명한 종단간 표적 출처증명 토큰(D6 입력)

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
