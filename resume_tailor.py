"""
resume_tailor.py — Upgraded.
1. Extracts text from the master PDF.
2. If GEMINI_API_KEY is configured, uses Gemini 1.5 Flash to generate a tailored 3-sentence Professional Summary.
3. Builds an ATS Keyword and Competencies matrix page including the summary.
4. Appends it to the original styled PDF, preserving formatting.
"""

import os
import importlib
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

def _extract_pdf_text(pdf_path: str) -> str:
    """Extract plain text from a PDF."""
    try:
        reader = PdfReader(pdf_path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""

def _gemini_rewrite_summary(resume_text: str, job_description: str, company: str, role: str) -> str | None:
    """
    Use Gemini to rewrite the professional summary to match JD keywords.
    """
    try:
        import google.generativeai as genai
        import config.profile
        importlib.reload(config.profile)
        api_key = getattr(config.profile, "GEMINI_API_KEY", "")
        if not api_key:
            return None
        genai.configure(api_key=api_key)
        prompt = f"""
You are an ATS optimization expert rewriting a resume summary.
Job Description (key parts): {job_description[:800]}
Target: {role} at {company}
Original Resume Text:
{resume_text[:2000]}

Write a 3-sentence professional summary that:
- Opens with years of experience and core identity (e.g., "Senior Data Engineer with 4+ years...")
- Mentions 3 keywords from the JD naturally
- Closes with a value statement
Return ONLY the 3-sentence summary. No labels, no preamble.
"""
        model    = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"  [GEMINI SUMMARY] Failed ({e}), keeping original summary.")
        return None

def generate_tailored_resume(original_pdf_path: str, job_description: str, company: str, role: str) -> str:
    """
    Full tailoring pipeline:
    1. Extract text from original PDF.
    2. Gemini rewrites summary.
    3. Append ATS keyword skills page.
    4. Return path to final merged PDF.
    Falls back to original PDF on any failure.
    """
    try:
        import config.profile
        importlib.reload(config.profile)

        profile    = getattr(config.profile, "PROFILE",         {})
        my_skills  = getattr(config.profile, "MY_SKILLS",       [])
        tech_exp   = getattr(config.profile, "TECH_EXPERIENCE", {})

        # ── 1. Skill matching ─────────────────────────────────────────────
        jd_lower      = job_description.lower()
        matched_skills = [s for s in my_skills if s.lower() in jd_lower] or my_skills[:6]
        print(f"[ATS TAILOR] Matched skills for {company} — {role}: {matched_skills}")

        # ── 2. Output paths ───────────────────────────────────────────────
        base_dir   = os.path.dirname(os.path.abspath(__file__))
        custom_dir = os.path.join(base_dir, "resume", "customized")
        os.makedirs(custom_dir, exist_ok=True)

        safe = lambda s: "".join(c for c in s if c.isalnum() or c in " _").strip().replace(" ", "_")
        temp_skills_pdf = os.path.join(custom_dir, f"skills_{safe(company)}_{safe(role)}.pdf")
        final_pdf_path  = os.path.join(custom_dir, f"{safe(company)}_{safe(role)}_resume.pdf")

        # ── 3. Extract resume text & get Gemini summary ──────────────────
        new_summary = None
        if os.path.exists(original_pdf_path):
            resume_text = _extract_pdf_text(original_pdf_path)
            new_summary = _gemini_rewrite_summary(resume_text, job_description, company, role)
            if new_summary:
                print(f"[ATS TAILOR] Generated tailored summary: {new_summary[:80]}...")
        else:
            print(f"[ATS TAILOR][WARN] Original PDF not found: {original_pdf_path}")
            return original_pdf_path

        # ── 4. Build ATS keyword skills page (ReportLab) ─────────────────
        styles    = getSampleStyleSheet()
        title_sty = ParagraphStyle("T", parent=styles["Heading1"], fontName="Helvetica-Bold",
                                    fontSize=15, textColor=colors.HexColor("#0f172a"), spaceAfter=12)
        sub_sty   = ParagraphStyle("S", parent=styles["Heading2"], fontName="Helvetica-Bold",
                                    fontSize=11, textColor=colors.HexColor("#2563eb"), spaceAfter=8)
        body_sty  = ParagraphStyle("B", parent=styles["BodyText"], fontName="Helvetica",
                                    fontSize=10, textColor=colors.HexColor("#334155"), spaceAfter=6)
        th_sty    = ParagraphStyle("TH", fontName="Helvetica-Bold", fontSize=9, textColor=colors.white)
        td_sty    = ParagraphStyle("TD", fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#1e293b"))

        elements = []
        cand = f"{profile.get('first_name','Pratik')} {profile.get('last_name','Pawar')}"
        elements.append(Paragraph(f"{cand} — Role-Specific Competencies", title_sty))
        elements.append(Paragraph(f"Position: <b>{role}</b> at <b>{company}</b>", body_sty))
        elements.append(Spacer(1, 10))

        if new_summary:
            elements.append(Paragraph("<b>AI-Tailored Professional Summary:</b>", sub_sty))
            elements.append(Paragraph(new_summary, body_sty))
            elements.append(Spacer(1, 10))

        elements.append(Paragraph("<b>Technical Competency Matrix:</b>", sub_sty))
        table_data = [[
            Paragraph("Skill", th_sty),
            Paragraph("Experience", th_sty),
            Paragraph("Application", th_sty),
        ]]
        for skill in matched_skills:
            exp_yrs = tech_exp.get(skill.lower(), profile.get("total_experience_years", "4.6"))
            table_data.append([
                Paragraph(f"<b>{skill}</b>", td_sty),
                Paragraph(f"{exp_yrs} yrs", td_sty),
                Paragraph("Data pipelines, ETL automation, cloud-scale deployments.", td_sty),
            ])

        tbl = Table(table_data, colWidths=[120, 75, 330])
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#1e293b")),
            ("ALIGN",         (0, 0), (-1, -1), "LEFT"),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
            ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ]))
        elements.append(tbl)

        doc = SimpleDocTemplate(temp_skills_pdf, pagesize=letter,
                                rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
        doc.build(elements)

        # ── 5. Merge original + skills page ──────────────────────────────
        reader = PdfReader(original_pdf_path)
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        for page in PdfReader(temp_skills_pdf).pages:
            writer.add_page(page)
        with open(final_pdf_path, "wb") as f:
            writer.write(f)

        try:
            os.remove(temp_skills_pdf)
        except Exception:
            pass

        print(f"[ATS TAILOR][OK] Tailored resume created at: {final_pdf_path}")
        return final_pdf_path

    except Exception as e:
        print(f"[ATS TAILOR][ERROR] Failed: {e}")
        return original_pdf_path
