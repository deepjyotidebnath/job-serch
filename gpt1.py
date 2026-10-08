import streamlit as st
import pandas as pd
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

st.set_page_config(page_title="AI Job Search Engine", layout="wide")

st.title("🚀 AI/ML Job & Internship Search Engine")
st.write("Search AI/ML, Data Science, Python Developer, GenAI and related fresher roles.")

DEFAULT_JOBS = [
    {
        "Company":"Google",
        "Role":"Software Engineering Intern",
        "Type":"Internship",
        "Source":"Google Careers",
        "Apply Link":"https://careers.google.com/"
    },
    {
        "Company":"Microsoft",
        "Role":"Software Engineer Intern",
        "Type":"Internship",
        "Source":"Microsoft Careers",
        "Apply Link":"https://careers.microsoft.com/"
    },
    {
        "Company":"Amazon",
        "Role":"Applied Scientist / SDE Intern",
        "Type":"Internship",
        "Source":"Amazon Jobs",
        "Apply Link":"https://www.amazon.jobs/"
    },
    {
        "Company":"LinkedIn",
        "Role":"Machine Learning Engineer",
        "Type":"Full Time",
        "Source":"LinkedIn Jobs",
        "Apply Link":"https://www.linkedin.com/jobs/"
    },
    {
        "Company":"Internshala",
        "Role":"Data Science Intern",
        "Type":"Internship",
        "Source":"Internshala",
        "Apply Link":"https://internshala.com/internships/data-science-internship/"
    },
    {
        "Company":"Unstop",
        "Role":"AI/ML Internship",
        "Type":"Internship",
        "Source":"Unstop",
        "Apply Link":"https://unstop.com/internships"
    }
]

query = st.text_input(
    "Search Role",
    value="AI ML Data Science Python Developer Fresher"
)

df = pd.DataFrame(DEFAULT_JOBS)

if query:
    mask = df.astype(str).apply(
        lambda col: col.str.contains(query.split()[0], case=False, na=False)
    ).any(axis=1)
    filtered = df if mask.sum() == 0 else df[mask]
else:
    filtered = df

st.dataframe(filtered, use_container_width=True)

def generate_pdf(dataframe, filename="jobs_report.pdf"):
    doc = SimpleDocTemplate(filename)
    styles = getSampleStyleSheet()

    content = [
        Paragraph("AI/ML Job Search Report", styles["Title"]),
        Spacer(1,12)
    ]

    table_data = [list(dataframe.columns)] + dataframe.values.tolist()

    table = Table(table_data)
    table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.lightgrey),
        ("GRID",(0,0),(-1,-1),1,colors.black),
    ]))

    content.append(table)
    doc.build(content)
    return filename

if st.button("Generate PDF"):
    pdf_file = generate_pdf(filtered)
    with open(pdf_file, "rb") as f:
        st.download_button(
            label="Download PDF",
            data=f,
            file_name="AI_Jobs_Report.pdf",
            mime="application/pdf"
        )

st.info("For live scraping, connect APIs or scrapers for LinkedIn, Internshala, Unstop, Amazon, Google and Microsoft careers.")
