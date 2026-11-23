"""Generate images/language-distribution.svg from all of your GitHub repos.

Queries the GraphQL API as the token's owner, so private repos are included
too. Only aggregate language names + percentages end up in the SVG - never
repo names or code. The token is read from the GH_PAT environment variable
(fine-grained PAT, "All repositories", Metadata: read-only).
"""

import html
import json
import math
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_URL = "https://api.github.com/graphql"
OUTPUT = Path("images/language-distribution.svg")
TOP_N = 8          # languages shown individually; the rest collapse into "Other"
MIN_SLICE = 0.005  # languages under 0.5% get folded into "Other"

QUERY = """
query($after: String) {
  viewer {
    repositories(ownerAffiliations: OWNER, first: 100, after: $after, isFork: false) {
      pageInfo { hasNextPage endCursor }
      nodes {
        languages(first: 100) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""

CSS = """
text { font-family: 'Segoe UI', Ubuntu, 'Helvetica Neue', sans-serif; }
.t { fill: #1f2328; }
@media (prefers-color-scheme: dark) { .t { fill: #e6edf3; } }
"""


def fetch_page(token, after=None):
    body = json.dumps({"query": QUERY, "variables": {"after": after}}).encode()
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "language-stats-svg",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as res:
        payload = json.load(res)
    if payload.get("errors"):
        raise SystemExit(f"GitHub API error: {payload['errors'][0].get('message')}")
    return payload["data"]["viewer"]["repositories"]


def collect(token):
    """Sum language bytes across every repo owned by the token's user."""
    totals = {}
    colors = {}
    after = None
    repo_count = 0
    while True:
        page = fetch_page(token, after)
        for repo in page["nodes"]:
            edges = repo["languages"]["edges"]
            if not edges:
                continue
            repo_count += 1
            for edge in edges:
                name = edge["node"]["name"]
                totals[name] = totals.get(name, 0) + edge["size"]
                if edge["node"]["color"]:
                    colors[name] = edge["node"]["color"]
        if page["pageInfo"]["hasNextPage"]:
            after = page["pageInfo"]["endCursor"]
        else:
            return totals, colors, repo_count


def rank(totals):
    """Return [(name, fraction), ...] with tail languages grouped as Other."""
    total = sum(totals.values())
    if total == 0:
        return []
    items = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    shown, other = [], 0.0
    for name, size in items:
        frac = size / total
        if len(shown) < TOP_N and frac >= MIN_SLICE:
            shown.append((name, frac))
        else:
            other += frac
    if other > 0:
        shown.append(("Other", other))
    return shown


def fallback_svg(message):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="560" height="320" '
        'viewBox="0 0 560 320" role="img">\n'
        f"  <style>{CSS}</style>\n"
        f'  <text class="t" x="280" y="165" text-anchor="middle" font-size="14" '
        f'opacity="0.7">{html.escape(message)}</text>\n'
        "</svg>\n"
    )


def donut_svg(rankings, colors, repo_count):
    width, height = 560, 320
    cx, cy, radius, stroke = 130, 192, 72, 32
    circumference = 2 * math.pi * radius
    today = datetime.now(timezone.utc).strftime("%b %d, %Y")

    def color_of(name):
        return colors.get(name, "#8b949e")

    # Donut slices: each circle's dash pattern draws its segment; negative
    # stroke-dashoffset places it after all previous ones. Rotated -90deg so
    # the chart starts at 12 o'clock.
    slices, acc = [], 0.0
    for i, (name, frac) in enumerate(rankings):
        seg = circumference * frac
        if i == len(rankings) - 1:
            seg = circumference * (1 - acc)  # last slice absorbs rounding gaps
        slices.append(
            f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" '
            f'stroke="{color_of(name)}" stroke-width="{stroke}" '
            f'stroke-dasharray="{seg:.2f} {circumference - seg:.2f}" '
            f'stroke-dashoffset="{-circumference * acc:.2f}" />'
        )
        acc += frac

    legend = []
    y = 92
    for name, frac in rankings:
        legend.append(f'<circle cx="258" cy="{y - 5}" r="6" fill="{color_of(name)}" />')
        legend.append(
            f'<text class="t" x="272" y="{y}" font-size="14">{html.escape(name)}</text>'
        )
        legend.append(
            f'<text class="t" x="530" y="{y}" font-size="14" text-anchor="end" '
            f'opacity="0.75">{frac * 100:.1f}%</text>'
        )
        y += 26

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Language distribution across {repo_count} repositories">\n'
        f"  <style>{CSS}</style>\n"
        f'  <text class="t" x="20" y="36" font-size="20" font-weight="700">'
        f"Language Distribution</text>\n"
        f'  <text class="t" x="20" y="58" font-size="12" opacity="0.6">'
        f"across {repo_count} repos &#183; updated {today}</text>\n"
        f'  <g transform="rotate(-90 {cx} {cy})">\n    ' + "\n    ".join(slices) + "\n  </g>\n"
        + "\n".join(f"  {line}" for line in legend)
        + "\n</svg>\n"
    )


def main():
    token = os.environ.get("GH_PAT")
    if not token:
        raise SystemExit(
            "GH_PAT is not set. Create a fine-grained personal access token "
            '(all repositories, permission "Metadata: read-only"), then expose '
            "it as this script's GH_PAT environment variable (locally) or as an "
            "Actions secret (in the workflow)."
        )

    totals, colors, repo_count = collect(token)
    rankings = rank(totals)
    svg = (
        donut_svg(rankings, colors, repo_count)
        if rankings
        else fallback_svg("No language data found across your repos yet.")
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(svg, encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT} ({repo_count} repos, {len(rankings)} languages)")


if __name__ == "__main__":
    main()
