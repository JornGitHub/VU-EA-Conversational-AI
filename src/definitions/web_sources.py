"""Free-only, source-aware optional web context retrieval.

This module deliberately avoids paid/API-key based search providers. It can use
cached sources and direct no-key HTTP fetches for known/allowlisted official URLs,
but failures simply return no web context so local documentation remains usable.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote_plus, urlparse

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "web_sources.yaml"
CACHE_DIR = PROJECT_ROOT / "data" / "web_cache"

SOURCE_TIERS = [
    "official_documentation",
    "official_supplemental",
    "official_web",
    "external_web",
    "manual_knowledge",
    "llm_inference",
]

DEFAULT_CONFIG = {
    "allow_paid_apis": False,
    "allow_api_key_based_search": False,
    "provider": "free_only",
    "official_web_only": True,
    "external_web_enabled": False,
    "max_results": 5,
    "cache_enabled": True,
    "official_web_domains": [
        "cbs.nl",
        "opendata.cbs.nl",
        "duo.nl",
        "onderwijsdata.duo.nl",
        "rijksoverheid.nl",
        "ocwincijfers.nl",
        "universiteitenvannederland.nl",
    ],
}


def _simple_yaml_config(text: str) -> dict[str, Any]:
    current = DEFAULT_CONFIG.copy(); in_ws = False; list_key = None
    current["official_web_domains"] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "web_sources:":
            in_ws = True; continue
        if not in_ws:
            continue
        if stripped.endswith(":"):
            list_key = stripped[:-1]; current[list_key] = []; continue
        if stripped.startswith("-") and list_key:
            current[list_key].append(stripped[1:].strip().strip('"\'')); continue
        if ":" in stripped:
            key, value = [p.strip() for p in stripped.split(":", 1)]
            list_key = None
            if value.lower() in {"true", "false"}:
                current[key] = value.lower() == "true"
            elif value.isdigit():
                current[key] = int(value)
            else:
                current[key] = value.strip('"\'')
    if not current.get("official_web_domains"):
        current["official_web_domains"] = DEFAULT_CONFIG["official_web_domains"]
    return current


def load_web_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    if not path.exists():
        return DEFAULT_CONFIG.copy()
    return _simple_yaml_config(path.read_text(encoding="utf-8"))


def domain_from_url(url: str) -> str:
    return (urlparse(url).netloc or "").lower().removeprefix("www.")


def is_official_domain(domain: str, allowed_domains: list[str] | None = None) -> bool:
    allowed = [d.lower().removeprefix("www.") for d in (allowed_domains or load_web_config()["official_web_domains"])]
    domain = domain.lower().removeprefix("www.")
    return any(domain == d or domain.endswith("." + d) for d in allowed)


def source_tier_for_url(url: str, allowed_domains: list[str] | None = None) -> str:
    return "official_web" if is_official_domain(domain_from_url(url), allowed_domains) else "external_web"


class WebProvider(Protocol):
    name: str
    requires_api_key: bool
    is_paid_or_usage_based: bool
    def search(self, query: str, *, allowed_domains: list[str] | None, max_results: int) -> list[dict[str, Any]]: ...
    def fetch(self, url: str) -> dict[str, Any]: ...


@dataclass
class FreeOnlyProvider:
    name: str = "free_only"
    requires_api_key: bool = False
    is_paid_or_usage_based: bool = False

    def search(self, query: str, *, allowed_domains: list[str] | None, max_results: int) -> list[dict[str, Any]]:
        # No paid search API: use deterministic official search URLs as fetchable hints.
        domains = allowed_domains or load_web_config()["official_web_domains"]
        return [{"title": f"Zoekresultaten {domain}", "url": f"https://{domain}/search?q={quote_plus(query)}", "snippet": "Gratis/no-key officiële zoekpagina; inhoud wordt alleen gebruikt als ophalen lukt."} for domain in domains[:max_results]]

    def fetch(self, url: str) -> dict[str, Any]:
        response = requests.get(url, timeout=10, headers={"User-Agent": "VU-EA-Conversational-AI/free-only"})
        response.raise_for_status()
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", response.text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        title_match = re.search(r"<title[^>]*>(.*?)</title>", response.text, flags=re.I | re.S)
        title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else url
        return {"title": title, "url": url, "snippet": text[:300], "text": text}


def _provider(provider: WebProvider | None = None) -> WebProvider:
    p = provider or FreeOnlyProvider()
    if p.requires_api_key or p.is_paid_or_usage_based:
        raise ValueError("Betaalde/API-key gebaseerde webproviders zijn uitgeschakeld in gratis-only modus.")
    return p


def _cache_path(url: str) -> Path:
    return CACHE_DIR / (hashlib.sha256(url.encode()).hexdigest() + ".json")


def fetch_web_source(url: str, provider: WebProvider | None = None) -> dict[str, Any] | None:
    cfg = load_web_config(); CACHE_DIR.mkdir(parents=True, exist_ok=True); path = _cache_path(url)
    if cfg.get("cache_enabled", True) and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        raw = _provider(provider).fetch(url)
    except Exception:
        return None
    text = str(raw.get("text") or raw.get("snippet") or "")
    meta = {"source_tier": source_tier_for_url(url, cfg["official_web_domains"]), "title": raw.get("title") or url, "url": url, "domain": domain_from_url(url), "retrieved_at": datetime.now(timezone.utc).isoformat(), "snippet": raw.get("snippet", ""), "text_excerpt": text[:1000], "content_hash": hashlib.sha256(text.encode()).hexdigest(), "relevance_score": 0.0, "used_for_answer": True}
    if cfg.get("cache_enabled", True):
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def search_web_context(query: str, *, allowed_domains: list[str] | None = None, max_results: int = 5, provider: WebProvider | None = None) -> list[dict[str, Any]]:
    return _provider(provider).search(_safe_query(query), allowed_domains=allowed_domains, max_results=max_results)


def _safe_query(query: str) -> str:
    # Only compact user query/search terms; no local documents or project data.
    return " ".join(str(query).split())[:160]


def rank_web_sources(query: str, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tokens = set(re.findall(r"\w+", query.lower()))
    ranked = []
    for s in sources:
        hay = f"{s.get('title','')} {s.get('snippet','')} {s.get('text_excerpt','')}".lower()
        score = sum(1 for t in tokens if t in hay) / max(len(tokens), 1)
        item = dict(s); item["relevance_score"] = float(score); ranked.append(item)
    return sorted(ranked, key=lambda s: (s.get("source_tier") == "official_web", s.get("relevance_score", 0)), reverse=True)


def build_web_context(query: str, matched_fields: list[dict[str, Any]] | None = None, matched_terms: list[str] | None = None, *, allow_external_web: bool = False, provider: WebProvider | None = None) -> list[dict[str, Any]]:
    cfg = load_web_config(); allowed = cfg["official_web_domains"]; max_results = int(cfg.get("max_results", 5))
    results = search_web_context(query, allowed_domains=allowed, max_results=max_results, provider=provider)
    fetched = []
    for result in results:
        meta = fetch_web_source(result.get("url", ""), provider=provider)
        if not meta:
            continue
        if meta["source_tier"] == "external_web" and not allow_external_web:
            continue
        fetched.append(meta)
    return rank_web_sources(query, fetched)[:max_results]
