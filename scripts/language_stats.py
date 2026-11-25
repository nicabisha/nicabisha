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
from pathlib import Path

API_URL = "https://api.github.com/graphql"
OUTPUT = Path("images/language-distribution.svg")
TOP_N = 8          # languages shown individually; the rest collapse into "Other"
MIN_SLICE = 0.005  # languages under 0.5% get folded into "Other"
CHAR_W = 9.6       # 0.6em advance width of the legend's monospace stack
FIT_MARGIN = 8     # breathing room before a legend column ends

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
text { font-family: ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace; }
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


def fit_name(name, pct_str, col_w):
    """Truncate a name so 'name pct' fits its column (word boundary first)."""
    budget = int((col_w - 18 - FIT_MARGIN) / CHAR_W)  # 18 = dot + gap before text
    max_name = budget - len(pct_str) - 1  # 1 for the separating space
    if len(name) <= max_name:
        return name
    cut = name[: max_name - 1].rstrip()  # room for the ellipsis
    if " " in cut:
        cut = cut[: cut.rindex(" ")].rstrip()
    return cut.rstrip(" .,;:-") + "…"


def fallback_svg(message):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="320" '
        'viewBox="0 0 600 320" role="img">\n'
        f"  <style>{CSS}</style>\n"
        f'  <text class="t" x="300" y="165" text-anchor="middle" font-size="16" '
        f'opacity="0.7">{html.escape(message)}</text>\n'
        "</svg>\n"
    )


def stacked_bar_svg(rankings, colors, repo_count):
    # Displayed at width=600 in the README; keep them equal so 1 SVG px = 1
    # CSS px and the 16px legend text matches the README's font size exactly.
    width, pad = 600, 20
    bar_y, bar_h = 24, 12
    bar_w = width - 2 * pad
    font_size = 16

    def color_of(name):
        return colors.get(name, "#8b949e")

    # Language bar: proportional segments drawn inside a rounded clip path, so
    # the ends of the bar are rounded but the edges between languages stay
    # square - the same look as the language bar on GitHub repo pages.
    segments, acc = [], 0.0
    for i, (name, frac) in enumerate(rankings):
        seg = bar_w * frac
        if i == len(rankings) - 1:
            seg = bar_w * (1 - acc)  # last segment absorbs rounding gaps
        segments.append(
            f'<rect x="{pad + bar_w * acc:.2f}" y="{bar_y}" width="{seg:.2f}" '
            f'height="{bar_h}" fill="{color_of(name)}" />'
        )
        acc += frac

    # Legend: dot + name + percentage, three entries per row.
    per_row, row_h = 3, 28
    rows = math.ceil(len(rankings) / per_row)
    legend_top = bar_y + bar_h + 34
    height = legend_top + rows * row_h + 6

    legend = []
    for i, (name, frac) in enumerate(rankings):
        pct_str = f"{frac * 100:.1f}%"
        col, row = i % per_row, i // per_row
        x = pad + col * (bar_w / per_row)
        y = legend_top + row * row_h
        legend.append(
            f'<circle cx="{x + 6:.0f}" cy="{y - 5}" r="6" fill="{color_of(name)}" />'
        )
        legend.append(
            f'<text class="t" x="{x + 18:.0f}" y="{y}" font-size="{font_size}">'
            f'{html.escape(fit_name(name, pct_str, bar_w / per_row))} '
            f'<tspan opacity="0.65">{pct_str}</tspan></text>'
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Language distribution across {repo_count} repositories">\n'
        f"  <style>{CSS}</style>\n"
        f'  <clipPath id="bar-clip"><rect x="{pad}" y="{bar_y}" width="{bar_w}" '
        f'height="{bar_h}" rx="{bar_h / 2}" /></clipPath>\n'
        f'  <g clip-path="url(#bar-clip)">\n    ' + "\n    ".join(segments) + "\n  </g>\n"
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
        stacked_bar_svg(rankings, colors, repo_count)
        if rankings
        else fallback_svg("No language data found across your repos yet.")
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(svg, encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT} ({repo_count} repos, {len(rankings)} languages)")


if __name__ == "__main__":
    main()
