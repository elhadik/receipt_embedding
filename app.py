import os
import secrets
import uuid
from flask import Flask, render_template, request, jsonify, session
from google import genai
from google.genai import types

from math_validator import validate_math
from duplicate_checker import DuplicateChecker

from dotenv import load_dotenv

# Load env variables
load_dotenv()

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = secrets.token_hex(32)

# Configuration
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB limits
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}

# Initialize services
duplicate_checker = DuplicateChecker()

PROJECT_ID = os.environ.get("PROJECT_ID", "shade-sandbox")
LOCATION = os.environ.get("LOCATION", "us-central1")

def get_genai_client():
    return genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.before_request
def ensure_csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(16)

@app.route('/')
def index():
    return render_template('index.html', csrf_token=session['csrf_token'])

@app.route('/upload', methods=['POST'])
def upload_file():
    # 1. CSRF Verification
    client_csrf = request.headers.get('X-CSRF-Token')
    session_csrf = session.get('csrf_token')
    
    if not session_csrf or client_csrf != session_csrf:
        return jsonify({'error': 'CSRF token validation failed.'}), 403

    # 2. File validation
    if 'receipt' not in request.files:
        return jsonify({'error': 'No file part in request.'}), 400
        
    file = request.files['receipt']
    if file.filename == '':
        return jsonify({'error': 'No selected file.'}), 400
        
    if not allowed_file(file.filename):
        return jsonify({'error': 'Unsupported file type. Permitted: PNG, JPG, JPEG, PDF.'}), 400

    try:
        # Generate secure random filename
        ext = file.filename.rsplit('.', 1)[1].lower()
        secure_name = f"{uuid.uuid4()}.{ext}"
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_name)
        
        # Save file to disk
        file.save(save_path)
        
        # Read file bytes for Gemini call
        with open(save_path, 'rb') as f:
            file_bytes = f.read()

        # Determine MIME type
        mime_type = 'image/png'
        if ext == 'pdf':
            mime_type = 'application/pdf'
        elif ext in ('jpg', 'jpeg'):
            mime_type = 'image/jpeg'

        # 3. Call Gemini 2.5 Flash for OCR Extraction
        prompt = """You are an expert document processing AI specialized in receipt OCR and data extraction. Your task is to analyze the provided image, determine if it is a financial receipt, and extract its data into a structured JSON format.

### Instructions:
1. **Receipt Validation**: First, evaluate whether the image is a receipt, invoice, or bill. Set the `is_receipt` boolean accordingly.
2. **Data Extraction**: If `is_receipt` is true, extract all available fields accurately. Do not assume or hallucinate values. If a field is missing or unreadable, return `null`.
3. **Line Items**: Extract every item line by line, including description, quantity, unit price, and total price if present.
4. **Confidence Score**: Provide an overall confidence score between 0.0 (completely uncertain/unreadable) and 1.0 (perfectly clear and verified) based on the legibility of the text and data completeness.
5. **Output Requirement**: Return ONLY a valid JSON object matching the schema below. Do not wrap the JSON in markdown blocks (like ```json), and do not include any conversational filler text.

### JSON Schema Structure:
{
  "is_receipt": boolean, // true if the image is a receipt/invoice, false otherwise
  "validation_message": string, // "Success" or explanation if it is not a receipt
  "confidence_score": float, // Overal confidence from 0.0 to 1.0
  "receipt_data": {
    "merchant": {
      "name": string or null,
      "address": string or null,
      "phone": string or null,
      "tax_id": string or null // e.g., VAT, EIN, ABN if available
    },
    "transaction": {
      "date": string or null, // Format as YYYY-MM-DD if recognizable
      "time": string or null, // Format as HH:MM:SS if recognizable
      "receipt_number": string or null,
      "currency": string or null // 3-letter ISO code (e.g., USD, EUR, GBP)
    },
    "line_items": [
      {
        "description": string,
        "quantity": number or null,
        "unit_price": float or null,
        "total_price": float or null
      }
    ],
    "financials": {
      "subtotal": float or null,
      "tax_amount": float or null,
      "tip_amount": float or null,
      "discount_amount": float or null,
      "total": float or null
    },
    "payment_method": {
      "type": string or null, // e.g., "Cash", "Credit Card", "Debit Card"
      "card_last_four": string or null
    }
  }
}

### Edge Cases:
- If `is_receipt` is false, set all fields inside `receipt_data` to null or omit them, and provide a clear `validation_message` explaining why (e.g., "Image is a landscape photo, not a receipt")."""

        client = get_genai_client()
        part = types.Part.from_bytes(data=file_bytes, mime_type=mime_type)
        config = types.GenerateContentConfig(response_mime_type="application/json")
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[part, prompt],
            config=config
        )
        
        import json
        extraction_data = json.loads(response.text)
        
        # 4. Check if it is a receipt at all
        is_receipt = extraction_data.get("is_receipt", False)
        if not is_receipt:
            return jsonify({
                'status': 'Rejected',
                'reason': f"Document is not a receipt: {extraction_data.get('validation_message', 'Invalid document format')}",
                'extraction': extraction_data,
                'math_validation': {'is_valid': False, 'errors': ['Not a receipt']},
                'duplicate_check': {'is_duplicate': False}
            })

        # 5. Math Validation check
        math_valid, math_errors = validate_math(extraction_data)
        
        # 6. Duplicate checking (anti-cheating)
        is_duplicate, max_similarity, match_details = duplicate_checker.check_duplicate(extraction_data, save_path)
        
        # 7. Make final verification decision
        if is_duplicate:
            status = "Rejected"
            reason = f"Cheating Attempt: Duplicate submission detected. Matches {match_details.get('file_name')} with {max_similarity*100:.0f}% similarity."
        elif not math_valid:
            status = "Rejected"
            reason = f"Arithmetic Check Failed: {'; '.join(math_errors)}"
        else:
            status = "Approved"
            reason = "Receipt verified successfully. Arithmetic and uniqueness checks passed."
            # Save to CSV only if it is approved (a unique valid submission)
            duplicate_checker.save_submission(extraction_data, save_path)

        return jsonify({
            'status': status,
            'reason': reason,
            'extraction': extraction_data,
            'math_validation': {
                'is_valid': math_valid,
                'errors': math_errors
            },
            'duplicate_check': {
                'is_duplicate': is_duplicate,
                'max_similarity': max_similarity,
                'match_details': match_details
            }
        })

    except Exception as e:
        print(f"Error handling upload: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/history', methods=['GET'])
def get_submission_history():
    try:
        history = duplicate_checker.get_history()
        return jsonify(history)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    )
    return response

if __name__ == '__main__':
    # Listen only on localhost for testing security
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 5000))
    app.run(host=host, port=port, debug=True)
