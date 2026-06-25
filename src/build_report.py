#!/usr/bin/env python3
"""report/*.md 를 순서대로 합쳐 단일 PDF로 빌드.

markdown → HTML → PDF (xhtml2pdf/pisa). 한글 폰트(AppleGothic) 등록, 그림 절대경로 삽입.
실행: python3 src/build_report.py
출력: report/DAH2026_예선보고서_Creative-Tactics.pdf
"""
import os
import markdown
from xhtml2pdf import pisa

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
REPORT = os.path.join(ROOT, "report")
RESULTS = os.path.join(ROOT, "docs", "results")
DIAG = os.path.join(ROOT, "docs", "diagrams")
FONT = "/System/Library/Fonts/Supplemental/AppleGothic.ttf"
OUT = os.path.join(REPORT, "DAH2026_예선보고서_Creative-Tactics.pdf")

ORDER = ["01_cover", "02_toc", "03_team", "04_attack_scenario",
         "05_defense", "06_agent", "07_conclusion", "08_references"]

# 무채색(검정) 테마
CSS = """
@page { size: A4; margin: 1.8cm; }
body { font-family: korean; font-size: 10.5pt; line-height: 1.55; color:#111; }
h1 { font-size: 17pt; color:#000; border-bottom:2px solid #000; padding-bottom:3px; }
h2 { font-size: 13.5pt; color:#000; margin-top:13px; }
h3 { font-size: 11.5pt; color:#222; }
table { border-collapse: collapse; width:100%; font-size:8.8pt; margin:6px 0; }
th, td { border:1px solid #777; padding:3px 5px; }
th { background:#333; color:#fff; }
code, pre { font-family: korean; background:#f3f3f3; font-size:8.4pt; }
pre { padding:6px; border:1px solid #ccc; }
img { max-width:88%; }
blockquote { border-left:3px solid #555; padding-left:9px; color:#222; background:#f5f5f5; }
"""
FONT_DECL = f'@font-face {{ font-family: korean; src: url("{FONT}"); }}'


def load_md():
    parts = []
    for i, name in enumerate(ORDER):
        with open(os.path.join(REPORT, name + ".md"), encoding="utf-8") as f:
            txt = f.read()
        if i > 0:
            parts.append('\n\n<div style="page-break-before: always;"></div>\n\n')
        parts.append(txt)
    return "\n".join(parts)


def main():
    md = (load_md()
          .replace("../docs/results/", RESULTS + os.sep)
          .replace("../docs/diagrams/", DIAG + os.sep))
    body = markdown.markdown(md, extensions=["tables", "fenced_code", "sane_lists"])
    html = (f"<html><head><meta charset='utf-8'><style>{FONT_DECL}{CSS}</style></head>"
            f"<body>{body}</body></html>")
    with open(OUT, "wb") as f:
        result = pisa.CreatePDF(html, dest=f, encoding="utf-8")
    size = os.path.getsize(OUT) if os.path.exists(OUT) else 0
    print(f"PDF 생성: {OUT}")
    print(f"  크기: {size/1024:.0f} KB / 에러: {result.err}")


if __name__ == "__main__":
    main()
