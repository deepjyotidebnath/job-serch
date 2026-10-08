"""
Internshala Apply Helper (Streamlit + Selenium)

Run:  pip install streamlit selenium pandas
      streamlit run app.py

NOTE: Selectors below are best guesses and Internshala changes its HTML often.
Open a listing in Chrome -> right click -> Inspect, and fix the SELECTORS dict if something fails.
"""
import random
import time

import pandas as pd
import streamlit as st
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# ---- Edit these if Internshala changes its markup ----
SELECTORS = {
    "card": "div.individual_internship",
    "title": ".job-internship-name, .profile",
    "company": ".company-name, .company_name",
    "apply_btn": "#continue_button, .apply_now_button, #easy_apply_button",
    "cover_letter": "#cover_letter_holder .ql-editor",
    "submit": "#submit",
}

DEFAULT_TEMPLATE = """Hello {company} team,

I'm excited to apply for the {role} position. I have hands-on experience with {skills}, \
and I enjoy building practical projects. I'd love to contribute and learn with your team.

Thank you for your time,
{name}"""

st.set_page_config(page_title="Internshala Apply Helper", page_icon="📝", layout="wide")
st.title("📝 Internshala Apply Helper")

ss = st.session_state
ss.setdefault("driver", None)
ss.setdefault("listings", pd.DataFrame())


def get_driver():
    """Return the live driver or None if the browser was closed."""
    d = ss.driver
    if d is None:
        return None
    try:
        _ = d.current_url
        return d
    except Exception:
        ss.driver = None
        return None


# ---------------- Sidebar: profile & settings ----------------
with st.sidebar:
    st.header("Your details")
    name = st.text_input("Name")
    skills = st.text_input("Key skills", "Python, SQL, Streamlit")
    st.header("Search")
    kind = st.radio("Type", ["internships", "jobs"], horizontal=True)
    keyword = st.text_input("Keyword", "python")
    pages = st.slider("Pages to scan", 1, 5, 1)
    st.header("Safety")
    max_apply = st.slider("Max applications this run", 1, 20, 5)
    min_delay, max_delay = st.slider("Random delay between applications (sec)", 5, 90, (15, 40))
    auto_submit = st.checkbox("Auto-submit (otherwise I click submit myself)", value=False)

template = st.text_area("Cover letter template", DEFAULT_TEMPLATE, height=220,
                        help="Placeholders: {company} {role} {skills} {name}")

# ---------------- Step 1: browser & login ----------------
st.subheader("1. Open browser and log in")
c1, c2 = st.columns(2)
if c1.button("Open Chrome / go to login"):
    if get_driver() is None:
        ss.driver = webdriver.Chrome()
    ss.driver.get("https://internshala.com/login/student")
    st.info("Log in manually in the opened window, then continue to step 2.")
c2.write("Browser: " + ("🟢 open" if get_driver() else "🔴 not open"))

# ---------------- Step 2: scan listings ----------------
st.subheader("2. Scan listings")
if st.button("Scan"):
    d = get_driver()
    if not d:
        st.error("Open the browser first.")
    else:
        rows = []
        slug = keyword.strip().lower().replace(" ", "-")
        for p in range(1, pages + 1):
            suffix = f"/page-{p}" if p > 1 else ""
            d.get(f"https://internshala.com/{kind}/keywords-{slug}{suffix}")
            time.sleep(2.5)
            for card in d.find_elements(By.CSS_SELECTOR, SELECTORS["card"]):
                try:
                    title_el = card.find_element(By.CSS_SELECTOR, SELECTORS["title"])
                    link = title_el.find_element(By.XPATH, ".//ancestor-or-self::a").get_attribute("href")
                except Exception:
                    link = card.get_attribute("data-href") or ""
                    title_el = None
                try:
                    company = card.find_element(By.CSS_SELECTOR, SELECTORS["company"]).text.strip()
                except Exception:
                    company = "your company"
                if link and not link.startswith("http"):
                    link = "https://internshala.com" + link
                rows.append({
                    "apply": True,
                    "role": title_el.text.strip() if title_el else "",
                    "company": company,
                    "url": link,
                })
        ss.listings = pd.DataFrame(rows).drop_duplicates("url") if rows else pd.DataFrame()
        if ss.listings.empty:
            st.warning("No listings found - check the 'card' selector.")

# ---------------- Step 3: review & apply ----------------
if not ss.listings.empty:
    st.subheader("3. Pick listings and apply")
    edited = st.data_editor(ss.listings, hide_index=True, use_container_width=True,
                            column_config={"url": st.column_config.LinkColumn("url")})
    selected = edited[edited["apply"]].head(max_apply)
    st.caption(f"{len(selected)} will be processed (cap = {max_apply}).")

    if st.button("🚀 Start applying", type="primary"):
        d = get_driver()
        if not d:
            st.error("Browser closed.")
            st.stop()
        log = []
        bar = st.progress(0.0)
        for i, row in enumerate(selected.itertuples(), 1):
            status = "ok"
            try:
                d.get(row.url)
                wait = WebDriverWait(d, 10)
                wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, SELECTORS["apply_btn"]))).click()
                letter = template.format(company=row.company, role=row.role, skills=skills, name=name)
                try:
                    box = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, SELECTORS["cover_letter"])))
                    box.click()
                    box.send_keys(letter)
                except Exception:
                    status = "no cover letter box (filled nothing)"
                if auto_submit:
                    d.find_element(By.CSS_SELECTOR, SELECTORS["submit"]).click()
                    status += " | submitted"
                else:
                    status += " | filled, NOT submitted"
                    st.warning(f"{row.role} @ {row.company}: review in browser, submit, then wait for the next one.")
            except Exception as e:
                status = f"failed: {type(e).__name__}"
            log.append({"role": row.role, "company": row.company, "status": status})
            bar.progress(i / len(selected))
            if i < len(selected):
                time.sleep(random.uniform(min_delay, max_delay))
        st.success("Run finished.")
        st.dataframe(pd.DataFrame(log), use_container_width=True)
        st.download_button("Download log (CSV)", pd.DataFrame(log).to_csv(index=False), "applications_log.csv")