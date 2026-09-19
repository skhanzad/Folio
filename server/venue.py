"""Retrieve bounded, attributable venue guidance from public HTTPS pages.

Connections use a validated public IP while retaining the original TLS SNI and
Host header. Redirects and discovered links stay on the submitted site's host.
No API credential, manuscript, or browser cookie is sent to venue websites.
"""

import asyncio
import hashlib
import ipaddress
import re
import socket
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from .models import VenueContext, VenueRequest, VenueSource

MAX_DOWNLOAD = 2 * 1024 * 1024
SOURCE_BYTES = 2400
MAX_SOURCES = 3
PRESETS = [
    {
        "name": "NeurIPS 2026",
        "website": "https://neurips.cc/Conferences/2026/ReviewerGuidelines",
        "track": "General",
    },
]
SIGNALS = re.compile(
    r"\b(scope|topics?|research|review(?:ing|er)?|criteria|contributions?|originality|novelty|significance|"
    r"clarity|quality|soundness|rigou?r|evidence|reproducib\w*|methodology|ethics|limitations?|"
    r"machine learning|artificial intelligence)\b",
    re.IGNORECASE,
)
PRIORITY = re.compile(
    r"criteria|scope|soundness|originality|significance|clarity|quality|reproducib|topics", re.IGNORECASE
)


class VenueError(ValueError):
    pass


def normalize_url(value: str) -> str:
    try:
        value = value.strip()
        if re.search(r"[\x00-\x20\\]", value):
            raise ValueError()
        parsed = urlsplit(value)
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
        ):
            raise ValueError()
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        if not re.fullmatch(r"[a-z0-9.-]+", host) or "." not in host:
            raise ValueError()
        if host.endswith((".localhost", ".local", ".internal", ".test", ".invalid")):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError()
        return urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))
    except (ValueError, UnicodeError) as exc:
        raise VenueError(
            "Use a public HTTPS venue website or review-guidelines URL, without credentials or a custom port."
        ) from exc


def site_host(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


async def public_address(host: str) -> str:
    try:
        addresses = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM), 8
        )
    except (OSError, TimeoutError) as exc:
        raise VenueError("The venue website could not be resolved. Check its URL and try again.") from exc
    if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
        raise VenueError("Venue sources must resolve exclusively to public internet addresses.")
    # Prefer IPv4 on machines without an IPv6 route. This exact IP is used for the connection.
    return min(addresses, key=lambda address: address[0] != socket.AF_INET)[4][0]


async def fetch_html(url: str, allowed_host: str) -> tuple[str, str]:
    for _ in range(4):
        url = normalize_url(url)
        if site_host(url) != allowed_host:
            raise VenueError(
                "The venue page redirected to another site. Enter the final official URL directly."
            )
        host = urlsplit(url).hostname
        address = await public_address(host)
        target = httpx.URL(url).copy_with(host=address)
        # A separate client per hop avoids reusing an IP-keyed TLS connection across hostnames.
        try:
            async with (
                httpx.AsyncClient(
                    timeout=httpx.Timeout(12, connect=8), trust_env=False, follow_redirects=False
                ) as client,
                client.stream(
                    "GET",
                    target,
                    headers={
                        "Host": host,
                        "User-Agent": "Folio/1.1 (venue-guidance reader)",
                        "Accept": "text/html,application/xhtml+xml",
                    },
                    extensions={"sni_hostname": host},
                ) as response,
            ):
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise VenueError("The venue website returned an invalid redirect.")
                    url = urljoin(url, location)
                    continue
                if not response.is_success:
                    raise VenueError(
                        f"The venue website returned HTTP {response.status_code}. Try a direct public call-for-papers or reviewer-guidelines page."
                    )
                if response.headers.get("content-type", "").split(";")[0].lower() not in (
                    "text/html",
                    "application/xhtml+xml",
                ):
                    raise VenueError(
                        "Use an HTML venue page, such as its scope, call for papers, or review guidelines."
                    )
                content = bytearray()
                async for block in response.aiter_bytes():
                    content.extend(block)
                    if len(content) > MAX_DOWNLOAD:
                        raise VenueError(
                            "The venue page is too large to read. Use a shorter guidelines page."
                        )
                return url, bytes(content).decode(response.encoding or "utf-8", errors="replace")
        except httpx.HTTPError as exc:
            raise VenueError(
                "The venue website could not be read. Check the URL or try a direct public guidelines page."
            ) from exc
    raise VenueError("The venue website redirected too many times. Enter the final guidelines URL.")


def read_guidance(html: str, url: str, track: str = "") -> tuple[VenueSource, list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True)[:200] if soup.title else "Venue guidance"
    root = soup.select_one("main, article, #main") or soup.body or soup
    for tag in root.select(
        "script, style, nav, footer, header, form, aside, noscript, [hidden], [aria-hidden='true']"
    ):
        tag.decompose()
    candidates = []
    seen = set()
    heading = ""
    category = ""
    track_words = [w for w in re.findall(r"[a-z]+", track.lower()) if len(w) > 3]
    matching_categories = {
        h.get_text(" ", strip=True)
        for h in root.find_all(["h1", "h2"])
        if track_words and any(word in h.get_text(" ", strip=True).lower() for word in track_words)
    }
    for element in root.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        text = re.sub(r"\s+", " ", element.get_text(" ", strip=True))
        if element.name in ("h1", "h2"):
            category = text
        if element.name.startswith("h"):
            heading = text
            continue
        if len(text.split()) < 12 or text in seen:
            continue
        if matching_categories and category not in matching_categories:
            continue
        seen.add(text)
        # Keep the heading with the passage so different tracks' rules remain distinguishable.
        passage = f"{category} / {heading}: {text}" if category != heading else f"{heading}: {text}"
        hits = len(SIGNALS.findall(passage))
        if hits < 2:
            continue
        rank = hits + 4 * len(PRIORITY.findall(heading))
        if track_words and any(word in f"{category} {heading}".lower() for word in track_words):
            rank += 30
        candidates.append((rank, len(candidates), passage))
    selected, used = [], 0
    for _, index, passage in sorted(candidates, key=lambda item: (-item[0], item[1])):
        # Complete phrases, bounded by UTF-8 bytes, with explicit ellipsis on clipping.
        budget = min(1100, SOURCE_BYTES - used)
        if budget < 180:
            break
        encoded = passage.encode("utf-8")
        clipped = passage
        if len(encoded) > budget:
            clipped = encoded[: budget - 4].decode("utf-8", errors="ignore").rsplit(" ", 1)[0] + " …"
        selected.append((index, clipped))
        used += len(clipped.encode("utf-8"))
    passages = [text for _, text in sorted(selected)]
    links = []
    for a in root.find_all("a", href=True):
        target = urljoin(url, a["href"])
        try:
            target = normalize_url(target)
        except VenueError:
            continue
        if site_host(target) != site_host(url) or target == url:
            continue
        description = a.get_text(" ", strip=True) + " " + urlsplit(target).path
        rank = sum(
            weight
            for pattern, weight in [
                (r"review(?:er|ing)?[\s/_-]*(?:guidelines|criteria|instructions)", 10),
                (r"call[\s/_-]*for[\s/_-]*papers|callforpapers", 8),
                (r"aims.{0,8}scope|scope|research.{0,5}topics", 7),
                (r"author[\s/_-]*guidelines", 4),
            ]
            if re.search(pattern, description, re.IGNORECASE)
        )
        if rank:
            # Avoid accidentally grounding a named edition in a linked older year's guidance.
            years = set(re.findall(r"20\d{2}", urlsplit(url).path))
            target_years = set(re.findall(r"20\d{2}", urlsplit(target).path))
            if years and target_years and years.isdisjoint(target_years):
                continue
            links.append((rank, target))
    source = VenueSource(
        url=url,
        title=title,
        retrieved_at=datetime.now(UTC).isoformat(),
        sha256=hashlib.sha256(html.encode("utf-8")).hexdigest(),
        passages=passages,
    )
    return source, list(dict.fromkeys(link for _, link in sorted(links, key=lambda item: -item[0])))


async def load_venue(request: VenueRequest) -> VenueContext:
    website = normalize_url(request.website)
    name, track = request.name.strip(), request.track.strip()
    if len(name) < 2:
        raise VenueError("Enter the venue name, including its year or edition when relevant.")
    sources, warnings = [], []
    try:
        async with asyncio.timeout(35):
            final_url, html = await fetch_html(website, site_host(website))
            first, links = read_guidance(html, final_url, track)
            if first.passages:
                sources.append(first)
            for link in links[: MAX_SOURCES - 1]:
                try:
                    resolved, content = await fetch_html(link, site_host(website))
                    source, _ = read_guidance(content, resolved, track)
                    if source.passages and not any(s.url == source.url for s in sources):
                        sources.append(source)
                except VenueError:
                    warnings.append(f"A linked guidance page could not be read: {link}")
    except TimeoutError as exc:
        raise VenueError(
            "Reading the venue website timed out. Try a direct reviewer-guidelines URL."
        ) from exc
    if not sources or sum(len(p.split()) for source in sources for p in source.passages) < 60:
        raise VenueError(
            "No usable review criteria or research scope were found. Enter a direct call-for-papers, aims-and-scope, or reviewer-guidelines URL."
        )
    warnings.append(
        "Grounding uses selected passages from the supplied site, not an exhaustive policy or submission-compliance check."
    )
    return VenueContext(name=name, website=website, track=track, sources=sources, warnings=warnings)
