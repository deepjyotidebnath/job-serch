"""
Job & Internship Finder (India) - single-file Streamlit app. No other files needed.

Run:     streamlit run basic1.py
Install: pip install streamlit requests beautifulsoup4 openpyxl pandas reportlab
"""
import io
import time
from datetime import datetime
from urllib.parse import quote_plus

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
}
COLS = ["Source", "Title", "Company", "Location", "Posted", "Link"]
INDIA_CITIES = [
    "India", "Bengaluru", "Hyderabad", "Pune", "Mumbai", "Delhi NCR", "Gurugram", "Noida",
    "Chennai", "Kolkata", "Ahmedabad", "Kochi", "Jaipur", "Siliguri", "Remote India",
]


def get(url):
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r


# ---------------- sources ----------------
def microsoft(kw, loc):
    url = (
        "https://gcsservices.careers.microsoft.com/search/api/v1/search"
        f"?q={quote_plus(kw)}&lc={quote_plus(loc)}&l=en_us&pg=1&pgSz=25&o=Relevance&flt=true"
    )
    jobs = get(url).json()["operationResult"]["result"]["jobs"]
    return [
        (
            "Microsoft", j.get("title"), "Microsoft",
            ", ".join(j.get("properties", {}).get("locations", [])[:2]),
            (j.get("postingDate") or "")[:10],
            f"https://jobs.careers.microsoft.com/global/en/job/{j['jobId']}",
        )
        for j in jobs
    ]


def google(kw, loc):
    url = f"https://careers.google.com/api/v3/search/?q={quote_plus(kw)}&location={quote_plus(loc)}&page_size=25"
    jobs = get(url).json().get("jobs", [])
    return [
        (
            "Google", j.get("title"), "Google",
            ", ".join(x.get("display", "") for x in j.get("locations", [])[:2]),
            (j.get("publish_date") or "")[:10],
            j.get("apply_url") or "https://www.google.com/about/careers/applications/jobs/results/",
        )
        for j in jobs
    ]


def internshala(kw, loc):
    slug = quote_plus(kw).replace("+", "-")
    soup = BeautifulSoup(get(f"https://internshala.com/internships/keywords-{slug}/").text, "html.parser")
    out = []
    for c in soup.select("div.individual_internship"):
        a = c.select_one("a.job-title-href") or c.select_one("h3 a")
        if not a:
            continue
        comp = c.select_one(".company-name")
        locn = c.select_one(".locations a, .location_link")
        out.append(
            (
                "Internshala", a.get_text(strip=True),
                comp.get_text(strip=True) if comp else "",
                locn.get_text(strip=True) if locn else "", "",
                "https://internshala.com" + a["href"],
            )
        )
    return out


def linkedin(kw, loc):
    # LinkedIn's terms restrict automated scraping: opt-in, low volume, personal use only.
    url = (
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        f"?keywords={quote_plus(kw)}&location={quote_plus(loc)}&f_TPR=r604800&start=0"
    )
    soup = BeautifulSoup(get(url).text, "html.parser")
    out = []
    for li in soup.select("li"):
        a = li.select_one("a.base-card__full-link")
        t = li.select_one(".base-search-card__title")
        if not a or not t:
            continue
        co = li.select_one(".base-search-card__subtitle")
        lo = li.select_one(".job-search-card__location")
        dt = li.select_one("time")
        out.append(
            (
                "LinkedIn", t.get_text(strip=True),
                co.get_text(strip=True) if co else "",
                lo.get_text(strip=True) if lo else "",
                dt.get("datetime", "") if dt else "",
                a["href"].split("?")[0],
            )
        )
    return out


SOURCES = {
    "Microsoft Careers": microsoft,
    "Google Careers": google,
    "Internshala": internshala,
    "LinkedIn (see ToS note)": linkedin,
}


def search_links(kw, loc):
    """Direct links to each site's own results page (India-focused). Always work."""
    q, l = quote_plus(kw), quote_plus(loc)
    dash_k = kw.strip().lower().replace(" ", "-")
    dash_l = loc.strip().lower().replace(" ", "-")
    return [
        ("LinkedIn (search page)", f"{kw} jobs", "-", loc, "",
         f"https://www.linkedin.com/jobs/search/?keywords={q}&location={l}&f_TPR=r86400"),
        ("Naukri (search page)", f"{kw} jobs", "-", loc, "",
         f"https://www.naukri.com/{dash_k}-jobs-in-{dash_l}"),
        ("Indeed India (search page)", f"{kw} jobs", "-", loc, "",
         f"https://in.indeed.com/jobs?q={q}&l={l}&fromage=1"),
        ("Foundit (search page)", f"{kw} jobs", "-", loc, "",
         f"https://www.foundit.in/srp/results?query={q}&locations={l}"),
        ("Internshala (search page)", f"{kw} internships", "-", loc, "",
         f"https://internshala.com/internships/keywords-{dash_k}/"),
        ("Google Careers (search page)", kw, "Google", loc, "",
         f"https://www.google.com/about/careers/applications/jobs/results/?q={q}&location={l}"),
        ("Microsoft Careers (search page)", kw, "Microsoft", loc, "",
         f"https://jobs.careers.microsoft.com/global/en/search?q={q}&lc={l}"),
    ]


def fetch(kw, loc, names):
    rows, status = [], {}
    for name in names:
        try:
            res = SOURCES[name](kw, loc)
            rows += res
            status[name] = f"{len(res)} results"
        except Exception as e:  # noqa: BLE001
            status[name] = f"failed ({e.__class__.__name__})"
    return rows, status


# ---------------- exports ----------------
def make_excel(frame):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        frame.to_excel(xw, index=False, sheet_name="Jobs")
        ws = xw.sheets["Jobs"]
        link_col = list(frame.columns).index("Link") + 1
        for r in range(2, ws.max_row + 1):
            cell = ws.cell(r, link_col)
            if cell.value:
                cell.hyperlink = cell.value
                cell.style = "Hyperlink"
        for letter, w in zip("ABCDEFG", [28, 45, 22, 24, 12, 60, 17]):
            ws.column_dimensions[letter].width = w
        ws.freeze_panes = "A2"
    return buf.getvalue()


def make_pdf(frame):
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ss = getSampleStyleSheet()
    cell = ss["BodyText"].clone("cell", fontSize=7.5, leading=9)
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=landscape(A4), leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24)
    data = [[Paragraph(f"<b>{c}</b>", cell) for c in COLS]]
    for _, r in frame.iterrows():
        link = str(r["Link"] or "")
        link_p = f'<a href="{escape(link)}" color="blue">Open link</a>' if link else ""
        data.append([Paragraph(escape(str(r[c] or "")), cell) for c in COLS[:-1]] + [Paragraph(link_p, cell)])
    t = Table(data, colWidths=[110, 210, 100, 120, 60, 70], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F6FA")]),
    ]))
    head = Paragraph(f"Job &amp; Internship Listings - India - {datetime.now():%d %b %Y %H:%M}", ss["Title"])
    doc.build([head, Spacer(1, 6), t])
    return out.getvalue()


# ---------------- UI ----------------
st.set_page_config(page_title="Job & Internship Finder (India)", page_icon="🔎", layout="wide")

with st.sidebar:
    st.header("Search")
    keywords = st.text_input("Keywords", "python intern")
    city = st.selectbox("Location", INDIA_CITIES, index=0)
    custom = st.text_input("Or type another city", "")
    location = custom.strip() or city
    chosen = st.multiselect(
        "Live sources", list(SOURCES), default=["Microsoft Careers", "Google Careers", "Internshala"]
    )
    st.caption("LinkedIn restricts automated scraping. Use sparingly, for personal use only.")
    live = st.toggle("Live mode (auto-refresh)", value=False)
    every = st.slider("Refresh every (minutes)", 1, 60, 10, disabled=not live)
    go = st.button("Search now", type="primary", width="stretch")

st.title("🔎 Job & Internship Finder (India)")
st.caption("Live listings plus direct links to Naukri, Indeed India, Foundit, LinkedIn, Internshala, Google and Microsoft.")

if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame(columns=COLS + ["Found At"])
    st.session_state.status = {}
    st.session_state.last = None

due = live and st.session_state.last is not None and (time.time() - st.session_state.last) >= every * 60

if go or due or st.session_state.last is None:
    with st.spinner("Searching..."):
        rows, status = fetch(keywords, location, chosen)
        rows = search_links(keywords, location) + rows
    new = pd.DataFrame(rows, columns=COLS)
    new["Found At"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    old = st.session_state.df
    if not old.empty:
        new = new[~new["Link"].isin(old["Link"])]
    st.session_state.df = pd.concat([new, old], ignore_index=True)
    st.session_state.status = status
    st.session_state.last = time.time()

df = st.session_state.df

if st.session_state.status:
    cols = st.columns(len(st.session_state.status))
    for c, (name, s) in zip(cols, st.session_state.status.items()):
        c.metric(name, s)
    if any("failed" in s for s in st.session_state.status.values()):
        st.info(
            "A source that failed may be blocking requests or have changed its layout. "
            "The '(search page)' rows still open each site's own results."
        )

f1, f2 = st.columns([1, 2])
src_filter = f1.multiselect("Filter by source", sorted(df["Source"].unique()))
text_filter = f2.text_input("Filter text (title / company / location)")

view = df
if src_filter:
    view = view[view["Source"].isin(src_filter)]
if text_filter:
    mask = (
        view[["Title", "Company", "Location"]].fillna("")
        .apply(lambda col: col.str.contains(text_filter, case=False, regex=False))
        .any(axis=1)
    )
    view = view[mask]

st.subheader(f"{len(view)} listings")
st.dataframe(
    view, width="stretch", hide_index=True,
    column_config={"Link": st.column_config.LinkColumn("Link", display_text="Open ↗")},
)

d1, d2 = st.columns(2)
d1.download_button(
    "⬇️ Download as Excel", make_excel(view), file_name="jobs.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch",
)
try:
    d2.download_button(
        "⬇️ Download as PDF", make_pdf(view), file_name="jobs.pdf",
        mime="application/pdf", width="stretch",
    )
except ImportError:
    d2.info("For PDF export run: pip install reportlab")

if live:
    left = int(every * 60 - (time.time() - st.session_state.last))
    st.caption(f"Next refresh in about {max(left, 0) // 60} min. Keep this tab open.")
    time.sleep(min(max(left, 1), 30))
    st.rerun()