"""
AI Job Finder - fresher jobs & internships (AI / ML / Data Science / Python)
Sources: LinkedIn, Internshala, Unstop, Amazon, Google, Microsoft
Output : interactive table + CSV + PDF with clickable apply links

Run:  pip install -r requirements.txt
      streamlit run app.py
"""
import io
import re
import urllib.parse as up
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from xml.sax.saxutils import escape

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = 15
SOURCES = ["LinkedIn", "Internshala", "Unstop", "Amazon", "Google", "Microsoft"]
DEFAULT_ROLES = ["Machine Learning", "Artificial Intelligence", "Data Science",
                 "Python Developer"]
# Titles that are clearly not for freshers
SENIOR = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|manager|director|head of|architect|"
    r"vp|distinguished|fellow|specialist ii|iii|iv)\b", re.I)


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def make_job(title, company, location, source, url, kind="", posted=""):
    return {"Title": " ".join(str(title).split()), "Company": company or "-",
            "Location": location or "-", "Source": source, "Type": kind,
            "Posted": posted, "Apply Link": url}


def get(url, **kw):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r


# --------------------------------------------------------------------------
# Scrapers  (each: fn(query, location, kinds, limit) -> list[dict])
# kinds is a set containing "Internship" and/or "Full-time"
# --------------------------------------------------------------------------
def scrape_linkedin(q, loc, kinds, limit):
    levels = []
    if "Internship" in kinds:
        levels.append("1")
    if "Full-time" in kinds:
        levels.append("2")  # entry level
    r = get("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search",
            params={"keywords": q, "location": loc, "f_E": ",".join(levels),
                    "f_TPR": "r2592000", "start": 0})
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for card in soup.select("li"):
        a = card.select_one("a.base-card__full-link")
        t = card.select_one(".base-search-card__title")
        if not (a and t):
            continue
        c = card.select_one(".base-search-card__subtitle")
        l = card.select_one(".job-search-card__location")
        d = card.select_one("time")
        out.append(make_job(t.text, c.text.strip() if c else "",
                            l.text.strip() if l else "", "LinkedIn",
                            a["href"].split("?")[0],
                            posted=d.get("datetime", "") if d else ""))
        if len(out) >= limit:
            break
    return out


def scrape_internshala(q, loc, kinds, limit):
    slug = slugify(q)
    pages = []
    if "Internship" in kinds:
        pages.append(("Internship", f"https://internshala.com/internships/keywords-{slug}/"))
    if "Full-time" in kinds:
        pages.append(("Full-time", f"https://internshala.com/jobs/keywords-{slug}/"))
    out = []
    for kind, url in pages:
        soup = BeautifulSoup(get(url).text, "html.parser")
        for card in soup.select("div.individual_internship"):
            t = card.select_one(".job-internship-name, .profile, h3")
            c = card.select_one(".company-name, .company_name")
            l = card.select_one(".locations, .location_link, #location_names")
            href = card.get("data-href")
            if not href:
                a = card.select_one("a[href*='/detail/']")
                href = a["href"] if a else None
            if not (t and href):
                continue
            out.append(make_job(t.text, c.text.strip() if c else "",
                                l.text.strip() if l else "", "Internshala",
                                up.urljoin("https://internshala.com", href), kind))
            if len(out) >= limit:
                break
    return out


def scrape_unstop(q, loc, kinds, limit):
    out = []
    for opp, kind in (("jobs", "Full-time"), ("internships", "Internship")):
        if kind not in kinds:
            continue
        r = get("https://unstop.com/api/public/opportunity/search-result",
                params={"opportunity": opp, "per_page": limit,
                        "oppstatus": "open", "searchTerm": q})
        items = (r.json().get("data") or {}).get("data") or []
        for it in items:
            url = it.get("public_url") or it.get("seo_url")
            if not url:
                continue
            if not url.startswith("http"):
                url = "https://unstop.com/" + url.lstrip("/")
            org = (it.get("organisation") or {}).get("name", "")
            locs = (it.get("job_detail") or {}).get("locations") or it.get("region") or ""
            if isinstance(locs, list):
                locs = ", ".join(str(x) for x in locs[:3])
            out.append(make_job(it.get("title", ""), org, locs, "Unstop", url, kind))
    return out[:limit]


def india_only(loc):
    return "india" in loc.lower()


def scrape_amazon(q, loc, kinds, limit):
    queries = []
    if "Internship" in kinds:
        queries.append((q + " intern", "Internship"))
    if "Full-time" in kinds:
        queries.append((q, "Full-time"))
    out = []
    for query, kind in queries:
        params = {"base_query": query, "loc_query": loc, "result_limit": limit,
                  "sort": "recent", "offset": 0}
        if india_only(loc):
            params["country"] = "IND"
        jobs = get("https://www.amazon.jobs/en/search.json", params=params).json().get("jobs", [])
        for j in jobs:
            out.append(make_job(j.get("title"), "Amazon", j.get("location"), "Amazon",
                                "https://www.amazon.jobs" + j.get("job_path", ""),
                                kind, j.get("posted_date", "")))
    return out[:limit]


def scrape_microsoft(q, loc, kinds, limit):
    query = q + (" intern" if kinds == {"Internship"} else "")
    r = get("https://apply.careers.microsoft.com/api/pcsx/search",
            params={"domain": "microsoft.com", "query": query, "location": loc,
                    "start": 0, "sort_by": "timestamp"})
    positions = (r.json().get("data") or {}).get("positions", [])
    out = []
    for p in positions[:limit]:
        path = p.get("positionUrl") or f"/careers/job/{p.get('id', '')}"
        locs = p.get("locations") or p.get("standardizedLocations") or []
        out.append(make_job(p.get("name"), "Microsoft",
                            ", ".join(locs[:2]) if isinstance(locs, list) else locs,
                            "Microsoft", "https://apply.careers.microsoft.com" + path))
    return out


def scrape_google(q, loc, kinds, limit):
    """Best effort: Google Careers has no public API, so parse job links from HTML."""
    levels = []
    if "Internship" in kinds:
        levels.append("INTERN_AND_APPRENTICE")
    if "Full-time" in kinds:
        levels.append("EARLY")
    params = [("q", q), ("location", loc)] + [("target_level", lv) for lv in levels]
    html = get("https://www.google.com/about/careers/applications/jobs/results/",
               params=params).text
    seen, out = set(), []
    for m in re.finditer(r"jobs/results/(\d+-[a-z0-9\-]+)", html):
        slug = m.group(1)
        if slug in seen:
            continue
        seen.add(slug)
        title = slug.split("-", 1)[1].replace("-", " ").title()
        out.append(make_job(title, "Google", loc, "Google",
                            "https://www.google.com/about/careers/applications/jobs/results/" + slug))
        if len(out) >= limit:
            break
    return out


SCRAPERS = {"LinkedIn": scrape_linkedin, "Internshala": scrape_internshala,
            "Unstop": scrape_unstop, "Amazon": scrape_amazon,
            "Google": scrape_google, "Microsoft": scrape_microsoft}


# --------------------------------------------------------------------------
# Direct search links (always work, even if a scraper is blocked)
# --------------------------------------------------------------------------
def search_links(q, loc):
    e, l = up.quote_plus(q), up.quote_plus(loc)
    return {
        "LinkedIn": f"https://www.linkedin.com/jobs/search/?keywords={e}&location={l}&f_E=1%2C2",
        "Internshala (internships)": f"https://internshala.com/internships/keywords-{slugify(q)}/",
        "Internshala (jobs)": f"https://internshala.com/jobs/keywords-{slugify(q)}/",
        "Unstop (jobs)": f"https://unstop.com/jobs?searchTerm={e}",
        "Unstop (internships)": f"https://unstop.com/internships?searchTerm={e}",
        "Amazon": f"https://www.amazon.jobs/en/search?base_query={e}&loc_query={l}",
        "Google": f"https://www.google.com/about/careers/applications/jobs/results/?q={e}&location={l}&target_level=EARLY",
        "Microsoft": f"https://apply.careers.microsoft.com/careers?query={e}&location={l}",
    }


# --------------------------------------------------------------------------
# Search orchestration
# --------------------------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def run_search(roles, location, kinds, sources, limit):
    kinds = set(kinds)
    tasks = [(s, r) for s in sources for r in roles]
    jobs, status = [], {s: {"count": 0, "error": None} for s in sources}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(SCRAPERS[s], r, location, kinds, limit): (s, r) for s, r in tasks}
        for f in as_completed(futs):
            s, _ = futs[f]
            try:
                jobs.extend(f.result())
            except Exception as exc:  # network block, layout change, etc.
                status[s]["error"] = f"{type(exc).__name__}: {str(exc)[:80]}"
    seen, clean = set(), []
    for j in jobs:
        if j["Apply Link"] in seen or SENIOR.search(j["Title"]):
            continue
        seen.add(j["Apply Link"])
        clean.append(j)
    for j in clean:
        status[j["Source"]]["count"] += 1
    order = {s: i for i, s in enumerate(SOURCES)}
    clean.sort(key=lambda j: (order[j["Source"]], j["Title"]))
    return clean, status


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------
def pdf_safe(text):
    """Built-in PDF fonts are Latin-1 only; avoid black-box glyphs."""
    return escape(str(text).encode("latin-1", "replace").decode("latin-1"))


def build_pdf(jobs, meta, links):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12 * mm,
                            rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=14 * mm,
                            title="AI Job Finder Report")
    ss = getSampleStyleSheet()
    cell = ParagraphStyle("cell", parent=ss["Normal"], fontSize=8, leading=10)
    head = ParagraphStyle("head", parent=cell, textColor=colors.white,
                          fontName="Helvetica-Bold")
    story = [Paragraph("AI Job Finder - Fresher Jobs &amp; Internships", ss["Title"]),
             Paragraph(pdf_safe(f"Generated {datetime.now():%d %b %Y, %H:%M} | "
                                f"Roles: {meta['roles']} | Location: {meta['location']} | "
                                f"Type: {meta['kinds']}"), ss["Normal"]),
             Spacer(1, 6 * mm)]

    def link(url, label="Apply now"):
        return Paragraph(f'<a href="{escape(url)}" color="#1a56db"><u>{label}</u></a>', cell)

    widths = [10 * mm, 95 * mm, 55 * mm, 50 * mm, 25 * mm, 30 * mm]
    by_source = {}
    for j in jobs:
        by_source.setdefault(j["Source"], []).append(j)
    for src in SOURCES:
        rows = by_source.get(src)
        if not rows:
            continue
        story.append(Paragraph(f"{src} ({len(rows)})", ss["Heading2"]))
        data = [[Paragraph(h, head) for h in ("#", "Role", "Company", "Location", "Type", "Apply")]]
        for i, j in enumerate(rows, 1):
            data.append([Paragraph(str(i), cell), Paragraph(pdf_safe(j["Title"]), cell),
                         Paragraph(pdf_safe(j["Company"]), cell),
                         Paragraph(pdf_safe(j["Location"]), cell),
                         Paragraph(pdf_safe(j["Type"] or "-"), cell), link(j["Apply Link"])])
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
            ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story += [t, Spacer(1, 5 * mm)]

    if not jobs:
        story.append(Paragraph("No live listings could be fetched. Use the direct search "
                               "links below.", ss["Normal"]))
    story.append(Paragraph("Direct search links (always up to date)", ss["Heading2"]))
    for q, ls in links.items():
        story.append(Paragraph(pdf_safe(q), ss["Heading4"]))
        for name, url in ls.items():
            story.append(Paragraph(f"{pdf_safe(name)}: "
                                   f'<a href="{escape(url)}" color="#1a56db"><u>open search</u></a>',
                                   cell))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Listings are fetched live from public pages and may change or "
                           "expire; always verify details on the official site.", cell))

    def footer(canvas, d):
        canvas.setFont("Helvetica", 7)
        canvas.drawRightString(landscape(A4)[0] - 12 * mm, 8 * mm, f"Page {d.page}")

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="AI Job Finder", page_icon="🎯", layout="wide")
    st.title("🎯 AI Job Finder")
    st.caption("Fresher jobs & internships in AI / ML / Data Science / Python from "
               "LinkedIn, Internshala, Unstop, Amazon, Google and Microsoft.")

    with st.sidebar:
        st.header("Filters")
        roles = st.multiselect("Roles", DEFAULT_ROLES + ["Data Analyst", "NLP", "Deep Learning",
                               "Generative AI", "MLOps", "Computer Vision"],
                               default=DEFAULT_ROLES[:3])
        custom = st.text_input("Custom keyword (optional)")
        location = st.text_input("Location", "India")
        kinds = st.multiselect("Type", ["Internship", "Full-time"],
                               default=["Internship", "Full-time"])
        sources = st.multiselect("Sources", SOURCES, default=SOURCES)
        limit = st.slider("Max results per source per role", 5, 30, 10)
        go = st.button("🔍 Search jobs", type="primary", use_container_width=True)

    all_roles = roles + ([custom.strip()] if custom.strip() else [])
    if go:
        if not (all_roles and kinds and sources):
            st.warning("Pick at least one role, type and source.")
        else:
            with st.spinner("Searching all sources..."):
                jobs, status = run_search(tuple(all_roles), location, tuple(kinds),
                                          tuple(sources), limit)
            st.session_state["result"] = {
                "jobs": jobs, "status": status,
                "meta": {"roles": ", ".join(all_roles), "location": location,
                         "kinds": ", ".join(kinds)},
                "links": {r: search_links(r, location) for r in all_roles}}

    res = st.session_state.get("result")
    if not res:
        st.info("Choose your filters in the sidebar and click **Search jobs**.")
        return

    jobs, status = res["jobs"], res["status"]
    cols = st.columns(len(status))
    for col, (s, v) in zip(cols, status.items()):
        col.metric(s, v["count"], help=v["error"] or "OK")
    failed = [s for s, v in status.items() if v["error"] and not v["count"]]
    if failed:
        st.warning(f"Could not fetch live listings from: {', '.join(failed)} (site blocked the "
                   "request or changed its layout). Use the direct search links below.")

    if jobs:
        df = pd.DataFrame(jobs)
        src_pick = st.multiselect("Show sources", sorted(df["Source"].unique()),
                                  default=sorted(df["Source"].unique()))
        text = st.text_input("Filter results by text")
        view = df[df["Source"].isin(src_pick)]
        if text:
            mask = view.apply(lambda r: text.lower() in " ".join(map(str, r)).lower(), axis=1)
            view = view[mask]
        st.dataframe(view, use_container_width=True, hide_index=True,
                     column_config={"Apply Link": st.column_config.LinkColumn(
                         "Apply", display_text="Apply ↗")})
        shown = view.to_dict("records")
        c1, c2 = st.columns(2)
        c1.download_button("📄 Download PDF", build_pdf(shown, res["meta"], res["links"]),
                           file_name=f"jobs_{datetime.now():%Y%m%d}.pdf",
                           mime="application/pdf", use_container_width=True)
        c2.download_button("📊 Download CSV", view.to_csv(index=False).encode(),
                           file_name="jobs.csv", mime="text/csv", use_container_width=True)
    else:
        st.error("No live results. The PDF will still contain direct search links.")
        st.download_button("📄 Download PDF (search links)",
                           build_pdf([], res["meta"], res["links"]),
                           file_name="job_search_links.pdf", mime="application/pdf")

    with st.expander("🔗 Direct search links"):
        for role, ls in res["links"].items():
            st.markdown(f"**{role}**")
            st.markdown(" · ".join(f"[{n}]({u})" for n, u in ls.items()))


if __name__ == "__main__":
    main()