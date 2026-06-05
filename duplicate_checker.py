import os
import csv
import math
import json
import uuid
from datetime import datetime
from google import genai
import vertexai
from vertexai.vision_models import MultiModalEmbeddingModel, Image

# Setup Project Constants
PROJECT_ID = "shade-sandbox"
LOCATION = "us-central1"

def get_genai_client():
    return genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

def get_receipt_canonical_text(receipt_data):
    """
    Constructs a unique canonical text representation of the receipt data.
    """
    merchant = receipt_data.get("merchant") or {}
    merchant_name = (merchant.get("name") or "unknown").strip().upper()
    
    transaction = receipt_data.get("transaction") or {}
    date = (transaction.get("date") or "unknown").strip()
    time = (transaction.get("time") or "unknown").strip()
    
    financials = receipt_data.get("financials") or {}
    total = financials.get("total")
    total_str = f"{float(total):.2f}" if total is not None else "0.00"
    
    line_items = receipt_data.get("line_items") or []
    items_list = []
    for item in line_items:
        desc = (item.get("description") or "").strip().upper()
        qty = item.get("quantity") or 1
        price = item.get("total_price")
        price_str = f"{float(price):.2f}" if price is not None else "0.00"
        items_list.append(f"{desc}(QTY:{qty},TOT:{price_str})")
        
    items_list.sort()  # Sort items to ensure order-independent similarity
    items_str = ", ".join(items_list)
    
    return f"MERCHANT: {merchant_name} | DATE: {date} | TIME: {time} | TOTAL: {total_str} | ITEMS: {items_str}"

def get_text_embedding(text):
    """
    Generates text embedding using text-embedding-004.
    """
    client = get_genai_client()
    response = client.models.embed_content(
        model="text-embedding-004",
        contents=text
    )
    embeddings = response.embeddings
    if not embeddings:
        raise Exception("Failed to retrieve text embeddings from API")
    return embeddings[0].values

def get_image_embedding(file_path):
    """
    Generates image embedding using multimodalembedding@001.
    """
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    # Ignore deprecation warning by loading model
    model = MultiModalEmbeddingModel.from_pretrained("multimodalembedding@001")
    image = Image.load_from_file(file_path)
    embeddings = model.get_embeddings(image=image)
    if not embeddings or not embeddings.image_embedding:
        raise Exception("Failed to retrieve multimodal image embeddings from API")
    return embeddings.image_embedding

def dot_product(v1, v2):
    return sum(x * y for x, y in zip(v1, v2))

def magnitude(v):
    return math.sqrt(sum(x * x for x in v))

def cosine_similarity(v1, v2):
    mag1 = magnitude(v1)
    mag2 = magnitude(v2)
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot_product(v1, v2) / (mag1 * mag2)

class DuplicateChecker:
    def __init__(self, db_path="submissions.csv"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        if not os.path.exists(self.db_path):
            with open(self.db_path, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "id", "timestamp", "merchant_name", "date", 
                    "total", "file_name", "canonical_text", "embedding_type", "embedding"
                ])

    def check_duplicate(self, data, file_path):
        """
        Checks if the receipt image or metadata is a duplicate.
        Returns:
            (is_duplicate, max_similarity, match_details)
        """
        receipt_data = data.get("receipt_data")
        if not receipt_data:
            return False, 0.0, None
            
        merchant = receipt_data.get("merchant") or {}
        merchant_name = (merchant.get("name") or "").strip().upper()
        
        transaction = receipt_data.get("transaction") or {}
        date = (transaction.get("date") or "").strip()
        
        financials = receipt_data.get("financials") or {}
        total = financials.get("total")
        total_val = float(total) if total is not None else 0.0
        
        # Determine embedding type
        file_name = os.path.basename(file_path)
        ext = file_name.rsplit('.', 1)[1].lower() if '.' in file_name else ''
        embedding_type = 'text' if ext == 'pdf' else 'multimodal'
        
        # Calculate embedding
        if embedding_type == 'multimodal':
            print(f"Generating multimodal image embedding for duplicate check...")
            current_embedding = get_image_embedding(file_path)
        else:
            print(f"Generating text embedding for duplicate check...")
            canonical_text = get_receipt_canonical_text(receipt_data)
            current_embedding = get_text_embedding(canonical_text)
            
        max_similarity = 0.0
        best_match = None
        exact_metadata_match = False
        
        with open(self.db_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # 1. Exact metadata match (always run)
                row_merchant = (row.get("merchant_name") or "").strip().upper()
                row_date = (row.get("date") or "").strip()
                try:
                    row_total = float(row.get("total") or 0.0)
                except ValueError:
                    row_total = 0.0
                    
                if (row_merchant == merchant_name and 
                    row_date == date and 
                    abs(row_total - total_val) < 0.01):
                    exact_metadata_match = True
                    best_match = row
                    max_similarity = 1.0
                    break
                
                # 2. Similarity match (only against same embedding type)
                row_emb_type = row.get("embedding_type") or 'multimodal'
                if row_emb_type == embedding_type:
                    row_emb_str = row.get("embedding")
                    if row_emb_str:
                        try:
                            row_emb = json.loads(row_emb_str)
                            sim = cosine_similarity(current_embedding, row_emb)
                            if sim > max_similarity:
                                max_similarity = sim
                                best_match = row
                        except Exception as e:
                            print(f"Error parsing embedding row: {e}")
                            continue
                            
        # Define thresholds
        # Multimodal image similarity threshold is 0.94 (allows slight lighting/angle differences)
        # Text similarity threshold is 0.97
        threshold = 0.94 if embedding_type == 'multimodal' else 0.97
        is_duplicate = exact_metadata_match or (max_similarity >= threshold)
        
        match_details = None
        if best_match:
            match_details = {
                "id": best_match.get("id"),
                "timestamp": best_match.get("timestamp"),
                "merchant_name": best_match.get("merchant_name"),
                "date": best_match.get("date"),
                "total": best_match.get("total"),
                "file_name": best_match.get("file_name"),
                "similarity": max_similarity,
                "type": "Exact Metadata Match" if exact_metadata_match else "Embedding Similarity Match"
            }
            
        return is_duplicate, max_similarity, match_details

    def save_submission(self, data, file_path):
        """
        Saves a verified unique submission.
        """
        receipt_data = data.get("receipt_data")
        if not receipt_data:
            return
            
        merchant = receipt_data.get("merchant") or {}
        merchant_name = (merchant.get("name") or "").strip()
        
        transaction = receipt_data.get("transaction") or {}
        date = (transaction.get("date") or "").strip()
        
        financials = receipt_data.get("financials") or {}
        total = financials.get("total") or 0.0
        
        # Determine embedding type
        file_name = os.path.basename(file_path)
        ext = file_name.rsplit('.', 1)[1].lower() if '.' in file_name else ''
        embedding_type = 'text' if ext == 'pdf' else 'multimodal'
        
        # Calculate embedding
        if embedding_type == 'multimodal':
            embedding = get_image_embedding(file_path)
            canonical_text = ""
        else:
            canonical_text = get_receipt_canonical_text(receipt_data)
            embedding = get_text_embedding(canonical_text)
            
        submission_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().isoformat()
        
        with open(self.db_path, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                submission_id,
                timestamp,
                merchant_name,
                date,
                total,
                file_name,
                canonical_text,
                embedding_type,
                json.dumps(embedding)
            ])
            
    def get_history(self):
        """
        Returns history of submissions.
        """
        history = []
        if not os.path.exists(self.db_path):
            return history
            
        with open(self.db_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                history.append({
                    "id": row.get("id"),
                    "timestamp": row.get("timestamp"),
                    "merchant_name": row.get("merchant_name"),
                    "date": row.get("date"),
                    "total": row.get("total"),
                    "file_name": row.get("file_name"),
                })
        # Return reversed history to show newest first
        return history[::-1]
