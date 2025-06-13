from flask import Flask, render_template, request, redirect, url_for, send_file, jsonify, session, flash  
import google.generativeai as genai  
import os  
from dotenv import load_dotenv  
from io import BytesIO  
import PyPDF2  
import docx  
import markdown  
from flask_session import Session  
  
# Load .env  
load_dotenv()  
  
# Configure Gemini API  
api_key = os.getenv("GOOGLE_API_KEY")  
genai.configure(api_key=api_key)  
model = genai.GenerativeModel(model_name="models/gemini-1.5-flash")  
  
app = Flask(__name__)  
app.secret_key = 'secretkey'  
app.config['SESSION_TYPE'] = 'filesystem'  
Session(app)  
  
# PDF Extract  
def extract_text_from_pdf(file_stream):  
    reader = PyPDF2.PdfReader(file_stream)  
    text = ""  
    for page in reader.pages:  
        content = page.extract_text()  
        if content:  
            text += content  
    return text  
  
# TXT Extract  
def extract_text_from_txt(file_stream):  
    return file_stream.read().decode("utf-8")  
  
# DOCX Extract  
def extract_text_from_docx(file_stream):  
    doc = docx.Document(file_stream)  
    text = ""  
    for para in doc.paragraphs:  
        text += para.text + "\n"  
    return text  
  
# Summarizer  
def summarize_text(text, length):  
    if length == "short":  
        prompt = f"Summarize these class notes in 3-4 bullet points:\n\n{text}"  
    elif length == "medium":  
        prompt = f"Summarize these class notes in 100-150 words:\n\n{text}"  
    elif length == "detailed":  
        prompt = f"Summarize these class notes in detailed format:\n\n{text}"  
    else:  
        prompt = f"Summarize these class notes:\n\n{text}"  
  
    response = model.generate_content(prompt)  
    summary_markdown = markdown.markdown(response.text)  
    return summary_markdown  
  
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
            file_ext = filename.split(".")[-1].lower()  
  
            if file_ext == "pdf":  
                original_text = extract_text_from_pdf(file)  
            elif file_ext == "txt":  
                original_text = extract_text_from_txt(file)  
            elif file_ext == "docx":  
                original_text = extract_text_from_docx(file)  
            else:  
                flash("Unsupported file format!")  
                return redirect(url_for('index'))  
  
        elif text_input:  
            original_text = text_input  
  
        else:  
            flash("Please upload a file or paste some text!")  
            return redirect(url_for('index'))  
  
        if original_text:  
            word_count = len(original_text.split())  
            summary = summarize_text(original_text, summary_length)  
            session['summary'] = summary  
            session['original_text'] = original_text  
        else:  
            flash("No readable text found.")  
            return redirect(url_for('index'))  
  
    return render_template("index.html", summary=summary, word_count=word_count)  

@app.route("/chatbot", methods=["POST"])  
def chatbot():  
    data = request.get_json()  
    user_msg = data.get("message", "").strip()  

    if not user_msg:  
        return jsonify({"response": "❗ Please enter a valid message."})  

    if 'summary' not in session:  
        return jsonify({"response": "❗ Please generate a summary first before chatting."})  
  
    # Check session memory (like name, age, etc.)
    if 'memory' not in session:
        session['memory'] = {}

    memory = session['memory']
    
    simple_responses = {  
        "hi": "Hello! 👋 How can I assist with your notes today?",  
        "hello": "Hi there! 🤖",  
        "how are you": "I'm an AI, always operational 🚀. What about you?",  
        "bye": "Goodbye 👋, see you soon!",  
        "what's your work": "I summarize your class notes and answer questions based on them."  
    }  

    lower_msg = user_msg.lower()  
    if lower_msg in simple_responses:  
        bot_reply = simple_responses[lower_msg]  
        session['chat_history'] = session.get('chat_history', "") + f"\nUser: {user_msg}\nBot: {bot_reply}"  
        return jsonify({"response": bot_reply})  

    # If user provides name
    if "my name is" in lower_msg:
        name = user_msg.split("my name is", 1)[1].strip()
        memory['name'] = name
        session.modified = True
        return jsonify({"response": f"Got it, {name}! I'll remember your name."})

    # If user provides age
    if "my age is" in lower_msg:
        age = user_msg.split("my age is", 1)[1].strip()
        memory['age'] = age
        session.modified = True
        return jsonify({"response": f"Got it, you are {age} years old!"})

    # Retrieve stored facts
    if "what is my name" in lower_msg:
        if 'name' in memory:
            return jsonify({"response": f"Your name is {memory['name']}."})
        else:
            return jsonify({"response": "I don't know your name yet!"})

    if "what is my age" in lower_msg:
        if 'age' in memory:
            return jsonify({"response": f"You told me you're {memory['age']} years old."})
        else:
            return jsonify({"response": "I don't know your age yet!"})

    prev_history = session.get("chat_history", "")  
    prompt = f"This is the summary of my class notes:\n{session['summary']}\n\nUser question: {user_msg}\n\nStrictly answer based on the above summary only."  
    full_prompt = prev_history + "\n" + prompt  

    try:  
        response = model.generate_content(full_prompt)  
        bot_reply = response.text.strip()  
        session['chat_history'] = full_prompt + "\nBot: " + bot_reply  
        return jsonify({"response": markdown.markdown(bot_reply)})  

    except Exception as e:  
        return jsonify({"response": f"⚠️ Oops, something went wrong: {str(e)}"})  

@app.route("/memory")  
def memory():  
    return jsonify(dict(session))  
  
if __name__ == "__main__":  
    app.run(debug=True)
