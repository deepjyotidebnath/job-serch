"""
Leeco-style Internshala agent: Discover -> AI fit score -> You approve -> Apply -> Track

Run:  pip install streamlit selenium pypdf groq pandas python-dotenv
      streamlit run app_leeco_style.py
Selectors are best guesses - adjust SELECTORS if Internshala changes its HTML.
"""
import json
import os
import random
import time

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from groq import Groq
from pypdf import PdfReader
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

load_dotenv()  # reads .env in the current folder
TRACKER = "applications.csv"
SELECTORS = {
    "login_email": "#email", "login_password": "#password", "login_submit": "#login_submit",
    "otp_input": "input[id*='otp' i], input[name*='otp' i]",
    "otp_submit": "button[type='submit'], #verify_otp, .btn-primary",
    "card": "div.individual_internship",
    "card_title": ".job-internship-name, .profile",
    "card_company": ".company-name, .company_name",
    "apply_btn": "#continue_button, .apply_now_button, #easy_apply_button",
    "cover_letter": "#cover_letter_holder .ql-editor",
    "questions": ".additional_question textarea, #application_form textarea",
    "submit": "#submit",
}

st.set_page_config(page_title="Internshala AI Agent", page_icon="🎯", layout="wide")
st.title("🎯 Internshala AI Agent")
ss = st.session_state
for k, v in {"driver": None, "resume": "", "need_otp": False, "logged_in": False,
             "found": pd.DataFrame()}.items():
    ss.setdefault(k, v)


def get_driver():
    try:
        if ss.driver is not None:
            _ = ss.driver.current_url
            return ss.driver
    except Exception:
        ss.driver = None
    return None


def parse_json(text):
    return json.loads(text.replace("```json", "").replace("```", "").strip())


def llm(client, model, prompt, max_tokens=2000):
    """Call Groq in JSON mode; the prompt must ask for a JSON object."""
    r = client.chat.completions.create(
        model=model, max_tokens=max_tokens, temperature=0.4,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}])
    return parse_json(r.choices[0].message.content)


def load_tracker():
    return pd.read_csv(TRACKER) if os.path.exists(TRACKER) else pd.DataFrame(
        columns=["time", "role", "company", "url", "score", "status"])


def save_tracker(rows):
    df = pd.concat([load_tracker(), pd.DataFrame(rows)], ignore_index=True)
    df.to_csv(TRACKER, index=False)


# ---------------- Sidebar ----------------
with st.sidebar:
    api_key = st.text_input("Groq API key", value=os.getenv("GROQ_API_KEY", ""), type="password")
    model = st.text_input("Model", os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))
    email = st.text_input("Internshala email", os.getenv("INTERNSHALA_EMAIL", ""))
    password = st.text_input("Internshala password", value=os.getenv("INTERNSHALA_PASSWORD", ""), type="password")
    st.divider()
    kind = st.radio("Search", ["internships", "jobs"], horizontal=True)
    keywords = st.text_input("Keywords (comma separated)", os.getenv("SEARCH_KEYWORDS", "python, data science"))
    pages = st.slider("Pages per keyword", 1, 3, 1)
    min_score = st.slider("Min fit score to pre-select", 0, 100, 65)
    st.divider()
    max_apply = st.slider("Max applications this run", 1, 20, 5)
    min_delay, max_delay = st.slider("Delay between applications (sec)", 5, 90, (15, 40))
    auto_submit = st.checkbox("Auto-submit (off = I click submit)", value=False)

tab_setup, tab_find, tab_apply, tab_track = st.tabs(["1 Setup", "2 Discover", "3 Review & Apply", "4 Tracker"])

# ---------------- Setup: resume + login/OTP ----------------
with tab_setup:
    pdf = st.file_uploader("Resume (PDF)", type="pdf")
    if pdf:
        ss.resume = "\n".join((p.extract_text() or "") for p in PdfReader(pdf).pages)
        st.caption(f"Read {len(ss.resume)} characters.")
    if st.button("Open browser & log in"):
        if not (email and password):
            st.error("Enter email and password in the sidebar.")
        else:
            ss.driver = get_driver() or webdriver.Chrome()
            d = ss.driver
            d.get("https://internshala.com/login/student")
            WebDriverWait(d, 15).until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, SELECTORS["login_email"]))).send_keys(email)
            d.find_element(By.CSS_SELECTOR, SELECTORS["login_password"]).send_keys(password)
            d.find_element(By.CSS_SELECTOR, SELECTORS["login_submit"]).click()
            time.sleep(4)
            ss.need_otp = bool(d.find_elements(By.CSS_SELECTOR, SELECTORS["otp_input"]))
            ss.logged_in = not ss.need_otp and "login" not in d.current_url
    st.write("Status: " + ("🟢 logged in" if ss.logged_in else "🟡 OTP needed" if ss.need_otp else "🔴 not logged in"))
    if ss.need_otp:
        otp = st.text_input("Enter the OTP", max_chars=8)
        if st.button("Submit OTP") and otp:
            d = get_driver()
            d.find_element(By.CSS_SELECTOR, SELECTORS["otp_input"]).send_keys(otp)
            d.find_element(By.CSS_SELECTOR, SELECTORS["otp_submit"]).click()
            time.sleep(4)
            ss.need_otp = bool(d.find_elements(By.CSS_SELECTOR, SELECTORS["otp_input"]))
            ss.logged_in = not ss.need_otp
            st.rerun()

# ---------------- Discover + AI fit scoring ----------------
with tab_find:
    if st.button("🔎 Find & score matches", type="primary"):
        d = get_driver()
        if not (d and ss.logged_in and ss.resume and api_key):
            st.error("Need: resume, API key, and a logged-in browser (tab 1).")
        else:
            rows, seen = [], set(load_tracker()["url"])
            with st.status("Scanning listings...") as status:
                for kw in [k.strip() for k in keywords.split(",") if k.strip()]:
                    slug = kw.lower().replace(" ", "-")
                    for p in range(1, pages + 1):
                        d.get(f"https://internshala.com/{kind}/keywords-{slug}" + (f"/page-{p}" if p > 1 else ""))
                        time.sleep(2.5)
                        for card in d.find_elements(By.CSS_SELECTOR, SELECTORS["card"]):
                            link = card.get_attribute("data-href") or ""
                            if not link:
                                try:
                                    link = card.find_element(By.CSS_SELECTOR, "a[href*='/detail/']").get_attribute("href")
                                except Exception:
                                    continue
                            if link.startswith("/"):
                                link = "https://internshala.com" + link

                            def txt(sel):
                                try:
                                    return card.find_element(By.CSS_SELECTOR, sel).text.strip()
                                except Exception:
                                    return ""
                            if link and link not in seen:
                                seen.add(link)
                                rows.append({"role": txt(SELECTORS["card_title"]),
                                             "company": txt(SELECTORS["card_company"]),
                                             "summary": card.text.replace("\n", " | ")[:350], "url": link})
                status.update(label=f"Found {len(rows)} new listings. Scoring with Groq...")
                client = Groq(api_key=api_key)
                for s in range(0, len(rows), 12):
                    chunk = rows[s:s + 12]
                    prompt = f"""Score how well each listing fits this candidate (0-100). Be strict and honest.
RESUME:
{ss.resume[:6000]}

LISTINGS:
{json.dumps([{"i": i, "role": r["role"], "company": r["company"], "details": r["summary"]} for i, r in enumerate(chunk)])}

Respond ONLY with a JSON object: {{"results": [{{"i": 0, "score": 80, "reason": "one short sentence"}}, ...]}}"""
                    try:
                        for item in llm(client, model, prompt)["results"]:
                            chunk[item["i"]]["score"] = item["score"]
                            chunk[item["i"]]["reason"] = item["reason"]
                    except Exception as e:
                        st.warning(f"Scoring failed for a batch: {type(e).__name__}")
                status.update(label="Done", state="complete")
            df = pd.DataFrame(rows)
            if not df.empty:
                df["score"] = df.get("score", 0).fillna(0)
                df["reason"] = df.get("reason", "").fillna("")
                df["apply"] = df["score"] >= min_score
                df = df.sort_values("score", ascending=False)
            ss.found = df
    if ss.found.empty:
        st.info("No results yet. Run a scan.")
    else:
        st.success(f"{len(ss.found)} listings scored. Go to tab 3.")

# ---------------- Review & apply ----------------
with tab_apply:
    if ss.found.empty:
        st.info("Scan first.")
    else:
        cols = ["apply", "score", "role", "company", "reason", "url"]
        edited = st.data_editor(ss.found[cols], hide_index=True, use_container_width=True,
                                column_config={"url": st.column_config.LinkColumn("url")})
        chosen = edited[edited["apply"]].head(max_apply)
        st.caption(f"{len(chosen)} selected (cap {max_apply}).")
        if st.button("🚀 Apply to selected", type="primary"):
            d, client, wait = get_driver(), Groq(api_key=api_key), None
            if not (d and ss.logged_in):
                st.error("Log in first.")
                st.stop()
            wait = WebDriverWait(d, 10)
            bar, results = st.progress(0.0), []
            for i, r in enumerate(chosen.itertuples(), 1):
                status = "filled"
                try:
                    d.get(r.url)
                    time.sleep(2)
                    page_text = d.find_element(By.TAG_NAME, "body").text
                    wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, SELECTORS["apply_btn"]))).click()
                    time.sleep(2)
                    boxes = d.find_elements(By.CSS_SELECTOR, SELECTORS["questions"])
                    qs = [d.execute_script(
                        "return (arguments[0].closest('.form-group, .additional_question')||arguments[0].parentElement).innerText",
                        b).strip()[:400] for b in boxes]
                    out = llm(client, model, f"""Help a student apply. Use ONLY facts from the resume; never invent anything.
RESUME:
{ss.resume[:8000]}
LISTING:
{page_text[:5000]}
CUSTOM QUESTIONS (answer each, 2-5 sentences, first person): {json.dumps(qs)}
Write a specific 120-180 word cover letter.
Respond ONLY with JSON: {{"cover_letter": "...", "answers": [exactly {len(qs)} strings]}}""")
                    try:
                        cl = d.find_element(By.CSS_SELECTOR, SELECTORS["cover_letter"])
                        cl.click()
                        cl.send_keys(out["cover_letter"])
                    except Exception:
                        status = "filled (no cover-letter box)"
                    for b, a in zip(boxes, out.get("answers", [])):
                        b.send_keys(a)
                    if auto_submit:
                        d.find_element(By.CSS_SELECTOR, SELECTORS["submit"]).click()
                        status = "submitted"
                    else:
                        st.warning(f"{r.role} @ {r.company}: review in the browser and submit manually.")
                except Exception as e:
                    status = f"failed: {type(e).__name__}"
                results.append({"time": time.strftime("%Y-%m-%d %H:%M"), "role": r.role, "company": r.company,
                                "url": r.url, "score": r.score, "status": status})
                bar.progress(i / len(chosen))
                if i < len(chosen):
                    time.sleep(random.uniform(min_delay, max_delay))
            save_tracker(results)
            st.success("Run finished. See the Tracker tab.")

# ---------------- Tracker ----------------
with tab_track:
    t = load_tracker()
    if t.empty:
        st.info("Nothing tracked yet.")
    else:
        st.dataframe(t.sort_values("time", ascending=False), use_container_width=True)
        st.download_button("Download CSV", t.to_csv(index=False), "applications.csv")