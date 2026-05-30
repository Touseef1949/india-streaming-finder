# Streamlit UI for TMDb India OTT Availability (single-file app)
# ---------------------------------------------------------------
# Features
# - Clean, modern UI with sidebar for API keys and options
# - Title + optional year parsing ("Movie 2015" works)
# - Deterministic, no-LLM pipeline (exact-match by title+year → popularity fallback)
# - TMDb search and watch-providers with 30 min caching (configurable)
# - Provider logo grid with monetization badges (flatrate/ads/free/rent/buy)
# - JSON payload output matching your formatter spec
# - Search history for quick back/forward
# - Optional download of results as JSON and requirements.txt
#
# How to run
# 1) pip install -r requirements.txt (or: pip install streamlit requests python-dotenv)
# 2) Put your TMDB v4 Read Access Token (Bearer) in a .env file as TMDB_TOKEN, or paste it in the sidebar.
# 3) streamlit run streamlit_app.py
#
# Notes
# - This UI uses the same TMDb endpoints as your tools. It does not require your LLM/agents to work.
# - If you still want to run through your Agno Team, drop your module import hook where marked (see TODO).

from __future__ import annotations

import os
import re
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests
import streamlit as st
from dotenv import load_dotenv

# ---------------------------------------------------------------
# App setup & constants
# ---------------------------------------------------------------
st.set_page_config(
    page_title="India OTT Availability • TMDb",
    page_icon="🎬",
    layout="wide",
)

load_dotenv()

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG_POSTER_W342 = "https://image.tmdb.org/t/p/w342"
TMDB_IMG_LOGO_W45 = "https://image.tmdb.org/t/p/w45"

# ---------------------------------------------------------------
# Sidebar: API keys, options, help
# ---------------------------------------------------------------
def _clear_cache():
    """Clear Streamlit caches robustly even if functions aren't yet defined this run."""
    try:
        # Clear global cache store (covers all @st.cache_data wrappers)
        st.cache_data.clear()
    except Exception:
        pass
    # Also try per-function clears if they're already defined
    for fn_name in ("tmdb_search_movie", "tmdb_watch_providers", "tmdb_movie_details"):
        fn = globals().get(fn_name)
        try:
            if fn is not None and hasattr(fn, "clear"):
                fn.clear()
        except Exception:
            pass

with st.sidebar:
    st.title("⚙️ Settings")

    # Load TMDb token from Streamlit Cloud secrets first, then .env for local dev
    try:
        default_tmdb = st.secrets["TMDB_TOKEN"]
    except Exception:
        default_tmdb = os.getenv("TMDB_TOKEN", "")

    # Only show API key field for local dev (no secrets available)
    if not default_tmdb:
        tmdb_token = st.text_input(
            "TMDb v4 Read Access Token (Bearer)",
            type="password",
            help="Find this in TMDb settings → API → v4 auth.",
        )
    else:
        # Use secrets securely — never expose in UI
        tmdb_token = default_tmdb
        st.success("🔑 TMDb connected via secure secrets")

    st.session_state.setdefault("cache_ttl", 1800)
    cache_ttl = st.slider("Cache TTL (seconds)", 60, 7200, st.session_state["cache_ttl"], 60)
    st.session_state["cache_ttl"] = cache_ttl

    st.divider()
    st.caption(
        "This tool queries TMDb /search/movie and /movie/{id}/watch/providers and formats the India providers without filtering."
    )

    with st.expander("🧰 Utilities"):
        if st.button("🧹 Clear cached API responses"):
            _clear_cache()  # Will be defined below
            st.success("Cache cleared.")

        # Download helper files
        req_txt = """streamlit>=1.33.0
requests>=2.31.0
python-dotenv>=1.0.1
"""
        st.download_button("⬇️ requirements.txt", req_txt, file_name="requirements.txt")

        env_example = "TMDB_TOKEN=YOUR_V4_BEARER_TOKEN_HERE\n"
        st.download_button("⬇️ .env.example", env_example, file_name=".env.example")

# ---------------------------------------------------------------
# Small CSS for pretty badges & cards
# ---------------------------------------------------------------
st.markdown(
    """
    <style>
    .badge {display:inline-block; padding:2px 8px; border-radius: 999px; font-size: 0.75rem; margin-left:6px;}
    .flatrate {background:#EEF6FF; border:1px solid #BBD6FF;}
    .ads {background:#FFF7E6; border:1px solid #FFD89B;}
    .free {background:#EFFFF2; border:1px solid #B8F0C6;}
    .rent {background:#F4F1FF; border:1px solid #D8D0FF;}
    .buy {background:#FFF0F3; border:1px solid #FFC2CC;}
    /* New grid layout for perfect alignment */
    .prov-grid {display:grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap:12px;}
    .prov-card {border:1px solid #e6e6e6; border-radius:16px; padding:14px;}
    .prov-head {display:flex; gap:8px; align-items:center;}
    .prov-name {font-weight:600;}
    .prov-meta {font-size:12px; color:#666; margin-top:6px;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", t.lower())


def _parse_query(raw: str) -> Tuple[str, Optional[int]]:
    """Parse inputs like "Dilwale 2015" → ("Dilwale", 2015). If explicit year present, return it."""
    raw = raw.strip()
    # Try trailing 4-digit year
    m = re.search(r"(.*?)(?:\(|\s)(\d{4})(?:\))?$", raw)
    if m:
        title = m.group(1).strip().strip('"\'')
        year = m.group(2)
        if year and len(year) == 4:
            try:
                return title, int(year)
            except ValueError:
                pass
    return raw.strip('"\''), None


@st.cache_data(show_spinner=False)
def tmdb_search_movie(title: str, year: Optional[int], region: str, token: str) -> Dict[str, Any]:
    params = {"query": title, "region": region, "include_adult": "false"}
    if year is not None:
        params["year"] = str(year)
    r = requests.get(f"{TMDB_BASE}/search/movie", headers=_headers(token), params=params, timeout=20)
    r.raise_for_status()
    return r.json()


@st.cache_data(show_spinner=False)
def tmdb_watch_providers(movie_id: int, token: str) -> Dict[str, Any]:
    r = requests.get(f"{TMDB_BASE}/movie/{movie_id}/watch/providers", headers=_headers(token), timeout=20)
    r.raise_for_status()
    return r.json()


@st.cache_data(show_spinner=False)
def tmdb_movie_details(movie_id: int, token: str) -> Dict[str, Any]:
    r = requests.get(f"{TMDB_BASE}/movie/{movie_id}", headers=_headers(token), params={"language": "en-IN"}, timeout=20)
    r.raise_for_status()
    return r.json()


def _year_of(date_str: Optional[str]) -> Optional[int]:
    if not date_str:
        return None
    try:
        return int(date_str.split("-")[0])
    except Exception:
        return None


def _select_candidate(query_title: str, query_year: Optional[int], results: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not results:
        return {}
    qn = _norm_title(query_title)

    exacts = []
    for r in results:
        t = r.get("title") or r.get("name") or ""
        rn = _norm_title(t)
        if rn == qn:
            if query_year is None or _year_of(r.get("release_date")) == query_year:
                exacts.append(r)

    if exacts:
        # If multiple exacts, choose by highest popularity
        exacts.sort(key=lambda x: x.get("popularity", 0), reverse=True)
        return exacts[0]

    # Fallback: highest popularity
    results = sorted(results, key=lambda x: x.get("popularity", 0), reverse=True)
    return results[0]


def monetization_label(m: str) -> str:
    mapping = {"flatrate": "available to watch", "ads": "with ads", "free": "free", "rent": "rent", "buy": "buy"}
    return mapping.get(m, m)


def _flatten_in_providers(in_block: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not in_block:
        return []
    buckets = ["flatrate", "ads", "free", "rent", "buy"]
    out = []
    for monetization in buckets:
        for p in in_block.get(monetization, []) or []:
            out.append(
                {
                    "name": p.get("provider_name"),
                    "provider_id": p.get("provider_id"),
                    "monetization": monetization,
                    "logo": f"{TMDB_IMG_LOGO_W45}{p.get('logo_path')}" if p.get("logo_path") else None,
                }
            )
    return out


def build_payload(title: str, year: Optional[int], movie: Dict[str, Any], providers_in: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "query": {"title": title, "year": year},
        "movie": {"id": movie.get("id"), "title": movie.get("title"), "release_date": movie.get("release_date")},
        "found": bool(movie),
        "platforms": providers_in,
    }


def _clear_cache():
    tmdb_search_movie.clear()
    tmdb_watch_providers.clear()
    tmdb_movie_details.clear()


# ---------------------------------------------------------------
# Main UI
# ---------------------------------------------------------------
left, right = st.columns([1, 2])

with left:
    st.title("🎬 India Streaming Availability")
    st.caption("Powered by TMDb — region IN · No filtering · No deep links")

    movie_input = st.text_input("Movie title (you can include a year)", placeholder='e.g., Dilwale 2015 or "Dilwale"')
    col_a, col_b = st.columns(2)
    with col_a:
        manual_year = st.number_input("Year (optional)", min_value=1888, max_value=datetime.now().year + 1, value=None, step=1, format="%d")
    with col_b:
        region = st.selectbox("Region", options=["IN"], index=0, help="This UI focuses on India availability.")

    run_btn = st.button("Find availability", type="primary", use_container_width=True)

    if "history" not in st.session_state:
        st.session_state.history = []  # list of (query, year, payload)

    st.divider()
    if st.session_state.history:
        st.subheader("Recent searches")
        for i, (q, y, payload) in enumerate(reversed(st.session_state.history[-5:]), start=1):
            label = f"{q} ({y})" if y else q
            if st.button(f"↺ {label}", key=f"hist_{i}"):
                movie_input = q
                manual_year = y
                run_btn = True

with right:
    if run_btn:
        if not tmdb_token:
            st.error("TMDb token is required. Add it in the sidebar.")
        else:
            with st.status("Searching TMDb and building payload…", expanded=True) as status:
                st.write("🔎 Parsing input…")
                q_title, q_year_auto = _parse_query(movie_input)
                q_year = manual_year or q_year_auto
                st.write(f"• Title = **{q_title}**, Year = **{q_year or '—'}**")

                try:
                    st.write("📚 TMDb /search/movie…")
                    raw = tmdb_search_movie(q_title, q_year, region, tmdb_token)
                    results = raw.get("results", [])

                    if not results:
                        status.update(state="error")
                        st.error("No results found. Try adjusting the title/year.")
                    else:
                        st.write(f"• {len(results)} candidate(s) found")
                        chosen = _select_candidate(q_title, q_year, results)
                        movie_id = chosen.get("id")
                        st.write(f"✅ Selected TMDb ID **{movie_id}** — {chosen.get('title')} ({_year_of(chosen.get('release_date')) or '—'})")

                        st.write("🧩 Fetching watch providers (IN)…")
                        wp = tmdb_watch_providers(movie_id, tmdb_token)
                        in_block = (wp or {}).get("results", {}).get("IN", {})
                        providers = _flatten_in_providers(in_block)
                        st.write(f"• Providers found: **{len(providers)}**")

                        payload = build_payload(q_title, q_year, chosen, providers)

                        # Optional enrichment: poster
                        poster_url = None
                        try:
                            details = tmdb_movie_details(movie_id, tmdb_token)
                            poster_path = details.get("poster_path")
                            if poster_path:
                                poster_url = f"{TMDB_IMG_POSTER_W342}{poster_path}"
                        except Exception:
                            poster_url = None

                        status.update(label="Done", state="complete")

                        # ---- Result layout ----
                        st.subheader("Result")
                        top_l, top_r = st.columns([1, 2])
                        with top_l:
                            if poster_url:
                                st.image(poster_url, use_container_width=True)
                            st.markdown(
                                f"**{chosen.get('title')}**\n\nRelease: {chosen.get('release_date') or '—'}\n\nTMDb ID: {movie_id}"
                            )
                        with top_r:
                            st.markdown("**Platforms (IN)**")
                            if providers:
                                cards = []
                                for prov in providers:
                                    label = monetization_label(prov["monetization"])
                                    logo_html = f"<img src='{prov['logo']}' width='34'/>" if prov.get("logo") else ""
                                    cards.append(
                                        f"<div class='prov-card'>"
                                        f"<div class='prov-head'>{logo_html}<span class='prov-name'>{prov['name']}</span>"
                                        f"<span class='badge {prov['monetization']}'>{label}</span></div>"
                                        f"<div class='prov-meta'>ID: {prov['provider_id']}</div>"
                                        f"</div>"
                                    )
                                grid_html = "<div class='prov-grid'>" + "".join(cards) + "</div>"
                                st.markdown(grid_html, unsafe_allow_html=True)
                            else:
                                st.info("No India providers listed for this title.")

                        st.divider()
                        st.markdown("**Final JSON payload** (matches your formatter schema)")
                        st.json(payload, expanded=False)

                        st.download_button(
                            "⬇️ Download JSON",
                            data=json.dumps(payload, indent=2),
                            file_name=f"ott_availability_{movie_id}.json",
                            mime="application/json",
                            use_container_width=True,
                        )

                        # Save to history
                        st.session_state.history.append((q_title, q_year, payload))

                except requests.HTTPError as e:
                    status.update(state="error")
                    try:
                        msg = e.response.json()
                    except Exception:
                        msg = {"error": str(e)}
                    st.error(f"TMDb request failed: {msg}")
                except Exception as e:
                    status.update(state="error")
                    st.error(f"Unexpected error: {e}")

    else:
        st.info("Enter a movie title and click **Find availability**.")

# ---------------------------------------------------------------
# (Optional) Agno Team integration (LLM-powered pipeline)
# ---------------------------------------------------------------
# If you want to wire this UI to your existing Agno agents/Team for streaming
# intermediates, you can import your module and trigger the pipeline instead
# of the deterministic path above. Example sketch:
#
# try:
#     import your_module  # defines agent_team etc.
#     HAS_TEAM = True
# except Exception:
#     HAS_TEAM = False
#
# if HAS_TEAM and st.toggle("Use Agno Team (experimental)":
#     prompt = f"""
#     Task: Return India streaming availability for the input movie.
#     Input: "{q_title} {q_year or ''}"
#     """.strip()
#     # Caution: streaming to Streamlit requires custom callbacks;
#     # as a simple approach you can capture final result via a synchronous call
#     # if your library exposes it, or display intermediate prints in a text area.
#
# ---------------------------------------------------------------
# Footer
# ---------------------------------------------------------------
st.caption(
    "Data source: TMDb. This product uses the TMDB API but is not endorsed or certified by TMDB."
)
