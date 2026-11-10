"""Gera a imagem de compartilhamento (docs/og.png, 1200x630) no estilo do site.

Rodar:  uv run --with cairosvg python scripts/make_og.py
"""

from __future__ import annotations

from pathlib import Path

import cairosvg

OUT = Path(__file__).resolve().parent.parent / "docs" / "og.png"

SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <defs>
    <pattern id="dots" width="28" height="28" patternUnits="userSpaceOnUse">
      <circle cx="1" cy="1" r="1" fill="#232a38"/>
    </pattern>
  </defs>
  <rect width="1200" height="630" fill="#0d1017"/>
  <rect width="1200" height="630" fill="url(#dots)" fill-opacity="0.6"/>

  <rect x="880" y="150" width="250" height="330" rx="20" fill="#4ade80" fill-opacity="0.05"
        stroke="#4ade80" stroke-width="2" stroke-dasharray="3 11"/>
  <text x="1005" y="134" text-anchor="middle" font-family="DejaVu Sans Mono, monospace"
        font-size="18" fill="#4ade80">escopo autorizado</text>
  <path d="M770 575 C870 575 850 300 970 300 S1060 345 1095 315" fill="none"
        stroke="#f5a623" stroke-width="5" stroke-linecap="round" stroke-dasharray="2 20"/>
  <circle cx="770" cy="575" r="14" fill="#f5a623"/>
  <circle cx="1060" cy="390" r="22" fill="none" stroke="#4ade80" stroke-width="4"/>
  <path d="M1048 390 l8 8 l16 -18" fill="none" stroke="#4ade80" stroke-width="4"
        stroke-linecap="round" stroke-linejoin="round"/>

  <circle cx="98" cy="118" r="16" fill="none" stroke="#f5a623" stroke-width="2.4"
          stroke-dasharray="2.4 7" stroke-linecap="round"/>
  <circle cx="98" cy="118" r="5.5" fill="#f5a623"/>
  <text x="128" y="128" font-family="DejaVu Sans, sans-serif" font-weight="bold"
        font-size="30" fill="#e7ebf2">scopehound</text>

  <text font-family="DejaVu Sans, sans-serif" font-weight="bold" font-size="66" fill="#f3f6fa">
    <tspan x="80" y="290">O farejador que</tspan>
    <tspan x="80" y="368">nunca sai do escopo.</tspan>
  </text>
  <text x="80" y="440" font-family="DejaVu Sans, sans-serif" font-size="26" fill="#aab4c4">
    Agente de IA para pentest assistido por humano.
  </text>
  <text x="80" y="478" font-family="DejaVu Sans, sans-serif" font-size="26" fill="#aab4c4">
    Escopo e permissões vivem fora do modelo.
  </text>
  <text x="80" y="560" font-family="DejaVu Sans Mono, monospace" font-size="20" fill="#8793a5">
    github.com/saulofilho/scopehound
  </text>
</svg>"""


def main() -> None:
    cairosvg.svg2png(bytestring=SVG.encode(), write_to=str(OUT), output_width=1200,
                     output_height=630)
    print(f"escrito: {OUT}")


if __name__ == "__main__":
    main()
