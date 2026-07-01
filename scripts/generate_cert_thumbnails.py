#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "cert-thumbnails"


CERTS = [
    {
        "file": "sqld.svg",
        "abbr": "SQLD",
        "name": "SQL Developer",
        "track": "Data / SQL",
        "colors": ("#0F766E", "#042F2E", "#A7F3D0"),
    },
    {
        "file": "adsp.svg",
        "abbr": "ADsP",
        "name": "Advanced Data Analytics Semi-Professional",
        "track": "Data Analysis",
        "colors": ("#7C3AED", "#2E1065", "#DDD6FE"),
    },
    {
        "file": "engineer-info-processing.svg",
        "abbr": "정보처리기사",
        "name": "Engineer Information Processing",
        "track": "Software Engineering",
        "colors": ("#1D4ED8", "#172554", "#BFDBFE"),
    },
    {
        "file": "aws-ai-practitioner.svg",
        "abbr": "AWS AIF",
        "name": "AWS Certified AI Practitioner",
        "track": "AI / Cloud",
        "colors": ("#FF9900", "#1F2937", "#FED7AA"),
    },
    {
        "file": "aws-cloud-practitioner.svg",
        "abbr": "AWS CLF",
        "name": "AWS Certified Cloud Practitioner",
        "track": "Cloud Foundations",
        "colors": ("#2563EB", "#0F172A", "#DBEAFE"),
    },
    {
        "file": "aws-solutions-architect-associate.svg",
        "abbr": "AWS SAA",
        "name": "AWS Solutions Architect Associate",
        "track": "Cloud Architecture",
        "colors": ("#DC2626", "#111827", "#FECACA"),
    },
    {
        "file": "google-cloud-generative-ai-leader.svg",
        "abbr": "GCP GenAI",
        "name": "Google Cloud Generative AI Leader",
        "track": "Generative AI",
        "colors": ("#16A34A", "#052E16", "#BBF7D0"),
    },
]


def svg_for(cert: dict[str, object]) -> str:
    primary, dark, light = cert["colors"]
    abbr = cert["abbr"]
    name = cert["name"]
    track = cert["track"]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630" role="img" aria-label="{abbr} study card">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{dark}"/>
      <stop offset="0.55" stop-color="#111827"/>
      <stop offset="1" stop-color="{primary}"/>
    </linearGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="18" stdDeviation="18" flood-color="#000000" flood-opacity="0.28"/>
    </filter>
  </defs>
  <rect width="1200" height="630" fill="url(#bg)"/>
  <rect x="72" y="72" width="1056" height="486" rx="34" fill="#FFFFFF" fill-opacity="0.08" stroke="#FFFFFF" stroke-opacity="0.22"/>
  <g filter="url(#shadow)">
    <rect x="116" y="116" width="256" height="256" rx="32" fill="{light}" fill-opacity="0.96"/>
    <text x="244" y="245" text-anchor="middle" font-family="Inter, Arial, sans-serif" font-size="58" font-weight="800" fill="{dark}">{abbr}</text>
    <text x="244" y="300" text-anchor="middle" font-family="Inter, Arial, sans-serif" font-size="22" font-weight="700" fill="{primary}">CBT</text>
  </g>
  <text x="430" y="190" font-family="Inter, Arial, sans-serif" font-size="34" font-weight="700" fill="{light}" letter-spacing="0">{track}</text>
  <text x="430" y="285" font-family="Inter, Arial, sans-serif" font-size="72" font-weight="850" fill="#FFFFFF" letter-spacing="0">{abbr}</text>
  <text x="430" y="345" font-family="Inter, Arial, sans-serif" font-size="30" font-weight="600" fill="#E5E7EB" letter-spacing="0">{name}</text>
  <line x1="430" y1="402" x2="1030" y2="402" stroke="#FFFFFF" stroke-opacity="0.26" stroke-width="2"/>
  <text x="430" y="462" font-family="Inter, Arial, sans-serif" font-size="26" font-weight="650" fill="#FFFFFF">Codex Learning System</text>
  <text x="430" y="502" font-family="Inter, Arial, sans-serif" font-size="22" font-weight="500" fill="#D1D5DB">Question bank · Wrong notes · Review queue</text>
</svg>
"""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for cert in CERTS:
        (OUT / str(cert["file"])).write_text(svg_for(cert), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

