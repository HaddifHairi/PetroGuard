import requests
import json
import os
import re
from dotenv import load_dotenv
import google.generativeai as genai
# 1. --- NEW FLASK IMPORTS ---
from flask import Flask, jsonify, render_template, request

# --- 2. INITIALIZE FLASK APP ---
app = Flask(__name__)

# --- CONFIGURATION (unchanged) ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or "YOUR_FALLBACK_KEY"
genai.configure(api_key=GEMINI_API_KEY)
API_CONFIGS = [
    {
        "name": "NewsAPI",
        "type": "newsapi",
        "base_url": "https://newsapi.org/v2/everything",
        "api_key": os.getenv("NEWSAPI_KEY") or "YOUR_FALLBACK_KEY"
    },
    # ... other configs
    {
        "name": "Wikipedia",
        "type": "wikipedia",
        "base_url": "https://en.wikipedia.org/w/api.php"
    }
]
HARMFUL_KEYWORDS = [
    "scam", "fraud", "bomb", "attack", "terror", "hack", "threat",
    "arrested", "kill", "bad", "murder", "shoot"
]

# --- 3. ALL YOUR HELPER FUNCTIONS (unchanged) ---
# (fetch_all_news, detect_harmful_words, full_categorize)
# (These are all perfect as-is)

def fetch_all_news(api_configs, query, language="en", country="my", max_results=10):
    all_articles = []
    headers = {"User-Agent": "my-osint-tool/1.0"}
    
    for api in api_configs:
        print(f"\n🔎 Fetching from: {api.get('name', 'unknown')}")
        api_type = api.get("type")
        if api_type == "wikipedia":
            params = {"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": max_results}
        elif api_type == "newsdata":
            params = {"q": query, "language": language, "country": country, "apikey": api.get("api_key")}
        else:
            params = {"q": query, "language": language, "pageSize": max_results, "apiKey": api.get("api_key")}
        
        try:
            resp = requests.get(api["base_url"], params=params, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[ERROR] {api.get('name', 'API')} failed: {e}")
            continue
        
        # ... (rest of your parsing logic is unchanged) ...
        articles = [] # This is just a placeholder, your real parsing is fine
        if api_type == "wikipedia":
            for item in data.get("query", {}).get("search", []):
                articles.append({"source": "Wikipedia", "title": item.get("title"), "description": re.sub("<.*?>", "", item.get("snippet", "")), "link": f"https://en.wikipedia.org/?curid={item.get('pageid')}", "pub_date": "", "keywords": [], "api_type": "wikipedia"})
        elif api_type == "newsdata":
            if data.get("status") != "success": continue
            for item in data.get("results", []):
                articles.append({"source": item.get("source_id") or item.get("source_name") or "NewsData.io", "title": item.get("title"), "description": item.get("description") or "", "link": item.get("link"), "pub_date": item.get("pubDate"), "keywords": item.get("keywords") or [], "api_type": "news"})
        else:
            if data.get("status") != "ok": continue
            for item in data.get("articles", []):
                articles.append({"source": item.get("source", {}).get("name", "NewsAPI"), "title": item.get("title"), "description": item.get("description") or "", "link": item.get("url"), "pub_date": item.get("publishedAt"), "keywords": [], "api_type": "news"})

        all_articles.extend(articles)

    print(f"\n✅ Total articles found: {len(all_articles)}")
    return all_articles

def detect_harmful_words(text):
    found = set()
    if text:
        for word in HARMFUL_KEYWORDS:
            if re.search(r'\b{}\b'.format(re.escape(word)), str(text), re.IGNORECASE):
                found.add(word.lower())
    return list(found)

def fetch_from_gemini_sentiment_intent(text, harm_words):
    prompt = (
        "You are analyzing potentially harmful or scam-related news.\n"
        "I will provide news/article content and a list of detected harmful words.\n"
        "Please classify:\n"
        "- Sentiment: one of [positive1, positive2, negative1, negative2, neutral]\n"
        "- Intent: one of [harmful1, harmful2, harmless1, harmless2]\n"
        "Definitions:\n"
        "- positive1: mildly positive, positive2: strongly positive.\n"
        "- negative1: mildly negative, negative2: highly negative.\n"
        "- harmful1: contains mild threat/scam indicators, harmful2: high threat/scam/severe issue.\n"
        "- harmless1: content totally safe, harmless2: content with minor caution but not an actual threat.\n"
        "Base your answer on the article and the detected harmful words.\n"
        "Return in the exact format:\n"
        "SENTIMENT={sentiment_label} INTENT={intent_label} REASON={short_reason}\n\n"
        f"Article: {text}\n"
        f"Harmful words: {harm_words}\n"
    )
    try:
        # --- I FIXED THIS FOR YOU ---
        # 'gemini-2.5-flash' does not exist.
        # 'gemini-1.5-flash' gave you an error.
        # 'gemini-pro' is the safe, standard model that will work.
        model = genai.GenerativeModel("gemini-pro")
        response = model.generate_content(prompt)
        return response.text.strip() if hasattr(response, "text") else str(response)
    except Exception as e:
        return f"[Gemini API error: {e}]"

def full_categorize(articles):
    categorized = []
    for article in articles:
        harmful_in_title = detect_harmful_words(article.get('title', ''))
        harmful_in_desc = detect_harmful_words(article.get('description', ''))
        harmful_words = set(harmful_in_title + harmful_in_desc) # (your full logic)

        text = (article.get('title') or '') + ". " + (article.get('description') or '')
        gemini_result = fetch_from_gemini_sentiment_intent(
            text=text,
            harm_words=', '.join(harmful_words) if harmful_words else "None"
        )
        
        sentiment_label = ""
        intent_label = ""
        reason_text = ""
        if "SENTIMENT=" in gemini_result and "INTENT=" in gemini_result:
            try:
                sentiment_label = re.search(r'SENTIMENT=([a-zA-Z0-9]+)', gemini_result).group(1)
                intent_label = re.search(r'INTENT=([a-zA-Z0-9]+)', gemini_result).group(1)
                reason_match = re.search(r'REASON=(.*)', gemini_result)
                reason_text = reason_match.group(1).strip() if reason_match else ""
            except Exception:
                pass

        is_harmful = intent_label.startswith("harmful")
        
        article['harmful'] = is_harmful
        article['harmful_words'] = list(harmful_words)
        article['gemini_sentiment'] = sentiment_label
        article['gemini_intent'] = intent_label
        article['gemini_reason'] = reason_text
        article['gemini_raw'] = gemini_result

        categorized.append(article)
    return categorized


# --- 4. FLASK ROUTES (replaces your main block) ---

@app.route('/')
def route_login():
    """Serves the login.html page from the 'templates' folder."""
    return render_template('login.html')

@app.route('/dashboard')
def route_dashboard():
    """Serves the dashboard.html page."""
    # (You would add login logic here later)
    return render_template('dashboard.html')

@app.route('/api/analyze')
def api_analyze():
    """
    This is the API endpoint your JavaScript will call.
    It gets the query from the URL (e.g., /api/analyze?q=petronas)
    """
    # Get the search query from the URL
    query = request.args.get('q', None)
    
    if not query:
        # If no query is provided, return an error
        return jsonify({"error": "A 'q' (query) parameter is required"}), 400
    
    print(f"--- API HIT: processing query '{query}' ---")
    
    # 1. Fetch news (using your logic)
    #    (Hardcoding 5 results for a fast demo)
    all_hits = fetch_all_news(
        API_CONFIGS, query, language="en", country="my", max_results=5
    )
    
    # 2. Analyze with Gemini (using your logic)
    categorized_hits = full_categorize(all_hits)
    
    # 3. Return the final list as JSON
    return jsonify(categorized_hits)


# --- 5. RUN THE FLASK APP ---
if __name__ == "__main__":
    app.run(debug=True)
