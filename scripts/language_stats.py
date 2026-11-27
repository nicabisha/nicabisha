"""Render your GitHub language distribution as ASCII art inside README.md.

Queries the GraphQL API as the token's owner. By default only public repos
count; pass --include-private to count private repos too. Only aggregate
language names + percentages end up in the README - never repo names or
code. The token is read from the GH_PAT environment variable (fine-grained
PAT, "All repositories", Metadata: read-only).
"""

import argparse
import html
import json
import os
import re
import urllib.request
from pathlib import Path

API_URL = "https://api.github.com/graphql"
README = Path("README.md")
TOP_N = 8          # languages shown individually; the rest collapse into "Other"
MIN_SLICE = 0.005  # languages under 0.5% get folded into "Other"
BAR_W = 16         # width of each bar, in characters
MAX_NAME_W = 16    # longest language name before truncation

STATS_BLOCK = re.compile(r"(<!-- stats:start -->)(.*?)(<!-- stats:end -->)", re.DOTALL)

QUERY = """
query($after: String) {
  viewer {
    repositories(ownerAffiliations: OWNER, first: 100, after: $after, isFork: false) {
      pageInfo { hasNextPage endCursor }
      nodes {
        isPrivate
        languages(first: 100) {
          edges { size node { name } }
        }
      }
    }
  }
}
"""


def fetch_page(token, after=None):
    body = json.dumps({"query": QUERY, "variables": {"after": after}}).encode()
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "language-stats-readme",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as res:
        payload = json.load(res)
    if payload.get("errors"):
        raise SystemExit(f"GitHub API error: {payload['errors'][0].get('message')}")
    return payload["data"]["viewer"]["repositories"]


def collect(token, include_private):
    """Sum language bytes across your repos (public only, unless asked)."""
    totals = {}
    after = None
    repo_count = 0
    while True:
        page = fetch_page(token, after)
        for repo in page["nodes"]:
            if repo["isPrivate"] and not include_private:
                continue
            edges = repo["languages"]["edges"]
            if not edges:
                continue
            repo_count += 1
            for edge in edges:
                name = edge["node"]["name"]
                totals[name] = totals.get(name, 0) + edge["size"]
        if page["pageInfo"]["hasNextPage"]:
            after = page["pageInfo"]["endCursor"]
        else:
            return totals, repo_count


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


def bar(frac):
    """Render a fraction as a BAR_W-wide bar of blocks, padded with spaces."""
    filled = max(round(frac * BAR_W), 1)  # at least one block so 0.x% stays visible
    return "█" * filled + " " * (BAR_W - filled)


def fit_name(name, width):
    """Truncate a name so it fits its column, keeping the ellipsis tidy."""
    if len(name) <= width:
        return name
    return name[: width - 1].rstrip(" .,;:-") + "…"


def render_ascii(rankings, repo_count):
    """Return the chart as a list of plain text lines."""
    if not rankings:
        return [f"languages · no data across {repo_count} repos yet"]
    name_w = min(max(len(name) for name, _ in rankings), MAX_NAME_W)
    lines = [f"languages · {repo_count} {'repo' if repo_count == 1 else 'repos'}"]
    for name, frac in rankings:
        pct = f"{frac * 100:.1f}%"
        lines.append(f"{fit_name(name, name_w):<{name_w}}  {bar(frac)}  {pct:>6}")
    return lines


def frame(lines):
    """Wrap chart lines in a heavy box-drawing frame."""
    inner = max(len(line) for line in lines)
    return (
        ["┏" + "━" * (inner + 2) + "┓"]
        + [f"┃ {line:<{inner}} ┃" for line in lines]
        + ["┗" + "━" * (inner + 2) + "┛"]
    )


def write_readme(lines):
    """Replace the text between the stats markers in README.md."""
    readme = README.read_text(encoding="utf-8")
    match = STATS_BLOCK.search(readme)
    if not match:
        raise SystemExit(
            "stats markers not found in README.md. Add a pair of them where "
            "the chart should go:\n"
            "  <!-- stats:start -->\n  <!-- stats:end -->"
        )
    # Borderless centered <samp> text art, same font as the greeting, no
    # box around it. Spaces must be &nbsp; or HTML collapses them and the
    # columns lose alignment; lines join on one source line so no stray
    # whitespace can sneak between rows.
    chart = "<br>".join(html.escape(line).replace(" ", "&nbsp;") for line in lines)
    block = (
        "<!-- stats:start -->\n"
        '<p align="center">\n'
        f"  <samp>{chart}</samp>\n"
        "</p>\n"
        "<!-- stats:end -->\n"
    )
    README.write_text(
        readme[: match.start()] + block + readme[match.end() :].lstrip("\n"),
        encoding="utf-8",
        newline="\n",
    )


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--include-private",
        action="store_true",
        help="count private repos too (default: public repos only)",
    )
    args = parser.parse_args()

    token = os.environ.get("GH_PAT")
    if not token:
        raise SystemExit(
            "GH_PAT is not set. Create a fine-grained personal access token "
            '(all repositories, permission "Metadata: read-only"), then expose '
            "it as this script's GH_PAT environment variable (locally) or as an "
            "Actions secret (in the workflow)."
        )

    totals, repo_count = collect(token, args.include_private)
    rankings = rank(totals)
    write_readme(frame(render_ascii(rankings, repo_count)))

    scope = "all repos" if args.include_private else "public repos only"
    print(f"Updated {README} ({repo_count} {scope}, {len(rankings)} languages)")


if __name__ == "__main__":
    main()
