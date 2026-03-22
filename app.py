import os
import re

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

try:
    import docx
except ImportError:
    docx = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        return False


load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "supersecretkey")

api_key = os.getenv("GOOGLE_API_KEY")
model_name = None
configured_model_names = []

if api_key and genai:
    genai.configure(api_key=api_key)
    preferred_model = os.getenv("GEMINI_MODEL", "models/gemini-3.1-flash-lite").strip()
    configured_model_names = [
        preferred_model,
        "models/gemini-3.1-flash-lite",
        "gemini-3.1-flash-lite",
        "models/gemini-2.5-flash-lite",
        "gemini-2.5-flash-lite",
        "models/gemini-2.5-flash",
        "gemini-2.5-flash",
    ]
    configured_model_names = list(dict.fromkeys(name for name in configured_model_names if name))
    model_name = configured_model_names[0]


def extract_text_from_pdf(file_stream):
    if PyPDF2 is None:
        raise RuntimeError("PyPDF2 is not installed.")
    reader = PyPDF2.PdfReader(file_stream)
    text = ""
    for page in reader.pages:
        content = page.extract_text()
        if content:
            text += content + "\n"
    return text.strip()


def extract_text_from_txt(file_stream):
    return file_stream.read().decode("utf-8", errors="ignore").strip()


def extract_text_from_docx(file_stream):
    if docx is None:
        raise RuntimeError("python-docx is not installed.")
    document = docx.Document(file_stream)
    return "\n".join(paragraph.text for paragraph in document.paragraphs).strip()


def summarize_text(text, length):
    if not configured_model_names:
        if genai is None:
            raise RuntimeError("google-generativeai is not installed.")
        raise RuntimeError("GOOGLE_API_KEY is not configured.")

    prompts = {
        "short": "Summarize the following class notes in 3-4 bullet points:",
        "medium": "Summarize the following class notes in a detailed paragraph of around 100-150 words:",
        "detailed": "Summarize the following class notes into a comprehensive explanation covering all important points:",
    }
    instruction = prompts.get(length, "Summarize the following class notes:")
    return generate_with_fallback(f"{instruction}\n\n{text}")


def clean_model_text(text):
    cleaned = text.replace("**", "").replace("__", "").replace("`", "")
    cleaned = re.sub(r"^[#>\-\*\s]+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def generate_with_fallback(prompt):
    global model_name

    last_error = None

    for candidate in configured_model_names:
        try:
            response = genai.GenerativeModel(model_name=candidate).generate_content(prompt)
            model_name = candidate
            return clean_model_text((getattr(response, "text", "") or "").strip())
        except Exception as exc:
            last_error = exc
            error_text = str(exc).lower()
            should_try_next = any(
                marker in error_text for marker in ("429", "quota", "rate limit", "not found", "404")
            )
            if not should_try_next:
                raise

    raise RuntimeError(f"All configured Gemini models failed. Last error: {last_error}")


def render_home(**context):
    defaults = {
        "summary": "",
        "word_count": 0,
        "text_input": "",
        "source_text": "",
        "source_name": "",
        "source_type": "text",
        "selected_length": "short",
    }
    defaults.update(context)
    return render_template("index.html", **defaults)


@app.route("/chat", methods=["GET"])
def chat_page():
    return render_template("chat.html")


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        summary = ""
        word_count = 0
        original_text = ""
        source_name = ""
        source_type = "text"
        summary_length = request.form.get("summary_length", "short")
        uploaded_file = request.files.get("file")
        text_input = (request.form.get("text") or "").strip()

        if uploaded_file and uploaded_file.filename:
            filename = uploaded_file.filename
            source_name = filename
            source_type = "file"
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

            try:
                if ext == "pdf":
                    original_text = extract_text_from_pdf(uploaded_file)
                elif ext == "txt":
                    original_text = extract_text_from_txt(uploaded_file)
                elif ext == "docx":
                    original_text = extract_text_from_docx(uploaded_file)
                else:
                    flash("Unsupported file format. Please use PDF, TXT, or DOCX.", "error")
                    return redirect(url_for("index"))
            except Exception as exc:
                flash(f"Could not read the uploaded file: {exc}", "error")
                return redirect(url_for("index"))
        elif text_input:
            original_text = text_input
        else:
            flash("Please upload a file or paste some text.", "error")
            return redirect(url_for("index"))

        if not original_text.strip():
            flash("No readable text found.", "error")
            return redirect(url_for("index"))

        word_count = len(original_text.split())

        try:
            summary = summarize_text(original_text, summary_length)
        except Exception as exc:
            flash(f"Failed to generate summary: {exc}", "error")
            return render_home(
                summary="",
                word_count=word_count,
                text_input=text_input if source_type == "text" else "",
                source_text=original_text,
                source_name=source_name,
                source_type=source_type,
                selected_length=summary_length,
            )

        return render_home(
            summary=summary,
            word_count=word_count,
            text_input=text_input if source_type == "text" else "",
            source_text=original_text,
            source_name=source_name,
            source_type=source_type,
            selected_length=summary_length,
        )

    return render_home(selected_length="short")


@app.route("/chatbot", methods=["POST"])
def chatbot():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    summary = (data.get("summary") or "").strip()
    history = data.get("history") or []

    if not question or not summary:
        return jsonify({"answer": "Invalid input."}), 400

    if not configured_model_names:
        return jsonify({"answer": "GOOGLE_API_KEY is not configured."}), 500

    conversation_context = []
    for item in history[-10:]:
        role = (item.get("role") or "").strip().lower()
        content = clean_model_text((item.get("content") or "").strip())
        if role in {"user", "assistant"} and content:
            label = "User" if role == "user" else "Assistant"
            conversation_context.append(f"{label}: {content}")

    history_block = "\n".join(conversation_context)
    prompt = (
        "You are a helpful study assistant. Answer based on the summary and prior chat context. "
        "Keep the response clean and direct without markdown formatting.\n\n"
        f"Summary:\n{summary}\n\n"
        f"Conversation so far:\n{history_block or 'No previous messages.'}\n\n"
        f"Question:\n{question}\n\n"
        "Answer:"
    )

    try:
        answer = generate_with_fallback(prompt)
    except Exception as exc:
        return jsonify({"answer": f"Failed to get response: {exc}"}), 500

    return jsonify({"answer": answer or "No answer generated."})


if __name__ == "__main__":
    app.run(debug=True)
