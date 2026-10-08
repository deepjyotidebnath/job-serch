"""
AI/ML Job & Internship Search Engine for CS Graduates (2027 batch)
-------------------------------------------------------------------
Run:  streamlit run app.py

How it works (3 layers):
 1. LIVE SCRAPE   - LinkedIn, Indeed, Naukri via python-jobspy; Internshala (HTML);
                    Amazon.jobs (official JSON API); Greenhouse boards of AI companies.
 2. SEARCH LINKS  - Portals that block scraping (Unstop, Wellfound, Cutshort, Instahyre,
                    Hirist, FreshersWorld, Google/Microsoft/NVIDIA careers...) get
                    pre-filled deep links so one click opens the live results.
 3. EXPORT        - Everything goes into a PDF with clickable "Apply" links (+ CSV).
"""
import io
import re
import time
from datetime import datetime
from urllib.parse import quote, quote_plus

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

DEFAULT_KEYWORDS = [
    "machine learning",
    "artificial intelligence",
    "data science",
    "python developer",
    "generative AI",
]

# Titles containing these are almost never for freshers
SENIOR_WORDS = re.compile(
    r"\b(senior|sr\.?|lead|principal|staff|manager|head|director|architect|vp|"
    r"iii|iv|expert|consultant)\b",
    re.I,
)
FRESHER_WORDS = re.compile(
    r"\b(intern|internship|fresher|graduate|entry|trainee|junior|associate|"
    r"early career|campus|new grad|university|2027|2026|apprentice)\b",
    re.I,
)
# Role relevance: title must mention one of these
ROLE_WORDS = re.compile(
    r"\b(ai|ml|machine learning|data scien|data analy|deep learning|nlp|llm|"
    r"generative|python|computer vision|software|sde|research|applied scien|"
    r"data engineer|mlops)\b",
    re.I,
)

# Greenhouse boards of AI-first companies (board token -> display name)
GREENHOUSE_BOARDS = {
    "anthropic": "Anthropic",
    "databricks": "Databricks",
    "scaleai": "Scale AI",
    "huggingface": "Hugging Face",
    "cohere": "Cohere",
    "stabilityai": "Stability AI",
    "runwayml": "Runway",
    "glean": "Glean",
}


# --------------------------------------------------------------------------
# Layer 1: live scrapers
# --------------------------------------------------------------------------
def scrape_jobspy(keywords, location, per_kw, hours_old, sites):
    rows = []
    try:
        from jobspy import scrape_jobs
    except ImportError:
        st.warning("python-jobspy not installed - skipping LinkedIn/Indeed/Naukri.")
        return rows
    for kw in keywords:
        for site in sites:
            try:
                df = scrape_jobs(
                    site_name=[site],
                    search_term=f"{kw} fresher intern",
                    location=location,
                    results_wanted=per_kw,
                    hours_old=hours_old,
                    country_indeed="India",
                    linkedin_fetch_description=False,
                )
                for _, r in df.iterrows():
                    rows.append(
                        {
                            "Title": r.get("title"),
                            "Company": r.get("company"),
                            "Location": r.get("location"),
                            "Source": str(r.get("site", site)).capitalize(),
                            "Posted": str(r.get("date_posted") or ""),
                            "Apply Link": r.get("job_url_direct") or r.get("job_url"),
                            "Keyword": kw,
                        }
                    )
            except Exception as e:  # one portal failing must not kill the search
                st.toast(f"{site} failed for '{kw}': {str(e)[:80]}")
            time.sleep(0.5)
    return rows


def scrape_internshala(keywords, per_kw):
    rows = []
    for kw in keywords:
        slug = kw.lower().replace(" ", "-")
        for kind, path in (("Internship", "internships"), ("Job", "jobs")):
            url = f"https://internshala.com/{path}/keywords-{slug}/"
            try:
                html = requests.get(url, headers=HEADERS, timeout=15).text
                soup = BeautifulSoup(html, "html.parser")
                cards = soup.select("div.individual_internship")[:per_kw]
                for c in cards:
                    a = c.select_one("a.job-title-href") or c.select_one("a[href*='/detail/']")
                    href = c.get("data-href") or (a.get("href") if a else None)
                    if not href:
                        continue
                    title = a.get_text(strip=True) if a else kw.title()
                    comp = c.select_one(".company-name, .company_name")
                    loc = c.select_one(".locations, .location_link")
                    rows.append(
                        {
                            "Title": title,
                            "Company": comp.get_text(strip=True) if comp else "",
                            "Location": loc.get_text(" ", strip=True) if loc else "",
                            "Source": f"Internshala ({kind})",
                            "Posted": "",
                            "Apply Link": "https://internshala.com" + href
                            if href.startswith("/")
                            else href,
                            "Keyword": kw,
                        }
                    )
            except Exception:
                continue
    return rows


def scrape_amazon(keywords, per_kw):
    rows = []
    for kw in keywords:
        try:
            r = requests.get(
                "https://www.amazon.jobs/en/search.json",
                params={
                    "base_query": kw,
                    "loc_query": "India",
                    "country": "IND",
                    "result_limit": per_kw,
                    "sort": "recent",
                },
                headers=HEADERS,
                timeout=20,
            ).json()
            for j in r.get("jobs", []):
                rows.append(
                    {
                        "Title": j.get("title"),
                        "Company": "Amazon",
                        "Location": j.get("normalized_location") or j.get("location"),
                        "Source": "Amazon Careers",
                        "Posted": j.get("posted_date", ""),
                        "Apply Link": "https://www.amazon.jobs" + j.get("job_path", ""),
                        "Keyword": kw,
                    }
                )
        except Exception:
            continue
    return rows


def scrape_greenhouse(keywords, boards):
    rows = []
    pat = re.compile("|".join(re.escape(k.split()[0]) for k in keywords) + "|intern|graduate", re.I)
    for token, name in boards.items():
        try:
            r = requests.get(
                f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
                headers=HEADERS,
                timeout=20,
            ).json()
            for j in r.get("jobs", []):
                title = j.get("title", "")
                loc = (j.get("location") or {}).get("name", "")
                if pat.search(title) and ("india" in loc.lower() or "remote" in loc.lower()):
                    rows.append(
                        {
                            "Title": title,
                            "Company": name,
                            "Location": loc,
                            "Source": "Company Careers",
                            "Posted": (j.get("updated_at") or "")[:10],
                            "Apply Link": j.get("absolute_url"),
                            "Keyword": "AI company",
                        }
                    )
        except Exception:
            continue
    return rows


# --------------------------------------------------------------------------
# Layer 2: deep search links
# --------------------------------------------------------------------------
def deep_links(kw):
    q, qp, slug = quote(kw), quote_plus(kw), kw.lower().replace(" ", "-")
    return {
        "Job portals": {
            "LinkedIn (Internship + Entry)": f"https://www.linkedin.com/jobs/search/?keywords={qp}&location=India&f_E=1%2C2&f_TPR=r2592000",
            "Indeed India": f"https://in.indeed.com/jobs?q={qp}+fresher&l=India&sort=date",
            "Naukri": f"https://www.naukri.com/{slug}-fresher-jobs",
            "Internshala - Internships": f"https://internshala.com/internships/keywords-{slug}/",
            "Internshala - Jobs": f"https://internshala.com/jobs/keywords-{slug}/",
            "Unstop - Internships": f"https://unstop.com/internships?searchTerm={q}",
            "Unstop - Jobs": f"https://unstop.com/jobs?searchTerm={q}",
            "Wellfound (AngelList)": "https://wellfound.com/role/l/machine-learning-engineer/india",
            "Cutshort": f"https://cutshort.io/jobs/{slug}-jobs",
            "Instahyre": f"https://www.instahyre.com/search-jobs/?keywords={qp}",
            "Hirist": f"https://www.hirist.tech/k/{slug}-jobs",
            "FreshersWorld": f"https://www.freshersworld.com/jobs/jobsearch/{slug}-jobs",
        },
        "MNC / AI company careers": {
            "Google": f"https://www.google.com/about/careers/applications/jobs/results/?q={q}&location=India&target_level=INTERN_AND_APPRENTICE&target_level=EARLY",
            "Microsoft": f"https://jobs.careers.microsoft.com/global/en/search?q={q}&lc=India&exp=Students%20and%20graduates",
            "Amazon": f"https://www.amazon.jobs/en/search?base_query={qp}&loc_query=India&country=IND",
            "NVIDIA": f"https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite?q={q}&locationCountry=c4f78be1a8f14da0ab49ce1162348a5e",
            "Meta": "https://www.metacareers.com/jobs?roles[0]=Internship%20-%20Engineering%2C%20Tech%20%26%20Design",
            "Apple": f"https://jobs.apple.com/en-in/search?search={q}&location=india-INDC",
            "Adobe": f"https://careers.adobe.com/us/en/search-results?keywords={qp}&location=India",
            "Intel": f"https://jobs.intel.com/en/search-jobs/{q}/599/1",
            "IBM": f"https://www.ibm.com/careers/search?q={qp}&field_keyword_05[0]=India",
            "Salesforce": f"https://careers.salesforce.com/en/jobs/?search={qp}&country=India",
            "OpenAI": "https://openai.com/careers/search/",
            "Anthropic": "https://www.anthropic.com/jobs",
            "Databricks": "https://www.databricks.com/company/careers/open-positions",
            "Qualcomm": f"https://careers.qualcomm.com/careers?query={q}&location=India",
            "Samsung R&D": "https://research.samsung.com/careers",
            "Flipkart": "https://www.flipkartcareers.com/#!/joblist",
        },
    }


# --------------------------------------------------------------------------
# Filtering / scoring
# --------------------------------------------------------------------------
def clean(df, fresher_only, role_only, location_filter):
    if df.empty:
        return df
    df = df.dropna(subset=["Title", "Apply Link"]).copy()
    df["Title"] = df["Title"].astype(str)
    df = df.drop_duplicates(subset=["Apply Link"])
    df = df.drop_duplicates(subset=["Title", "Company"])
    if fresher_only:
        df = df[~df["Title"].str.contains(SENIOR_WORDS)]
    if role_only:
        df = df[df["Title"].str.contains(ROLE_WORDS)]
    if location_filter:
        pat = "|".join(re.escape(x.strip()) for x in location_filter.split(",") if x.strip())
        if pat:
            df = df[df["Location"].astype(str).str.contains(pat, case=False, na=True)]
    df["Fresher Match"] = df["Title"].apply(lambda t: "Yes" if FRESHER_WORDS.search(t) else "")
    df = df.sort_values(["Fresher Match", "Posted"], ascending=[False, False])
    return df.reset_index(drop=True)


# --------------------------------------------------------------------------
# Layer 3: PDF export (clickable links)
# --------------------------------------------------------------------------
def build_pdf(df, links_by_kw, meta):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title="AI/ML Jobs & Internships - 2027 Batch",
    )
    ss = getSampleStyleSheet()
    cell = ParagraphStyle("cell", parent=ss["BodyText"], fontSize=8, leading=10)
    link_style = ParagraphStyle("lnk", parent=cell, textColor=colors.HexColor("#1a56db"))
    story = [
        Paragraph("AI / ML / Data Science / Python - Jobs &amp; Internships (2027 Batch)", ss["Title"]),
        Paragraph(
            f"Generated {datetime.now():%d %b %Y, %I:%M %p} | Keywords: {meta['kw']} | "
            f"Location: {meta['loc']} | Results: {len(df)}",
            cell,
        ),
        Spacer(1, 6),
    ]

    esc = lambda s: (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    if not df.empty:
        story.append(Paragraph("Live results (click APPLY)", ss["Heading2"]))
        data = [["#", "Role", "Company", "Location", "Source", "Fresher?", "Apply"]]
        for i, r in df.iterrows():
            url = esc(r["Apply Link"])
            data.append(
                [
                    i + 1,
                    Paragraph(esc(r["Title"]), cell),
                    Paragraph(esc(r["Company"]), cell),
                    Paragraph(esc(r["Location"]), cell),
                    Paragraph(esc(r["Source"]), cell),
                    r.get("Fresher Match", ""),
                    Paragraph(f'<a href="{url}"><u>APPLY</u></a>', link_style),
                ]
            )
        t = Table(
            data,
            colWidths=[8 * mm, 85 * mm, 50 * mm, 45 * mm, 35 * mm, 17 * mm, 20 * mm],
            repeatRows=1,
        )
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
                ]
            )
        )
        story.append(t)

    story.append(Spacer(1, 10))
    story.append(Paragraph("Direct search links (portals &amp; company career pages)", ss["Heading2"]))
    for kw, groups in links_by_kw.items():
        story.append(Paragraph(f"<b>Keyword: {esc(kw)}</b>", ss["Heading3"]))
        for group, items in groups.items():
            parts = [f'<a href="{esc(u)}" color="#1a56db"><u>{esc(n)}</u></a>' for n, u in items.items()]
            story.append(Paragraph(f"<b>{group}:</b> " + " &nbsp;|&nbsp; ".join(parts), cell))
            story.append(Spacer(1, 3))
    doc.build(story)
    return buf.getvalue()


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------
st.set_page_config(page_title="AI Job Finder - 2027 Batch", page_icon="🎯", layout="wide")
st.title("🎯 AI/ML Job & Internship Finder - CS Batch 2027")
st.caption("Searches LinkedIn, Indeed, Naukri, Internshala, Amazon + AI companies live, "
           "and gives one-click search links for Unstop, Wellfound, Cutshort, Instahyre, "
           "Hirist, FreshersWorld, Google, Microsoft, NVIDIA & more.")

with st.sidebar:
    st.header("Search settings")
    kws = st.multiselect("Keywords", DEFAULT_KEYWORDS + ["data analyst", "NLP", "computer vision",
                         "MLOps", "deep learning", "LLM", "software engineer"],
                         default=DEFAULT_KEYWORDS[:4])
    extra = st.text_input("Add custom keywords (comma separated)")
    location = st.text_input("Location", "India")
    loc_filter = st.text_input("Only these cities (comma separated, optional)",
                               placeholder="Bangalore, Hyderabad, Remote")
    per_kw = st.slider("Results per keyword per site", 5, 40, 15)
    days = st.slider("Posted within (days)", 3, 90, 30)
    st.subheader("Live sources")
    use_li = st.checkbox("LinkedIn", True)
    use_in = st.checkbox("Indeed", True)
    use_nk = st.checkbox("Naukri", True)
    use_is = st.checkbox("Internshala", True)
    use_am = st.checkbox("Amazon Careers", True)
    use_gh = st.checkbox("AI company boards (Anthropic, Databricks, Scale...)", True)
    st.subheader("Filters")
    fresher_only = st.checkbox("Hide senior/lead/manager roles", True)
    role_only = st.checkbox("Only AI/ML/DS/Python-related titles", True)

keywords = kws + [k.strip() for k in extra.split(",") if k.strip()]

if st.button("🔍 Search jobs", type="primary", disabled=not keywords):
    sites = [s for s, on in (("linkedin", use_li), ("indeed", use_in), ("naukri", use_nk)) if on]
    all_rows = []
    with st.status("Searching...", expanded=True) as status:
        if sites:
            st.write(f"LinkedIn/Indeed/Naukri: {', '.join(sites)}")
            all_rows += scrape_jobspy(keywords, location, per_kw, days * 24, sites)
        if use_is:
            st.write("Internshala")
            all_rows += scrape_internshala(keywords, per_kw)
        if use_am:
            st.write("Amazon Careers")
            all_rows += scrape_amazon(keywords, per_kw)
        if use_gh:
            st.write("AI company career boards")
            all_rows += scrape_greenhouse(keywords, GREENHOUSE_BOARDS)
        status.update(label=f"Fetched {len(all_rows)} raw listings", state="complete")

    df = clean(pd.DataFrame(all_rows), fresher_only, role_only, loc_filter)
    st.session_state["df"] = df
    st.session_state["links"] = {k: deep_links(k) for k in keywords}
    st.session_state["meta"] = {"kw": ", ".join(keywords), "loc": loc_filter or location}

if "df" in st.session_state:
    df, links = st.session_state["df"], st.session_state["links"]
    tab1, tab2 = st.tabs([f"📋 Live results ({len(df)})", "🔗 Portal & company search links"])

    with tab1:
        if df.empty:
            st.info("No live results - portals may have rate-limited you. "
                    "Use the Search links tab; they always work.")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Listings", len(df))
            c2.metric("Fresher/intern titles", int((df["Fresher Match"] == "Yes").sum()))
            c3.metric("Sources", df["Source"].nunique())
            src = st.multiselect("Filter by source", sorted(df["Source"].unique()))
            only_f = st.checkbox("Show only fresher/intern-tagged")
            view = df
            if src:
                view = view[view["Source"].isin(src)]
            if only_f:
                view = view[view["Fresher Match"] == "Yes"]
            st.dataframe(
                view,
                use_container_width=True,
                hide_index=True,
                column_config={"Apply Link": st.column_config.LinkColumn("Apply", display_text="Apply ↗")},
            )
            st.session_state["view"] = view

    with tab2:
        for kw, groups in links.items():
            with st.expander(f"Keyword: {kw}", expanded=(kw == list(links)[0])):
                for g, items in groups.items():
                    st.markdown(f"**{g}**")
                    st.markdown(" · ".join(f"[{n}]({u})" for n, u in items.items()))

    st.divider()
    view = st.session_state.get("view", df)
    pdf_bytes = build_pdf(view, links, st.session_state["meta"])
    d1, d2 = st.columns(2)
    d1.download_button("⬇️ Download PDF (with Apply links)", pdf_bytes,
                       file_name=f"ai_jobs_2027_{datetime.now():%Y%m%d}.pdf", mime="application/pdf")
    d2.download_button("⬇️ Download CSV", view.to_csv(index=False).encode(),
                       file_name="ai_jobs_2027.csv", mime="text/csv")

st.divider()
st.caption("Tip: Job boards change their layouts and rate-limit scrapers. If a source returns nothing, "
           "the direct search links still open the live results. Always apply on the official page.")