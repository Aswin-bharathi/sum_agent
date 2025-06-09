from flask import Flask, render_template, request, redirect, url_for, flash, jsonifyAdd commentMore actions
import google.generativeai as genai
import os
from dotenv import load_dotenv
from io import BytesIO
import PyPDF2
import docx

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=api_key)
model = genai.GenerativeModel(model_name="models/gemini-1.5-flash")

app = Flask(__name__)
app.secret_key = "supersecretkey"  # For flash messages

def extract_text_from_pdf(file_stream):
    reader = PyPDF2.PdfReader(file_stream)
    text = ""
    for page in reader.pages:
        content = page.extract_text()
        if content:
            text += content
    return text

def extract_text_from_txt(file_stream):
    return file_stream.read().decode("utf-8")

def extract_text_from_docx(file_stream):
    doc = docx.Document(file_stream)
    text = ""
    for para in doc.paragraphs:
        text += para.text + "\n"
    return text

def summarize_text(text, length):
    if length == "short":
        prompt = f"Summarize the following class notes in 3-4 bullet points:\n\n{text}"
    elif length == "medium":
        prompt = f"Summarize the following class notes in a detailed paragraph form around 100-150 words:\n\n{text}"
    elif length == "detailed":
        prompt = f"Summarize the following class notes into a comprehensive, expanded summary covering all important points:\n\n{text}"
    else:
        prompt = f"Summarize the following class notes:\n\n{text}"

    response = model.generate_content(prompt)
    return response.text

@app.route("/", methods=["GET", "POST"])
def index():
    summary = ""
    word_count = 0
    original_text = ""

    if request.method == "POST":
        summary_length = request.form.get("summary_length", "short")
        file = request.files.get("file")
        text_input = request.form.get("text")

        if file and file.filename != "":
            filename = file.filename
            ext = filename.split(".")[-1].lower()
            if ext == "pdf":
                original_text = extract_text_from_pdf(file)
            elif ext == "txt":
                original_text = extract_text_from_txt(file)
            elif ext == "docx":
                original_text = extract_text_from_docx(file)
            else:
                flash("Unsupported file format!", "error")
                return redirect(url_for("index"))
        elif text_input:
            original_text = text_input
        else:
            flash("Please upload a file or paste some text!", "error")
            return redirect(url_for("index"))

        if original_text:
            word_count = len(original_text.split())
            summary = summarize_text(original_text, summary_length)
            return render_template(
                "index.html",
                summary=summary,
                word_count=word_count,
                original_text=original_text
            )
        else:
            flash("No readable text found.", "error")
            return redirect(url_for("index"))

    return render_template("index.html")

@app.route("/chatbot", methods=["POST"])
def chatbot():
    data = request.json
    question = data.get("question")
    summary = data.get("summary")
    if not question or not summary:
        return jsonify({"answer": "Invalid input."})

    prompt = f"Answer this question based on the following summarized notes:\n\nSummary:\n{summary}\n\nQuestion:\n{question}\n\nAnswer:"
    response = model.generate_content(prompt)
    answer = response.text.strip()
    return jsonify({"answer": answer})

if __name__ == "__main__":
    app.run(debug=True)
