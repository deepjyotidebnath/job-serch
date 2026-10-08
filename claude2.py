"""AI Job Finder: single-file version (config + link builders + Streamlit UI).

Still imported from your project (not included here):
    scrapers.source_names, search.run_search, pdf_report.build_pdf
"""
import re
from datetime import datetime
from urllib.parse import quote_plus

import pandas as pd
import streamlit as st

from pdf_report import build_pdf
from scrapers import source_names
from search import run_search

st.set_page_config(page_title="AI Job Finder", page_icon="🎯", layout="wide")

# ============================== CONFIG ==============================
# NOTE: match DEFAULT_ROLES / KINDS / DEFAULT_LOCATION / CACHE_TTL to your old config.py.
# KINDS values must be what your search.py / filters.py expect.
CACHE_TTL = 3600
DEFAULT_LOCATION = "India"
KINDS = ["Fresher", "Internship"]

DEFAULT_ROLES = [
    "AI Engineer", "Machine Learning Engineer", "Data Scientist", "Python Developer",
]
EXTRA_ROLES = [
    "Data Analyst", "GenAI Engineer", "LLM Engineer", "NLP Engineer",
    "Computer Vision Engineer", "Applied AI Engineer",
    "AI Research Intern", "ML Intern", "Data Science Intern",
]

# Sites that only get direct search links (login / anti-bot, so no scraping)
LINK_ONLY_SOURCES = ["Naukri", "Indeed", "Wellfound", "Cutshort",
                     "FresherWorld", "Hirist", "Instahyre"]

# {q} = URL-encoded role. Plain URLs are career homepages.
COMPANY_CAREERS = {
    "Google": "https://www.google.com/about/careers/applications/jobs/results/?q={q}",
    "Microsoft": "https://jobs.careers.microsoft.com/global/en/search?q={q}",
    "Amazon": "https://www.amazon.jobs/en/search?base_query={q}&country=IND",
    "NVIDIA": "https://www.nvidia.com/en-us/about-nvidia/careers/",
    "Adobe": "https://careers.adobe.com/",
    "Qualcomm": "https://www.qualcomm.com/company/careers",
    "Cisco": "https://jobs.cisco.com/",
    "Accenture": "https://www.accenture.com/in-en/careers",
}

# ============================== LINKS ==============================
def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "india"


LINK_BUILDERS = {
    "Naukri":       lambda r, l: f"https://www.naukri.com/{slug(r)}-jobs-in-{slug(l)}?experience=0",
    "Indeed":       lambda r, l: f"https://in.indeed.com/jobs?q={quote_plus(r)}&l={quote_plus(l)}&fromage=14",
    "Wellfound":    lambda r, l: f"https://wellfound.com/role/l/{slug(r)}/{slug(l)}",
    "Cutshort":     lambda r, l: f"https://cutshort.io/jobs/{slug(r)}-jobs",
    "FresherWorld": lambda r, l: f"https://www.freshersworld.com/jobs/jobsearch/{slug(r)}-jobs-in-{slug(l)}",
    "Hirist":       lambda r, l: f"https://www.hirist.tech/k/{slug(r)}-jobs",
    "Instahyre":    lambda r, l: f"https://www.instahyre.com/search-jobs/?search={quote_plus(r)}",
    "LinkedIn":     lambda r, l: f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(r)}&location={quote_plus(l)}",
}


def search_links(role, location, sources):
    """Direct search URL per source. Unknown sources fall back to a Google search."""
    out = {}
    for name in sources:
        builder = LINK_BUILDERS.get(name)
        out[name] = (builder(role, location) if builder else
                     "https://www.google.com/search?q=" + quote_plus(f"{role} {name} jobs {location}"))
    return out


# ============================== SOURCES ==============================
LIVE_SOURCES = list(source_names())
ALL_SOURCES = LIVE_SOURCES + [s for s in LINK_ONLY_SOURCES if s not in LIVE_SOURCES]


# ============================== SEARCH ==============================
@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def cached_search(roles, location, kinds, sources, limit):
    return run_search(roles, location, kinds, sources, limit)


# ============================== UI ==============================
def sidebar():
    """Returns the user's filter choices. Add new widgets here."""
    with st.sidebar:
        st.header("Filters")
        role_options = list(dict.fromkeys(DEFAULT_ROLES + EXTRA_ROLES))
        roles = st.multiselect("Roles", role_options, default=DEFAULT_ROLES[:3])
        custom = st.text_input("Custom keyword (optional)")
        location = st.text_input("Location", DEFAULT_LOCATION)
        kinds = st.multiselect("Type", KINDS, default=KINDS)
        sources = st.multiselect("Sources", ALL_SOURCES, default=ALL_SOURCES,
                                 help="Link-only sources give direct search links, not scraped listings.")
        limit = st.slider("Max results per source per role", 5, 30, 10)
        go = st.button("🔍 Search jobs", type="primary", use_container_width=True)
    if custom.strip() and custom.strip() not in roles:
        roles = roles + [custom.strip()]
    return dict(roles=roles, location=location, kinds=kinds, sources=sources,
                limit=limit, go=go)


def do_search(f):
    live = [s for s in f["sources"] if s in LIVE_SOURCES]
    jobs, status = [], {}
    if live:
        with st.spinner("Searching live sources..."):
            jobs, status = cached_search(tuple(f["roles"]), f["location"],
                                         tuple(f["kinds"]), tuple(live), f["limit"])
    st.session_state["result"] = {
        "jobs": jobs, "status": status, "live": bool(live),
        "meta": {"roles": ", ".join(f["roles"]), "location": f["location"],
                 "kinds": ", ".join(f["kinds"])},
        "links": {r: search_links(r, f["location"], f["sources"]) for r in f["roles"]}}


def show_status(status):
    if not status:  # only link-only sources selected: st.columns(0) would crash
        return
    cols = st.columns(len(status))
    for col, (s, v) in zip(cols, status.items()):
        col.metric(s, v["count"], help=v["error"] or "OK")
    failed = [s for s, v in status.items() if v["error"] and not v["count"]]
    if failed:
        st.warning(f"Could not fetch live listings from: {', '.join(failed)}. "
                   "Use the direct search links below.")


def links_only_download(res):
    st.download_button("📄 Download PDF (search links)",
                       build_pdf([], res["meta"], res["links"]),
                       file_name="job_search_links.pdf", mime="application/pdf")


def show_results(res):
    jobs = res["jobs"]
    if not res.get("live"):
        st.info("Only link-only sources selected. Use the direct search links below.")
        links_only_download(res)
        return
    if not jobs:
        st.error("No live results. The PDF will still contain direct search links.")
        links_only_download(res)
        return
    df = pd.DataFrame(jobs)
    picks = st.multiselect("Show sources", sorted(df["Source"].unique()),
                           default=sorted(df["Source"].unique()))
    text = st.text_input("Filter results by text")
    view = df[df["Source"].isin(picks)]
    if text:
        view = view[view.apply(lambda r: text.lower() in " ".join(map(str, r)).lower(), axis=1)]
    st.dataframe(view, use_container_width=True, hide_index=True,
                 column_config={"Apply Link": st.column_config.LinkColumn("Apply", display_text="Apply ↗")})
    c1, c2 = st.columns(2)
    c1.download_button("📄 Download PDF", build_pdf(view.to_dict("records"), res["meta"], res["links"]),
                       file_name=f"jobs_{datetime.now():%Y%m%d}.pdf", mime="application/pdf",
                       use_container_width=True)
    c2.download_button("📊 Download CSV", view.to_csv(index=False).encode(), file_name="jobs.csv",
                       mime="text/csv", use_container_width=True)


def show_links(res):
    with st.expander("🔗 Direct search links", expanded=not res.get("live")):
        for role, ls in res["links"].items():
            st.markdown(f"**{role}**")
            st.markdown(" · ".join(f"[{n}]({u})" for n, u in ls.items()))
    with st.expander("🏢 Company career pages"):
        role = next(iter(res["links"]), "")
        q = quote_plus(role)
        st.markdown(" · ".join(f"[{n}]({u.format(q=q)})" for n, u in COMPANY_CAREERS.items()))


def main():
    st.title("🎯 AI Job Finder")
    st.caption("Freshers & internships only: AI / ML / Data Science / Python.")
    f = sidebar()
    if f["go"]:
        if f["roles"] and f["kinds"] and f["sources"]:
            do_search(f)
        else:
            st.warning("Pick at least one role, type and source.")
    res = st.session_state.get("result")
    if not res:
        st.info("Choose your filters in the sidebar and click **Search jobs**.")
        return
    show_status(res["status"])
    show_results(res)
    show_links(res)


main()