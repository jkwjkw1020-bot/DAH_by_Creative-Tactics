#!/usr/bin/env python3
"""보고서용 아키텍처/흐름 다이어그램 4종 생성 (matplotlib, 한글 폰트).

무채색(검정/회색) 테마. 공격(RED)·방어(GREEN)는 의미 구분을 위해 최소한으로만 사용.
출력: docs/diagrams/  fig_arch_coop / fig_killchain / fig_defense_stack / fig_janus_arch (.png)
실행: python3 src/make_diagrams.py
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.patches import FancyBboxPatch, Rectangle

FONT = "/System/Library/Fonts/Supplemental/AppleGothic.ttf"
fm.fontManager.addfont(FONT)
plt.rcParams["font.family"] = fm.FontProperties(fname=FONT).get_name()
plt.rcParams["axes.unicode_minus"] = False

OUT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "diagrams"))
os.makedirs(OUT, exist_ok=True)

# 무채색 팔레트 (파란색 제거)
INK = "#222222"        # 기본 선/글자 (검정 계열)
GRAY_BOX = "#ededed"   # 일반 박스 배경
GRAY_AREA = "#f4f4f4"  # 영역 배경
GRAY_AREA2 = "#e7e7e7" # 영역 배경 2
RED = "#b00000"        # 공격(의미 강조)
GREEN = "#1f7a44"      # 방어(의미 강조)
AMBER = "#8a6d00"      # 조정자


def box(ax, x, y, w, h, text, fc=GRAY_BOX, ec=INK, fs=9, tc="#111"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02", fc=fc, ec=ec, lw=1.6))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color=tc)


def arrow(ax, x1, y1, x2, y2, color=INK, lw=1.6):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle="-|>", color=color, lw=lw))


def d_coop(p):
    fig, ax = plt.subplots(figsize=(9, 4.6)); ax.set_xlim(0, 10); ax.set_ylim(0, 6); ax.axis("off")
    ax.add_patch(Rectangle((0.2, 0.4), 3.5, 5.0, fc=GRAY_AREA, ec="none"))
    ax.add_patch(Rectangle((6.3, 0.4), 3.5, 5.0, fc=GRAY_AREA2, ec="none"))
    ax.text(1.95, 5.6, "MAVLink 도메인 (UAV)", ha="center", fontsize=9, color=INK)
    ax.text(8.05, 5.6, "ROS2/DDS 도메인 (UGV)", ha="center", fontsize=9, color=INK)
    box(ax, 0.5, 3.8, 2.9, 1.0, "정찰 UAV\n(ArduPilot · MAVLink)")
    box(ax, 0.5, 1.0, 2.9, 1.0, "GCS\n(QGC · MAVProxy)")
    box(ax, 4.0, 2.45, 2.0, 1.3, "협동\n게이트웨이\nMAVLink↔ROS2", "#f2dede", RED, 9)
    box(ax, 6.6, 3.8, 2.9, 1.0, "타격 UGV\n(ROS2 스택)")
    box(ax, 6.6, 1.0, 2.9, 1.0, "UGV n\n(ROS2)")
    arrow(ax, 3.4, 4.3, 4.0, 3.4); arrow(ax, 3.4, 1.5, 4.0, 2.8)
    arrow(ax, 6.0, 3.4, 6.6, 4.3); arrow(ax, 6.0, 2.8, 6.6, 1.5)
    ax.annotate("신뢰경계 교차 · 단일 실패점", xy=(5.0, 2.45), xytext=(5.0, 0.55), ha="center",
                fontsize=8.5, color=RED, arrowprops=dict(arrowstyle="-|>", color=RED))
    fig.savefig(p, dpi=150, bbox_inches="tight"); plt.close()


def d_killchain(p):
    fig, ax = plt.subplots(figsize=(11, 2.8)); ax.set_xlim(0, 11); ax.set_ylim(0, 2.8); ax.axis("off")
    steps = [("① 정찰", "T1590"), ("② MITM", "T1557·T0830"), ("③ 장악\n명령+GPS", "T0855·T0856"),
             ("④ 횡적확산", "T1557·T0843"), ("⑤ 임무영향\n군집분열", "T0827·T0826"), ("⑥ 은폐", "T0856")]
    x, w, gap = 0.15, 1.66, 0.16
    for i, (t, tag) in enumerate(steps):
        fc = "#f2dede" if i == 1 else GRAY_BOX; ec = RED if i == 1 else INK
        box(ax, x, 0.95, w, 1.0, t, fc, ec, 8.5)
        ax.text(x + w / 2, 0.7, tag, ha="center", fontsize=6.5, color="#555")
        if i < 5:
            arrow(ax, x + w, 1.45, x + w + gap, 1.45)
        x += w + gap
    ax.text(5.5, 2.45, "작전 MIRROR-CRACK — 게이트웨이 한 점에서 시작해 협동 체계 전체로 확산",
            ha="center", fontsize=9, color=INK)
    fig.savefig(p, dpi=150, bbox_inches="tight"); plt.close()


def d_defense(p):
    fig, ax = plt.subplots(figsize=(9.5, 4.8)); ax.set_xlim(0, 10); ax.set_ylim(0, 6); ax.axis("off")
    layers = [("대응 계층", "진단기반 복구 · 페일세이프 · 군집 재구성", "임무 복원"),
              ("협동 계층", "합의(consensus) 인증 · 포메이션 이탈 감시", "군집 분열"),
              ("통신 계층", "MAVLink2 서명 · DDS-Security · 게이트웨이 IDS", "명령주입 · MITM"),
              ("물리 계층", "센서융합 이상탐지 (EKF 이노베이션, IMU↔GPS)", "항법(GPS) 기만")]
    y = 0.5
    for name, desc, atk in layers:
        box(ax, 1.2, y, 6.0, 1.0, f"{name}\n{desc}", GRAY_BOX, INK, 8.8)
        ax.annotate(atk, xy=(7.2, y + 0.5), xytext=(8.9, y + 0.5), ha="center", va="center",
                    fontsize=7.5, color=RED, arrowprops=dict(arrowstyle="-|>", color=RED))
        y += 1.2
    ax.text(4.2, 5.7, "JANUS-Blue 심층 방어 스택 (Zero-Trust)", ha="center", fontsize=10, color=INK)
    fig.savefig(p, dpi=150, bbox_inches="tight"); plt.close()


def d_janus(p):
    fig, ax = plt.subplots(figsize=(10, 6.2)); ax.set_xlim(0, 10); ax.set_ylim(0, 7.2); ax.axis("off")
    box(ax, 3.3, 6.1, 3.4, 0.85, "Orchestrator Agent (LLM)\n공방 진행 · 전략 · 설명 로그", "#f3ecd6", AMBER, 9)
    ax.add_patch(Rectangle((0.3, 2.7), 3.9, 2.9, fc="#faf0f0", ec=RED, lw=1.2))
    ax.add_patch(Rectangle((5.8, 2.7), 3.9, 2.9, fc="#eef6f0", ec=GREEN, lw=1.2))
    ax.text(2.25, 5.35, "RED TEAM (공격)", ha="center", color=RED, fontsize=10)
    for i, t in enumerate(["Recon Agent", "Exploit Agent", "C2 / Impact Agent"]):
        box(ax, 0.6, 4.5 - i * 0.75, 3.3, 0.58, t, "#f2dede", RED, 8.5)
    ax.text(7.75, 5.35, "BLUE TEAM (방어)", ha="center", color=GREEN, fontsize=10)
    for i, t in enumerate(["Sensor / IDS Agent", "Triage Agent", "Response / Recovery"]):
        box(ax, 6.1, 4.5 - i * 0.75, 3.3, 0.58, t, "#dfeee5", GREEN, 8.5)
    box(ax, 2.8, 0.5, 4.4, 1.0, "교전 환경 (ArduPilot SITL-lite + ROS2)\n공유 Blackboard · 텔레메트리", GRAY_BOX, INK, 9)
    arrow(ax, 4.4, 6.1, 2.4, 5.6); arrow(ax, 5.6, 6.1, 7.6, 5.6)
    arrow(ax, 2.25, 2.7, 4.2, 1.5, RED); arrow(ax, 7.75, 2.7, 5.8, 1.5, GREEN)
    arrow(ax, 5.0, 1.5, 5.0, 2.6, "#888")
    ax.text(5.15, 2.05, "공방 루프", fontsize=8, color="#666", ha="left")
    fig.savefig(p, dpi=150, bbox_inches="tight"); plt.close()


def main():
    d_coop(os.path.join(OUT, "fig_arch_coop.png"))
    d_killchain(os.path.join(OUT, "fig_killchain.png"))
    d_defense(os.path.join(OUT, "fig_defense_stack.png"))
    d_janus(os.path.join(OUT, "fig_janus_arch.png"))
    print("다이어그램 4종 생성 완료:", OUT)


if __name__ == "__main__":
    main()
