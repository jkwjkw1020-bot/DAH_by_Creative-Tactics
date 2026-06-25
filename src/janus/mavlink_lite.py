"""경량 MAVLink2 메시지 모델 + HMAC 메시지 서명.

실제 pymavlink 의존 없이, MAVLink2의 실제 메시지 ID/시맨틱과 '메시지 서명'(message signing)
취약점·방어를 재현하기 위한 최소 구현. 실기체/SITL 연동 시 본 모듈을 pymavlink로 교체 가능.

출처:
- MAVLink common message set (common.xml) — 메시지 ID 정의
- MAVLink2 message signing specification — HMAC-SHA256 기반 서명(여기선 6바이트로 절단)
"""
import hmac
import hashlib
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

# --- 실제 MAVLink common.xml 메시지 ID ---
MSG_HEARTBEAT = 0
MSG_GLOBAL_POSITION_INT = 33
MSG_COMMAND_LONG = 76
MSG_SET_POSITION_TARGET_GLOBAL_INT = 86
MSG_GPS_INPUT = 232

MSG_NAME = {
    0: "HEARTBEAT",
    33: "GLOBAL_POSITION_INT",
    76: "COMMAND_LONG",
    86: "SET_POSITION_TARGET_GLOBAL_INT",
    232: "GPS_INPUT",
}

# GCS 관례 시스템 ID (공격자가 사칭하는 값)
GCS_SYSID = 255


@dataclass
class MAVMessage:
    msgid: int
    fields: Dict
    source_system: int = 1
    source_component: int = 1
    seq: int = 0
    signature: Optional[bytes] = None  # None == 미서명(MAVLink2 unsigned)
    t: float = field(default_factory=time.time)

    @property
    def name(self) -> str:
        return MSG_NAME.get(self.msgid, f"MSG{self.msgid}")

    def payload_bytes(self) -> bytes:
        """서명 대상 직렬화: msgid|sysid|comp|seq|정렬된 필드."""
        items = [str(self.msgid), str(self.source_system),
                 str(self.source_component), str(self.seq)]
        for k in sorted(self.fields):
            items.append(f"{k}={self.fields[k]}")
        return "|".join(items).encode()


def sign_message(msg: MAVMessage, key: bytes) -> MAVMessage:
    """MAVLink2 메시지 서명 부여 (HMAC-SHA256, 6바이트 절단)."""
    msg.signature = hmac.new(key, msg.payload_bytes(), hashlib.sha256).digest()[:6]
    return msg


def verify_message(msg: MAVMessage, key: bytes) -> bool:
    """서명 검증. 미서명이거나 위조면 False (= 주입 의심)."""
    if msg.signature is None:
        return False
    expected = hmac.new(key, msg.payload_bytes(), hashlib.sha256).digest()[:6]
    return hmac.compare_digest(expected, msg.signature)


# --- 메시지 팩토리 (위치는 시뮬 단순화를 위해 로컬 ENU 미터 x,y,z 사용) ---
def heartbeat(sysid: int = 1) -> MAVMessage:
    return MAVMessage(MSG_HEARTBEAT, {"type": "vehicle", "autopilot": "ardupilot"},
                      source_system=sysid)


def command_long(target: int, command: str, param1: float = 0.0,
                 sysid: int = GCS_SYSID) -> MAVMessage:
    return MAVMessage(MSG_COMMAND_LONG,
                      {"target": target, "command": command, "param1": param1},
                      source_system=sysid)


def set_position_target(target: int, x: float, y: float, z: float,
                        sysid: int = GCS_SYSID) -> MAVMessage:
    return MAVMessage(MSG_SET_POSITION_TARGET_GLOBAL_INT,
                      {"target": target, "x": round(x, 2), "y": round(y, 2), "z": round(z, 2)},
                      source_system=sysid)


def gps_input(target: int, x: float, y: float, z: float, sysid: int = 1) -> MAVMessage:
    return MAVMessage(MSG_GPS_INPUT,
                      {"target": target, "x": round(x, 2), "y": round(y, 2), "z": round(z, 2)},
                      source_system=sysid)


def global_position_int(sysid: int, x: float, y: float, z: float) -> MAVMessage:
    return MAVMessage(MSG_GLOBAL_POSITION_INT,
                      {"x": round(x, 2), "y": round(y, 2), "z": round(z, 2)},
                      source_system=sysid)
