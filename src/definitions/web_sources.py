"""Free-only, source-aware optional web context retrieval.

This module deliberately avoids paid/API-key based search providers. It can use
cached sources and direct no-key HTTP fetches for known/allowlisted official URLs,
but failures simply return no web context so local documentation remains usable.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote_plus, urljoin, urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "web_sources.yaml"
SEED_URLS_PATH = PROJECT_ROOT / "config" / "official_web_seed_urls.yaml"
CACHE_DIR = PROJECT_ROOT / "data" / "web_cache"
WEB_MODE_DEFAULT = "fallback"
WEB_MODES = {"off", "fallback", "enhance", "force"}
OFFICIAL_WEB_ONLY_DEFAULT = True
ALLOW_EXTERNAL_WEB_DEFAULT = False
ALLOW_PAID_APIS = False
ALLOW_API_KEY_BASED_SEARCH = False

SOURCE_TIERS = [
    "official_documentation",
    "official_supplemental",
    "official_web",
    "external_web",
    "manual_knowledge",
    "llm_inference",
]

DEFAULT_CONFIG = {
    "allow_paid_apis": ALLOW_PAID_APIS,
    "allow_api_key_based_search": ALLOW_API_KEY_BASED_SEARCH,
    "provider": "free_only",
    "web_mode_default": WEB_MODE_DEFAULT,
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
        import requests  # ± 290 ms importtijd; alleen nodig als er echt gefetcht wordt

        response = requests.get(url, timeout=10, headers={"User-Agent": "VU-EA-Conversational-AI/free-only"})
        # Keep status code in metadata; HTTP errors are classified later and not used as evidence.
        response.raise_for_status()
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", response.text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        title_match = re.search(r"<title[^>]*>(.*?)</title>", response.text, flags=re.I | re.S)
        title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else url
        return {"title": title, "url": url, "snippet": text[:300], "text": text, "status_code": response.status_code}


def _provider(provider: WebProvider | None = None) -> WebProvider:
    p = provider or FreeOnlyProvider()
    if p.requires_api_key or p.is_paid_or_usage_based:
        raise ValueError("Betaalde/API-key gebaseerde webproviders zijn uitgeschakeld in gratis-only modus.")
    return p


def _cache_path(url: str) -> Path:
    return CACHE_DIR / (hashlib.sha256(url.encode()).hexdigest() + ".json")


def extract_pdf_text(content: bytes) -> str:
    """Return the text of a PDF, or "" when extraction is not possible.

    ``pypdf`` is optional and pulls in native dependencies (cryptography/cffi)
    that can be broken in a given Python environment. Such an import can raise a
    non-``Exception`` error from native code, which would otherwise escape every
    caller and break an answer that does not even need the PDF, so the catch is
    deliberately wide.
    """
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:  # noqa: BLE001 - see docstring: native import failures.
        return ""


def fetch_web_candidate(candidate: dict[str, Any], provider: WebProvider | None = None) -> dict[str, Any] | None:
    url = str(candidate.get("url") or "")
    if not url:
        return None
    if url.lower().endswith(".pdf"):
        if provider is not None:
            try:
                return {**candidate, **_provider(provider).fetch(url)}
            except Exception:
                return None
        try:
            import requests

            response = requests.get(url, timeout=15, headers={"User-Agent": "VU-EA-Conversational-AI/free-only"})
        except Exception:
            return None
        if response.status_code >= 400:
            return {**candidate, "status_code": response.status_code, "text": "", "content_type": response.headers.get("content-type", "application/pdf")}
        text = extract_pdf_text(response.content)
        return {**candidate, "status_code": response.status_code, "content_type": response.headers.get("content-type", "application/pdf"), "text": text, "snippet": text[:300], "title": candidate.get("title") or url}
    try:
        raw = _provider(provider).fetch(url)
    except Exception:
        return None
    return {**candidate, **raw}


def fetch_web_source(url: str, provider: WebProvider | None = None) -> dict[str, Any] | None:
    cfg = load_web_config(); CACHE_DIR.mkdir(parents=True, exist_ok=True); path = _cache_path(url)
    if cfg.get("cache_enabled", True) and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    raw = fetch_web_candidate({"url": url}, provider=provider)
    if raw is None:
        return None
    text = str(raw.get("text") or raw.get("snippet") or "")
    meta = {"source_tier": source_tier_for_url(url, cfg["official_web_domains"]), "title": raw.get("title") or url, "url": url, "domain": domain_from_url(url), "retrieved_at": datetime.now(timezone.utc).isoformat(), "status_code": raw.get("status_code"), "content_type": raw.get("content_type"), "snippet": raw.get("snippet", ""), "text_excerpt": text[:1000], "content_hash": hashlib.sha256(text.encode()).hexdigest(), "relevance_score": 0.0, "used_for_answer": True}
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
        item = dict(s); item["relevance_score"] = max(float(item.get("relevance_score", 0) or 0), float(score)); ranked.append(item)
    return sorted(ranked, key=lambda s: (s.get("source_tier") == "official_web", s.get("relevance_score", 0)), reverse=True)


def parse_seed_urls(path: Path = SEED_URLS_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    seeds: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    list_key: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "official_seed_urls:":
            continue
        if stripped.startswith("- id:"):
            if current:
                seeds.append(current)
            current = {"id": stripped.split(":", 1)[1].strip().strip('"\''), "topics": [], "related_fields": []}
            list_key = None
            continue
        if current is None:
            continue
        if stripped in {"topics:", "related_fields:"}:
            list_key = stripped[:-1]
            current.setdefault(list_key, [])
            continue
        if stripped.startswith("-") and list_key:
            current[list_key].append(stripped[1:].strip().strip('"\''))
            continue
        if ":" in stripped:
            key, value = [part.strip() for part in stripped.split(":", 1)]
            if value.lower() in {"true", "false"}:
                current[key] = value.lower() == "true"
            else:
                current[key] = value.strip('"\'')
            list_key = None
    if current:
        seeds.append(current)
    return [seed for seed in seeds if seed.get("enabled", True)]


def expanded_search_queries(query: str, matched_fields: list[dict[str, Any]] | None = None, matched_terms: list[str] | None = None) -> list[str]:
    terms = [str(term) for term in (matched_terms or []) if str(term).strip()]
    fields = [str(field.get("field_name", "")) for field in (matched_fields or []) if field.get("field_name")]
    qn = normalize_for_relevance(query)
    queries = [query]
    if "onechte neveninschrijving" in qn:
        queries.extend([
            '"onechte neveninschrijving"',
            '"onechte neveninschrijving" "Soort inschrijving ho"',
            '"onechte neveninschrijving" "dubbeltellingen"',
            '"onechte neveninschrijving" "beslisboom"',
            '"Soort inschrijving ho" "onechte neveninschrijving"',
            '"Toelichting op de gegevens die DUO levert" "onechte neveninschrijving"',
            'site:duo.nl "onechte neveninschrijving"',
            'site:duo.nl/zakelijk/images "onechte neveninschrijving" filetype:pdf',
            'site:onderwijsdata.duo.nl "Soort inschrijving ho"',
            'site:cbs.nl "neveninschrijving" "hoger onderwijs"',
        ])
    for value in terms + fields:
        if value:
            queries.append(f'"{value}"')
    unique = []
    seen = set()
    for value in queries:
        if value not in seen:
            seen.add(value); unique.append(value)
    return unique[:10]


def seed_matches_query(seed: dict[str, Any], query: str, matched_fields: list[dict[str, Any]] | None = None, matched_terms: list[str] | None = None) -> bool:
    haystack = normalize_for_relevance(" ".join([query, " ".join(matched_terms or []), " ".join(str(f.get("field_name", "")) for f in (matched_fields or []))]))
    for value in seed.get("topics", []) + seed.get("related_fields", []):
        norm = normalize_for_relevance(value)
        if norm and (norm in haystack or any(token in haystack for token in norm.split() if len(token) > 5)):
            return True
    return False


def discover_web_candidates(query: str, matched_fields: list[dict[str, Any]] | None = None, matched_terms: list[str] | None = None, web_mode: str = WEB_MODE_DEFAULT, provider: WebProvider | None = None) -> dict[str, Any]:
    strategies = ["seed_urls", "query_expansion", "official_site_search", "sitemap"]
    candidates: list[dict[str, Any]] = []
    for seed in parse_seed_urls():
        if seed_matches_query(seed, query, matched_fields, matched_terms):
            candidates.append({**seed, "discovery_strategy": "seed_urls", "candidate_source": "seed_urls"})
    expanded = expanded_search_queries(query, matched_fields, matched_terms)
    try:
        for expanded_query in expanded[:3]:
            for result in search_web_context(expanded_query, allowed_domains=load_web_config()["official_web_domains"], max_results=3, provider=provider):
                candidates.append({**result, "discovery_strategy": "official_site_search", "candidate_source": "search_page"})
    except Exception:
        pass
    # Lightweight sitemap strategy: add known sitemap URLs as rejected/diagnostic candidates only; no broad crawl.
    for url in ["https://duo.nl/sitemap.xml", "https://www.duo.nl/sitemap.xml", "https://onderwijsdata.duo.nl/sitemap.xml"]:
        candidates.append({"title": "Sitemap", "url": url, "domain": domain_from_url(url), "source_tier": source_tier_for_url(url), "discovery_strategy": "sitemap", "candidate_source": "sitemap", "used_for_answer": False})
    deduped = []
    seen = set()
    for candidate in candidates:
        url = candidate.get("url")
        if url and url not in seen:
            seen.add(url); deduped.append(candidate)
    return {"candidates": deduped, "strategies": strategies, "expanded_queries": expanded}


SEARCH_URL_PATTERNS = ("/search?", "/zoeken?", "?q=", "/search/", "/zoek")
NOT_FOUND_TERMS = ("pagina niet gevonden", "sorry, deze pagina bestaat niet", "page not found", "not found")
SEARCH_TITLES = ("zoeken", "search")
MIN_CONTENT_CHARS = 120
RELEVANCE_THRESHOLD = 0.55


def is_search_page(url: str, title: str = "", text: str = "") -> bool:
    url_l = str(url or "").lower()
    title_l = str(title or "").strip().lower()
    if any(pattern in url_l for pattern in SEARCH_URL_PATTERNS):
        return True
    if title_l in SEARCH_TITLES or title_l.startswith("zoeken ") or title_l.startswith("search "):
        return True
    if "cbs statline" in title_l and not is_relevant_web_source("", text, matched_terms=["onechte neveninschrijving", "neveninschrijving"]):
        return True
    return False


def is_404_or_error_page(status_code: int | None = None, title: str = "", text: str = "") -> bool:
    if status_code is not None and int(status_code) >= 400:
        return True
    haystack = f"{title} {text}".lower()
    return "404" in str(title).lower() or any(term in haystack for term in NOT_FOUND_TERMS)


def is_low_content_page(text: str) -> bool:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    return len(clean) < MIN_CONTENT_CHARS


def is_relevant_web_source(query: str, text: str, matched_terms: list[str] | None = None, matched_fields: list[dict[str, Any]] | None = None) -> bool:
    haystack = normalize_for_relevance(text)
    if not haystack:
        return False
    phrases = [normalize_for_relevance(term) for term in (matched_terms or []) if normalize_for_relevance(term)]
    fields = [normalize_for_relevance(field.get("field_name", "")) for field in (matched_fields or [])]
    phrases.extend(field for field in fields if field)
    query_norm = normalize_for_relevance(query)
    if query_norm:
        phrases.append(query_norm)
    if any(phrase and phrase in haystack for phrase in phrases):
        return True
    query_tokens = {token for token in re.findall(r"\w+", query_norm) if len(token) > 3}
    domain_terms = {"onechte", "neveninschrijving", "neveninschrijvingen", "opleiding", "instelling", "opleiding instelling", "inschrijving", "student"}
    relevant_tokens = query_tokens | domain_terms
    hits = {token for token in relevant_tokens if token in haystack}
    return len(hits) >= 3 and ("neveninschrijving" in hits or "neveninschrijvingen" in hits or "inschrijving" in hits)


def normalize_for_relevance(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", str(value or "").lower())).strip()


def score_web_relevance(query: str, text: str, matched_fields: list[dict[str, Any]] | None = None, matched_terms: list[str] | None = None) -> tuple[float, list[str]]:
    haystack = normalize_for_relevance(text)
    weighted_terms: list[tuple[str, float]] = []
    qn = normalize_for_relevance(query)
    if qn:
        weighted_terms.append((qn, 0.35))
    for term in matched_terms or []:
        weighted_terms.append((normalize_for_relevance(term), 0.18))
    for field in matched_fields or []:
        weighted_terms.append((normalize_for_relevance(field.get("field_name", "")), 0.14))
    if "onechte neveninschrijving" in qn or "neveninschrijving" in qn:
        weighted_terms.extend([
            ("onechte neveninschrijving", 0.35),
            ("neveninschrijving", 0.18),
            ("soort inschrijving ho", 0.16),
            ("soort inschrijving soort ho", 0.12),
            ("dubbeltellingen", 0.12),
            ("beslisboom", 0.1),
            ("rekenregel", 0.1),
            ("inschrijving", 0.08),
            ("hoger onderwijs", 0.08),
        ])
    score = 0.0
    matched: list[str] = []
    seen = set()
    for term, weight in weighted_terms:
        if term and term not in seen and term in haystack:
            seen.add(term); matched.append(term); score += weight
    return min(score, 1.0), matched


def build_relevant_excerpt(text: str, query: str, matched_terms: list[str] | None = None, matched_fields: list[dict[str, Any]] | None = None, max_chars: int = 700) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return ""
    priority_terms = [
        "onechte neveninschrijving",
        "echte neveninschrijving",
        "hoofdinschrijving",
        "Soort inschrijving ho",
        "Soort inschrijving soort ho",
        "dubbeltellingen",
        "beslisboom",
        "rekenregel",
    ]
    dynamic_terms = [str(term) for term in (matched_terms or []) if str(term).strip()]
    dynamic_terms.extend(str(field.get("field_name", "")) for field in (matched_fields or []) if field.get("field_name"))
    query_norm = normalize_for_relevance(query)
    if "onechte neveninschrijving" in query_norm:
        dynamic_terms.extend(priority_terms)
    query_tokens = [token for token in re.findall(r"\w+", query_norm) if len(token) > 4]
    terms = []
    seen = set()
    for term in dynamic_terms + query_tokens:
        norm = normalize_for_relevance(term)
        if norm and norm not in seen:
            seen.add(norm); terms.append(term)
    clean_norm = normalize_for_relevance(clean)
    best_pos = None
    best_len = 0
    for term in terms:
        norm = normalize_for_relevance(term)
        pos = clean_norm.find(norm)
        if pos >= 0:
            # Map approximately back to original text by searching case-insensitively for the raw term.
            raw_match = re.search(re.escape(str(term)), clean, flags=re.I)
            best_pos = raw_match.start() if raw_match else min(pos, len(clean))
            best_len = len(str(term))
            break
    if best_pos is None:
        return clean[:max_chars]
    start = max(0, best_pos - max_chars // 3)
    end = min(len(clean), start + max_chars)
    if end - start < max_chars:
        start = max(0, end - max_chars)
    excerpt = clean[start:end].strip()
    if start > 0:
        excerpt = "…" + excerpt
    if end < len(clean):
        excerpt += "…"
    return excerpt


def clean_web_excerpt(text: str) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return ""
    # PDF table extraction can prepend unrelated cells before the field label;
    # keep the excerpt anchored on the evidence-bearing field label when present.
    field_anchor = re.search(r"\bVeldnaam\s+Soort\s+inschrijving\s+ho\b", clean, flags=re.I)
    if field_anchor:
        clean = clean[field_anchor.start():]
    clean = re.sub(r"\bBeschrijving\b", "Beschrijving:", clean, count=1, flags=re.I)
    clean = re.sub(r"\bRekenregel\b", "Rekenregel:", clean, count=1, flags=re.I)
    clean = re.sub(r"\bAfgeleid door DUO IP\s+Ja\b", "Afgeleid door DUO IP.", clean, flags=re.I)
    clean = re.sub(r"\bAfgeleid door DUO IP\b", "Afgeleid door DUO IP.", clean, count=1, flags=re.I)
    clean = re.sub(r"\s+([.,;:])", r"\1", clean)
    clean = re.sub(r"\bAfgeleid door DUO IP\.\s*\.", "Afgeleid door DUO IP.", clean, flags=re.I)
    clean = re.sub(r"([.:])(?=\S)", r"\1 ", clean)
    clean = re.sub(r"\bo\.\s*b\.?\s*v\.?", "o.b.v.", clean, flags=re.I)
    clean = re.sub(r"dubbel\s+tellingen", "dubbeltellingen", clean, flags=re.I)
    clean = re.sub(r"\bdomein ho\b", "domein HO", clean, flags=re.I)
    clean = re.sub(r"\bvan ho\b", "van HO", clean, flags=re.I)
    clean = re.sub(r"\s+", " ", clean).strip(" .")
    if len(clean) > 700:
        boundary = max(clean.rfind(". ", 0, 700), clean.rfind(") ", 0, 700))
        clean = clean[:boundary + 1 if boundary > 250 else 700].rstrip()
    if clean and clean[-1] not in ".!?…":
        clean += "…"
    return clean


def accept_or_reject_web_candidate(candidate: dict[str, Any], query: str, *, matched_terms: list[str] | None = None, matched_fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return classify_web_candidate(candidate, query, matched_terms=matched_terms, matched_fields=matched_fields)


def classify_web_candidate(candidate: dict[str, Any], query: str, *, matched_terms: list[str] | None = None, matched_fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    url = str(candidate.get("url") or "")
    title = str(candidate.get("title") or "")
    text = str(candidate.get("text") or candidate.get("text_excerpt") or candidate.get("snippet") or "")
    status_code = candidate.get("status_code")
    classified = dict(candidate)
    classified.setdefault("domain", domain_from_url(url))
    classified.setdefault("source_tier", source_tier_for_url(url))
    classified["accepted"] = False
    if is_404_or_error_page(status_code, title, text):
        classified["reject_reason"] = "not_found"
    elif is_search_page(url, title, text):
        classified["reject_reason"] = "search_page"
    elif is_low_content_page(text):
        classified["reject_reason"] = "low_content"
    else:
        score, matched = score_web_relevance(query, text, matched_fields=matched_fields, matched_terms=matched_terms)
        if classified.get("discovery_strategy") == "seed_urls" and ("toelichting op de gegevens die duo levert" in normalize_for_relevance(classified.get("title")) or "duo levert" in normalize_for_relevance(classified.get("url"))):
            score = min(1.0, score + 0.35)
            if "duo seed url" not in matched:
                matched.append("duo seed url")
        classified["relevance_score"] = score
        classified["matched_terms"] = matched
        if score < RELEVANCE_THRESHOLD or not is_relevant_web_source(query, text, matched_terms=matched_terms, matched_fields=matched_fields):
            classified["reject_reason"] = "not_relevant"
        else:
            classified["accepted"] = True
            classified["reject_reason"] = None
            classified["used_for_answer"] = True
    return classified


def build_web_context_with_candidates(query: str, matched_fields: list[dict[str, Any]] | None = None, matched_terms: list[str] | None = None, *, allow_external_web: bool = False, provider: WebProvider | None = None) -> dict[str, Any]:
    cfg = load_web_config(); allowed = cfg["official_web_domains"]; max_results = int(cfg.get("max_results", 5))
    discovery = discover_web_candidates(query, matched_fields=matched_fields, matched_terms=matched_terms, provider=provider)
    results = discovery["candidates"]
    candidates = []
    accepted = []
    for result in results[: max_results * 3]:
        url = result.get("url", "")
        pre = classify_web_candidate({**result, "domain": domain_from_url(url), "source_tier": source_tier_for_url(url, allowed)}, query, matched_terms=matched_terms, matched_fields=matched_fields)
        if not pre["accepted"] and pre.get("reject_reason") == "search_page":
            candidates.append(pre)
            continue
        raw = fetch_web_candidate(result, provider=provider)
        if not raw:
            failed = {**result, "url": url, "domain": domain_from_url(url), "source_tier": source_tier_for_url(url, allowed), "accepted": False, "reject_reason": "fetch_failed", "used_for_answer": False}
            candidates.append(failed)
            continue
        text = str(raw.get("text") or raw.get("snippet") or "")
        meta = {**raw, "source_tier": source_tier_for_url(url, allowed), "title": raw.get("title") or result.get("title") or url, "url": url, "domain": domain_from_url(url), "retrieved_at": datetime.now(timezone.utc).isoformat(), "snippet": raw.get("snippet", ""), "text_excerpt": text[:1000], "content_hash": hashlib.sha256(text.encode()).hexdigest(), "used_for_answer": True}
        classified = classify_web_candidate(meta, query, matched_terms=matched_terms, matched_fields=matched_fields)
        if classified["source_tier"] == "external_web" and not allow_external_web:
            classified["accepted"] = False
            classified["reject_reason"] = "external_web_disabled"
        if classified.get("accepted"):
            excerpt = clean_web_excerpt(build_relevant_excerpt(text, query, matched_terms=classified.get("matched_terms") or matched_terms, matched_fields=matched_fields))
            classified["text_excerpt"] = excerpt
            classified["evidence_excerpt"] = excerpt
        classified.pop("text", None)
        candidates.append(classified)
        if classified.get("accepted"):
            accepted.append(classified)
    context = rank_web_sources(query, accepted)[:max_results]
    rejected = [c for c in candidates if not c.get("accepted")]
    return {"web_context": context, "web_candidates": candidates, "rejected_web_candidates": rejected, "web_discovery_strategies_used": discovery.get("strategies", []), "web_search_queries": discovery.get("expanded_queries", [])}


def build_web_context(query: str, matched_fields: list[dict[str, Any]] | None = None, matched_terms: list[str] | None = None, *, allow_external_web: bool = False, provider: WebProvider | None = None) -> list[dict[str, Any]]:
    return build_web_context_with_candidates(query, matched_fields=matched_fields, matched_terms=matched_terms, allow_external_web=allow_external_web, provider=provider)["web_context"]
