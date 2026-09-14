"""Update README.md profile stats from the GitHub API (keeps existing HTML style)."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

USERNAME = "IvanCodesDev"
ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
CHART = ROOT / "assets" / "productive-time.png"
API = "https://api.github.com"
GRAPHQL = f"{API}/graphql"
UTC_OFFSET = 8
TZ = timezone(timedelta(hours=UTC_OFFSET))

FEATURED = [
    "software-certificate-skill",
    "ForgeX",
    "OmniSpeed",
    "OpenMathModel",
    "Nivik",
    "CiteBase",
]


def gh_headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{USERNAME}-readme-stats",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def gh_get(url: str) -> object:
    req = urllib.request.Request(url, headers=gh_headers())
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def gh_graphql(query: str, variables: dict) -> dict:
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    headers = gh_headers()
    headers["Content-Type"] = "application/json"
    req = urllib.request.Request(GRAPHQL, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.load(resp)
    if body.get("errors"):
        raise RuntimeError(body["errors"])
    assert isinstance(body, dict)
    return body


def add_hour(hours: list[int], iso: str) -> None:
    stamp = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ)
    hours[stamp.hour] += 1


def commit_hours() -> list[int]:
    hours = [0] * 24
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        data = gh_graphql(
            """
            query ($login: String!) {
              user(login: $login) {
                repositories(
                  first: 30
                  ownerAffiliations: OWNER
                  isFork: false
                  orderBy: { field: PUSHED_AT, direction: DESC }
                ) {
                  nodes {
                    defaultBranchRef {
                      target {
                        ... on Commit {
                          history(first: 100) {
                            nodes { committedDate }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
            """,
            {"login": USERNAME},
        )
        repos = (
            data.get("data", {})
            .get("user", {})
            .get("repositories", {})
            .get("nodes", [])
        )
        for repo in repos:
            ref = (repo or {}).get("defaultBranchRef") or {}
            target = ref.get("target") or {}
            for node in (target.get("history") or {}).get("nodes") or []:
                if node and node.get("committedDate"):
                    add_hour(hours, node["committedDate"])
        if sum(hours) > 0:
            return hours

    page = 1
    while page <= 3:
        events = gh_get(f"{API}/users/{USERNAME}/events/public?per_page=100&page={page}")
        if not isinstance(events, list) or not events:
            break
        for event in events:
            created = event.get("created_at")
            if created and event.get("type") in {"PushEvent", "CreateEvent", "PullRequestEvent"}:
                add_hour(hours, created)
        if len(events) < 100:
            break
        page += 1
    return hours


def render_productive_time(hours: list[int]) -> None:
    from PIL import Image, ImageDraw, ImageFont

    scale = 2
    width, height = 420 * scale, 200 * scale
    left, right, top, bottom = 36 * scale, 18 * scale, 58 * scale, 42 * scale
    plot_w = width - left - right
    plot_h = height - top - bottom
    peak = max(hours) if any(hours) else 1
    step = max(1, round(peak / 4) or 1)
    while step * 4 < peak:
        step += 1
    ymax = max(peak, step * 4)

    img = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(img)

    def font(size: int):
        candidates = (
            "segoeui.ttf",
            "arial.ttf",
            "DejaVuSans.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        )
        for name in candidates:
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    title_font = font(40)
    label_font = font(22)
    title = f"Commits (UTC +{UTC_OFFSET:.2f})"
    draw.text((width / 2, 32 * scale), title, fill="#111111", font=title_font, anchor="mm")

    gap = 3 * scale
    bar_w = (plot_w - gap * 23) / 24
    for i, count in enumerate(hours):
        h = 0 if ymax == 0 else plot_h * (count / ymax)
        x = left + i * (bar_w + gap)
        y = top + plot_h - h
        if h > 0:
            draw.rounded_rectangle((x, y, x + bar_w, top + plot_h), radius=3, fill="#111111")

    for n in range(5):
        val = ymax - step * n
        y = top + plot_h * (n / 4)
        draw.text((left - 8 * scale, y), str(val), fill="#8A8A8A", font=label_font, anchor="rm")

    for hour in (0, 6, 12, 18, 23):
        x = left + hour * (bar_w + gap) + bar_w / 2
        draw.text((x, height - 18 * scale), str(hour), fill="#8A8A8A", font=label_font, anchor="mm")

    draw.text(
        (width - right, height - 6 * scale),
        "per day hour",
        fill="#8A8A8A",
        font=label_font,
        anchor="rb",
    )
    img.save(CHART, format="PNG", optimize=True)


def list_repos() -> list[dict]:
    repos: list[dict] = []
    page = 1
    while True:
        batch = gh_get(
            f"{API}/users/{USERNAME}/repos?per_page=100&page={page}&type=owner&sort=updated"
        )
        if not isinstance(batch, list) or not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return repos


def set_stat(text: str, key: str, value: int) -> str:
    pattern = rf"(<!--STAT:{re.escape(key)}-->)\d+(<!--/STAT:{re.escape(key)}-->)"
    updated, n = re.subn(pattern, rf"\g<1>{value}\2", text, count=1)
    if n != 1:
        raise SystemExit(f"failed to update stat marker: {key}")
    return updated


def main() -> None:
    user = gh_get(f"{API}/users/{USERNAME}")
    assert isinstance(user, dict)
    followers = int(user.get("followers") or 0)
    public_repos = int(user.get("public_repos") or 0)

    repos = list_repos()
    total_stars = sum(int(r.get("stargazers_count") or 0) for r in repos if not r.get("fork"))

    featured_stats: dict[str, tuple[int, int]] = {}
    for name in FEATURED:
        data = gh_get(f"{API}/repos/{USERNAME}/{name}")
        assert isinstance(data, dict)
        featured_stats[name] = (
            int(data.get("stargazers_count") or 0),
            int(data.get("forks_count") or 0),
        )

    text = README.read_text(encoding="utf-8")
    text = set_stat(text, "stars", total_stars)
    text = set_stat(text, "followers", followers)
    text = set_stat(text, "repos", public_repos)
    for name, (stars, forks) in featured_stats.items():
        text = set_stat(text, f"{name}:stars", stars)
        text = set_stat(text, f"{name}:forks", forks)

    README.write_text(text, encoding="utf-8", newline="\n")
    hours = commit_hours()
    render_productive_time(hours)
    print(
        f"updated: stars={total_stars} followers={followers} repos={public_repos} featured={featured_stats} hours={hours}"
    )


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"GitHub API error: {e.code} {e.reason}") from e
