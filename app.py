from flask import Flask, render_template, request, jsonify
from google.cloud import storage
import os
import uuid
import base64 # Import base64 for encoding image data
from PIL import Image # Import Pillow for image processing
from io import BytesIO # Import BytesIO to handle image in memory
from datetime import datetime # Import datetime for timestamps
import time # Import time for performance measurement
from PIL import ImageOps # Import ImageOps for EXIF transpose
import threading # Import threading for cache lock
from google.cloud import firestore # Import firestore
import subprocess # Import subprocess to run shell commands
from googleapiclient import discovery # Import Google Sheets API v4
from dotenv import load_dotenv # Import dotenv for loading .env file

# Load environment variables from .env file
load_dotenv()


app = Flask(__name__)

# Initialize Firestore DB
db = firestore.Client(database="image-voting")

# In-memory cache for image UUIDs and their extensions
# This cache will store a dictionary of {uuid: extension}
image_uuid_cache = {"data": {}, "timestamp": datetime.min}
# In-memory cache for image likes
# This cache will store a dictionary of {uuid: {likes: count, timestamp: datetime}}
image_likes_cache = {"data": {}, "timestamp": datetime.min}

# In-memory cache for Google Sheets profile data
# This cache will store profile data with timestamp
profile_cache = {"data": None, "timestamp": datetime.min}

# In-memory cache for Google Sheets team data
# This cache will store team data with timestamp
team_cache = {"data": None, "timestamp": datetime.min}

CACHE_EXPIRATION_SECONDS = 2
PROFILE_CACHE_EXPIRATION_SECONDS = 300  # 5 minutes for profile data
TEAM_CACHE_EXPIRATION_SECONDS = 300  # 5 minutes for team data
cache_lock = threading.Lock() # Lock for thread-safe cache access

def require_password(f):
    """Decorator to require password authentication for API endpoints."""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get password from URL parameter
        password = request.args.get('password')
        
        if not password:
            return jsonify({"error": "Password required"}), 401
        
        try:
            # Verify password from Firestore - search for student account
            try:
                credentials_ref = db.collection('credentials')
                query = credentials_ref.where('account', '==', 'student')
                docs = query.get()
                
                if not docs:
                    return jsonify({"error": "Student credentials not found"}), 404
                
                # Get the first matching document
                doc = docs[0]
                doc_data = doc.to_dict()
                stored_password = doc_data.get('password')
                
                if password != stored_password:
                    return jsonify({"error": "Invalid password"}), 401
            except Exception as firestore_error:
                print(f"{datetime.now().strftime('%H:%M:%S')} ERROR: Firestore access failed: {firestore_error}", flush=True)
                return jsonify({"error": "Authentication service unavailable"}), 500
                
        except Exception as e:
            print(f"{datetime.now().strftime('%H:%M:%S')} ERROR: Password verification failed: {e}", flush=True)
            import traceback
            print(f"{datetime.now().strftime('%H:%M:%S')} EXCEPTION TRACEBACK:", flush=True)
            print(traceback.format_exc(), flush=True)
            return jsonify({"error": "Authentication failed"}), 500
        
        return f(*args, **kwargs)
    return decorated_function

# Configure Google Cloud Storage
# For Google Cloud Storage and Firestore, use default credentials from the environment
# (service account associated with the deployment environment)
storage_client = storage.Client()

# Environment variable validation
BUCKET_NAME = os.environ.get('GCS_BUCKET_NAME')
if not BUCKET_NAME:
    raise ValueError("GCS_BUCKET_NAME environment variable is required")

SHEET_ID = os.environ.get('GOOGLE_SHEETS_ID')
if not SHEET_ID:
    raise ValueError("GOOGLE_SHEETS_ID environment variable is required")

TEAM_SHEET_ID = os.environ.get('TEAM_SHEETS_ID')
if not TEAM_SHEET_ID:
    raise ValueError("TEAM_SHEETS_ID environment variable is required")

GOOGLE_SHEETS_CREDENTIALS_FILE = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
if not GOOGLE_SHEETS_CREDENTIALS_FILE:
    raise ValueError("GOOGLE_APPLICATION_CREDENTIALS environment variable is required")

GCS_FOLDER = "20250901" # The folder within the bucket for original images
GCS_CACHED_FOLDER = "20250901_cached" # The folder for cached images in GCS
LOCAL_CACHE_DIR = "/tmp/cached" # Local directory for caching images

# Google Sheets configuration
SHEET_RANGE = "Form Responses 1!A1:I999"  # Adjust range as needed

# Team Sheets configuration
TEAM_SHEET_RANGE = "A2:Z999"  # The first row is comment that should be skipped



@app.route('/')
def index():
    return render_template('index.html')

def _get_image_data_and_description(uuid_only: str, original_file_extension: str, bucket: storage.Bucket):
    """
    Helper function to retrieve image data and description, with caching logic.
    Handles image processing for response (RGB conversion) without re-caching.
    """
    print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: _get_image_data_and_description received uuid_only: {uuid_only}, extension: {original_file_extension}", flush=True)
    
    full_filename = uuid_only + original_file_extension
    
    original_blob = None
    all_blobs_in_original_folder = bucket.list_blobs(prefix=f"{GCS_FOLDER}/")
    for b in all_blobs_in_original_folder:
        blob_name_without_folder = b.name.replace(f"{GCS_FOLDER}/", "", 1)
        if blob_name_without_folder == full_filename: # Match the full filename
            original_blob = b
            break

    if not original_blob:
        print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: No original image blob found for filename: {full_filename}.", flush=True)
        return None, None, None # Indicate not found

    image_mimetype = original_blob.content_type if original_blob.content_type else 'application/octet-stream'
    
    local_cached_image_path = os.path.join(LOCAL_CACHE_DIR, full_filename)
    gcs_cached_blob_name = os.path.join(GCS_CACHED_FOLDER, full_filename)
    gcs_cached_blob = bucket.blob(gcs_cached_blob_name)
    
    image_data_raw = None # Raw image data before processing

    # 1. Try to retrieve from local cache first
    if os.path.exists(local_cached_image_path):
        print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Found local cached image: {local_cached_image_path}", flush=True)
        with open(local_cached_image_path, 'rb') as f:
            image_data_raw = f.read()
    else:
        print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Local cached image not found for filename: {full_filename}. Checking GCS cache.", flush=True)
        
        # 2. Try to retrieve from GCS cache
        if gcs_cached_blob.exists():
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Found GCS cached blob: {gcs_cached_blob.name}. Downloading to local cache.", flush=True)
            image_data_raw = gcs_cached_blob.download_as_bytes()
            # Save to local cache
            with open(local_cached_image_path, 'wb') as f:
                f.write(image_data_raw)
        else:
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: GCS cached blob not found for filename: {full_filename}. Retrieving original from GCS.", flush=True)
            # 3. If not in GCS cache, download original image data
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Found original blob: {original_blob.name}. Creating cached versions (local and GCS).", flush=True)
            
            image_data_raw = original_blob.download_as_bytes() # Use raw data for processing
            
            # Upload the original image to GCS cache and save to local cache
            gcs_cached_blob.upload_from_file(BytesIO(image_data_raw), content_type=image_mimetype)
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Uploaded to GCS cache: {gcs_cached_blob.name}", flush=True)
            with open(local_cached_image_path, 'wb') as f:
                f.write(image_data_raw)
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Saved to local cache: {local_cached_image_path}", flush=True)

    if not image_data_raw:
        return None, None, None # Indicate data could not be retrieved
        
    # Process image (convert to RGB if necessary) before encoding for response
    image_data_to_encode = image_data_raw
    try:
        img = Image.open(BytesIO(image_data_raw))
        img = ImageOps.exif_transpose(img) # Apply EXIF orientation
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        processed_img_byte_arr = BytesIO()
        # Save in original format if possible, otherwise infer from extension
        save_format = img.format if img.format else original_file_extension[1:].upper()
        img.save(processed_img_byte_arr, format=save_format)
        processed_img_byte_arr.seek(0)
        image_data_to_encode = processed_img_byte_arr.getvalue()
    except Exception as img_e:
        print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Image processing failed for {full_filename}: {img_e}. Using raw image data.", flush=True)
        # If processing fails, fall back to raw image data
        image_data_to_encode = image_data_raw

    encoded_image_data = base64.b64encode(image_data_to_encode).decode('utf-8')

    # Fetch the corresponding description file
    # Description file name is now UUID + original_extension + .txt
    description_filename = full_filename + '.txt'
    local_description_path = os.path.join(LOCAL_CACHE_DIR, description_filename)
    description_text = ""

    # 1. Try to retrieve description from local cache first
    if os.path.exists(local_description_path):
        print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Found local cached description: {local_description_path}", flush=True)
        with open(local_description_path, 'r', encoding='utf-8') as f:
            description_text = f.read()
    else:
        print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Local cached description not found for filename: {full_filename}. Retrieving from GCS.", flush=True)
        description_blob_name = os.path.join(GCS_FOLDER, description_filename)
        description_blob = bucket.blob(description_blob_name)
        
        if description_blob.exists():
            description_text = description_blob.download_as_text()
            # Save to local cache
            with open(local_description_path, 'w', encoding='utf-8') as f:
                f.write(description_text)
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Saved description to local cache: {local_description_path}", flush=True)
        else:
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Description blob not found in GCS for filename: {full_filename}.", flush=True)

    return encoded_image_data, image_mimetype, description_text

def _get_likes_from_firestore(filename_without_extension: str) -> int:
    """
    Retrieves the like count for a given image from Firestore, with per-item caching.
    """
    global image_likes_cache
    with cache_lock:
        # Check if cache is still valid and contains the specific image's likes
        if filename_without_extension in image_likes_cache["data"] and \
           (datetime.now() - image_likes_cache["data"][filename_without_extension]["timestamp"]).total_seconds() < CACHE_EXPIRATION_SECONDS:
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Using cached likes for {filename_without_extension}.", flush=True)
            return image_likes_cache["data"][filename_without_extension]["likes"]

        print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Cache expired or not set for likes. Fetching likes for {filename_without_extension} from Firestore.", flush=True)
        try:
            doc_ref = db.collection("images").document(filename_without_extension)
            doc = doc_ref.get()
            if doc.exists:
                likes = doc.to_dict().get("likes", 0)
            else:
                # If document doesn't exist, initialize it with 0 likes
                doc_ref.set({"likes": 0, "filename": filename_without_extension})
                likes = 0
            
            # Update cache for this specific image
            image_likes_cache["data"][filename_without_extension] = {"likes": likes, "timestamp": datetime.now()}
            return likes
        except Exception as e:
            print(f"{datetime.now().strftime('%H:%M:%S')} ERROR: Failed to get likes from Firestore for {filename_without_extension}: {e}", flush=True)
            return 0 # Return 0 likes on error


@app.route('/image/<filename>') # Renamed parameter to clarify it's just the UUID
def get_image(filename): # filename here is the UUID part only
    print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: get_image received filename (UUID): {filename}", flush=True)
    try:
        bucket = storage_client.bucket(BUCKET_NAME) # Initialize bucket here
        
        # Get the extension from the cache or by listing blobs
        image_uuids_with_extensions = get_cached_image_uuids_with_extensions(bucket)
        original_file_extension = image_uuids_with_extensions.get(filename)
        
        if not original_file_extension:
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Extension not found for UUID: {filename}.", flush=True)
            return jsonify({"error": "Image not found or could not be retrieved"}), 404

        encoded_image_data, image_mimetype, description_text = _get_image_data_and_description(filename, original_file_extension, bucket)
        likes = _get_likes_from_firestore(filename) # Get likes from Firestore

        if encoded_image_data is None:
            return jsonify({"error": "Image not found or could not be retrieved"}), 404

        return jsonify({
            "image_data": encoded_image_data,
            "image_mimetype": image_mimetype,
            "description": description_text,
            "likes": likes # Include likes in the response
        })
    except Exception as e:
        print(f"{datetime.now().strftime('%H:%M:%S')} ERROR: get_image failed: {e}", flush=True)
        return jsonify({"error": str(e)}), 404

@app.route('/upload', methods=['POST'])
def upload_image():
    print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: upload_image called", flush=True)
    if 'image' not in request.files:
        return jsonify({"error": "No image file provided"}), 400
    if 'description' not in request.form:
        return jsonify({"error": "No description provided"}), 400

    image_file = request.files['image']
    description = request.form['description']

    if image_file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    if image_file:
        try:
            gcs_folder_str: str = GCS_FOLDER

            # Get original file extension
            original_filename = image_file.filename if image_file.filename else ""
            file_extension = os.path.splitext(original_filename)[1].lower()
            if not file_extension:
                # Attempt to infer extension from mimetype if not present in filename
                if image_file.mimetype and 'image/' in image_file.mimetype:
                    file_extension = '.' + image_file.mimetype.split('/')[-1]
                else:
                    file_extension = ".bin" # Fallback for unknown type

            unique_filename_base = str(uuid.uuid4()) # Always generate a new UUID
            unique_filename = unique_filename_base + file_extension # Preserve original extension

            blob_name = os.path.join(gcs_folder_str, unique_filename)
            blob = storage_client.bucket(BUCKET_NAME).blob(blob_name)

            # Upload the image file as is
            image_file.stream.seek(0) # Ensure stream is at the beginning
            blob.upload_from_file(image_file.stream, content_type=image_file.mimetype)

            # Store the description in a separate text file with the image's full unique filename + .txt
            description_blob_name = os.path.join(gcs_folder_str, unique_filename + '.txt')
            description_blob = storage_client.bucket(BUCKET_NAME).blob(description_blob_name)
            description_blob.upload_from_string(description)

            return jsonify({
                "message": f"Image and description uploaded successfully to gs://{BUCKET_NAME}/{blob_name}",
                "description": description,
                "uuid": unique_filename.split('.')[0] # Return only the UUID part
            }), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"error": "Something went wrong"}), 500

def get_cached_image_uuids_with_extensions(bucket: storage.Bucket):
    """
    Retrieves image UUIDs and their extensions from cache or GCS, with expiration.
    """
    global image_uuid_cache
    with cache_lock:
        # Check if cache is still valid
        if (datetime.now() - image_uuid_cache["timestamp"]).total_seconds() < CACHE_EXPIRATION_SECONDS:
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Using cached image UUIDs.", flush=True)
            return image_uuid_cache["data"]

        print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Cache expired or not set. Fetching image UUIDs from GCS.", flush=True)
        
        # Fetch from GCS
        all_blobs_in_original_folder = bucket.list_blobs(prefix=f"{GCS_FOLDER}/")
        
        new_image_uuids_with_extensions = {} # Store UUID and original extension
        for blob in all_blobs_in_original_folder:
            blob_name_without_folder = blob.name.replace(f"{GCS_FOLDER}/", "", 1)
            if '.' in blob_name_without_folder and not blob_name_without_folder.endswith('.txt'):
                uuid_part, ext_part = os.path.splitext(blob_name_without_folder)
                new_image_uuids_with_extensions[uuid_part] = ext_part
        
        # Update cache
        image_uuid_cache["data"] = new_image_uuids_with_extensions
        image_uuid_cache["timestamp"] = datetime.now()
        print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Image UUIDs cache updated.", flush=True)
        return new_image_uuids_with_extensions

@app.route('/images/all')
def get_all_images():
    print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: get_all_images called", flush=True)
    try:
        bucket = storage_client.bucket(BUCKET_NAME)
        
        # Use the caching function to get image UUIDs
        image_uuids_with_extensions = get_cached_image_uuids_with_extensions(bucket)
        
        all_images_data = []
        for uuid_only, original_file_extension in sorted(image_uuids_with_extensions.items()): # Sort for consistent order
            try:
                encoded_image_data, image_mimetype, description_text = _get_image_data_and_description(uuid_only, original_file_extension, bucket)

                if encoded_image_data is None:
                    print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Image data could not be retrieved for UUID: {uuid_only}. Skipping.", flush=True)
                    continue # Skip this UUID if image data is not available

                likes = _get_likes_from_firestore(uuid_only) # Get likes from Firestore
                all_images_data.append({
                    "uuid": uuid_only,
                    "image_data": encoded_image_data,
                    "image_mimetype": image_mimetype,
                    "description": description_text,
                    "likes": likes # Include likes in the response
                })
            except Exception as e:
                print(f"{datetime.now().strftime('%H:%M:%S')} ERROR: Failed to process image {uuid_only}: {e}", flush=True)
                # Continue to next image even if one fails
                
        return jsonify({"images": all_images_data}), 200
    except Exception as e:
        print(f"{datetime.now().strftime('%H:%M:%S')} ERROR: get_all_images failed: {e}", flush=True)
        return jsonify({"error": str(e)}), 500

@app.route('/like_image', methods=['POST'])
def like_image():
    print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: like_image called", flush=True)
    data = request.get_json()
    image_uuid = data.get('uuid')

    if not image_uuid:
        return jsonify({"error": "Image UUID not provided"}), 400

    try:
        doc_ref = db.collection("images").document(image_uuid)
        doc = doc_ref.get()

        if doc.exists:
            current_likes = doc.to_dict().get("likes", 0)
            new_likes = current_likes + 1
            doc_ref.update({"likes": new_likes})
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Image {image_uuid} liked. New count: {new_likes}", flush=True)
            # Update the likes cache immediately for this specific image
            with cache_lock:
                image_likes_cache["data"][image_uuid] = {"likes": new_likes, "timestamp": datetime.now()}
            return jsonify({"message": "Image liked successfully", "new_likes": new_likes}), 200
        else:
            # If document doesn't exist, create it with 1 like
            doc_ref.set({"likes": 1, "filename": image_uuid})
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Image {image_uuid} liked (new entry). New count: 1", flush=True)
            # Update the likes cache immediately for this specific image
            with cache_lock:
                image_likes_cache["data"][image_uuid] = {"likes": 1, "timestamp": datetime.now()}
            return jsonify({"message": "Image liked successfully (new entry)", "new_likes": 1}), 200
    except Exception as e:
        print(f"{datetime.now().strftime('%H:%M:%S')} ERROR: Failed to like image {image_uuid}: {e}", flush=True)
        return jsonify({"error": str(e)}), 500

@app.route('/images/top10_liked')
def get_top10_liked_images():
    print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: get_top10_liked_images called", flush=True)
    try:
        bucket = storage_client.bucket(BUCKET_NAME)
        
        # Get all image UUIDs and extensions (from cache or GCS)
        image_uuids_with_extensions = get_cached_image_uuids_with_extensions(bucket)
        
        top_images_data = []
        
        # Query Firestore for top 10 liked images
        docs = db.collection("images").order_by("likes", direction=firestore.Query.DESCENDING).limit(10).stream()
        
        for doc in docs:
            image_uuid = doc.id
            likes = doc.to_dict().get("likes", 0)
            
            original_file_extension = image_uuids_with_extensions.get(image_uuid)
            
            if not original_file_extension:
                print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Extension not found for UUID: {image_uuid} in top 10 list. Skipping.", flush=True)
                continue
            
            try:
                encoded_image_data, image_mimetype, description_text = _get_image_data_and_description(image_uuid, original_file_extension, bucket)

                if encoded_image_data is None:
                    print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Image data could not be retrieved for UUID: {image_uuid} in top 10 list. Skipping.", flush=True)
                    continue

                top_images_data.append({
                    "uuid": image_uuid,
                    "image_data": encoded_image_data,
                    "image_mimetype": image_mimetype,
                    "description": description_text,
                    "likes": likes
                })
            except Exception as e:
                print(f"{datetime.now().strftime('%H:%M:%S')} ERROR: Failed to process top image {image_uuid}: {e}", flush=True)
                # Continue to next image even if one fails
                
        return jsonify({"images": top_images_data}), 200
    except Exception as e:
        print(f"{datetime.now().strftime('%H:%M:%S')} ERROR: get_top10_liked_images failed: {e}", flush=True)
        return jsonify({"error": str(e)}), 500

@app.route('/init', methods=['GET'])
def initialize_data():
    print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: initialize_data called", flush=True)
    confirm = request.args.get('confirm')
    password = request.args.get('password')

    # Check password if provided
    if password:
        try:
            # Get admin credentials from Firestore
            admin_docs = db.collection("credentials").where("account", "==", "admin").limit(1).stream()
            admin_doc = None
            for doc in admin_docs:
                admin_doc = doc
                break
            
            if not admin_doc:
                return jsonify({"error": "Admin credentials not found in Firestore"}), 401
            
            stored_password = admin_doc.to_dict().get("password")
            if not stored_password:
                return jsonify({"error": "Password field not found in admin credentials"}), 401
            
            if password != stored_password:
                return jsonify({"error": "Invalid password"}), 401
                
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Password verification successful", flush=True)
        except Exception as e:
            print(f"{datetime.now().strftime('%H:%M:%S')} ERROR: Password verification failed: {e}", flush=True)
            return jsonify({"error": f"Password verification failed: {e}"}), 500

    if confirm is None:
        try:
            bucket = storage_client.bucket(BUCKET_NAME)
            
            # Count GCS original folder entries
            gcs_original_count = sum(1 for _ in bucket.list_blobs(prefix=f"{GCS_FOLDER}/"))
            
            # Count GCS cached folder entries
            gcs_cached_count = sum(1 for _ in bucket.list_blobs(prefix=f"{GCS_CACHED_FOLDER}/"))
            
            # Count Firestore "images" collection entries
            firestore_count = sum(1 for _ in db.collection("images").stream())

            return render_template('confirm_init.html', 
                                   gcs_original_count=gcs_original_count,
                                   gcs_cached_count=gcs_cached_count,
                                   firestore_count=firestore_count)
        except Exception as e:
            print(f"{datetime.now().strftime('%H:%M:%S')} ERROR: Failed to get counts for initialization confirmation: {e}", flush=True)
            return jsonify({"error": f"Failed to retrieve current data counts: {e}"}), 500
    elif confirm == 'no':
        return jsonify({"message": "Initialization cancelled."}), 200
    elif confirm != 'yes':
        return jsonify({"message": "Initialization not confirmed. Please add '?confirm=yes' to the URL to proceed."}), 400

    try:
        bucket = storage_client.bucket(BUCKET_NAME)

        # Clean GCS original folder
        blobs_to_delete = bucket.list_blobs(prefix=f"{GCS_FOLDER}/")
        for blob in blobs_to_delete:
            blob.delete()
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Deleted GCS original blob: {blob.name}", flush=True)

        # Clean GCS cached folder
        blobs_to_delete = bucket.list_blobs(prefix=f"{GCS_CACHED_FOLDER}/")
        for blob in blobs_to_delete:
            blob.delete()
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Deleted GCS cached blob: {blob.name}", flush=True)

        # Clean Firestore "images" collection
        docs = db.collection("images").stream()
        for doc in docs:
            doc.reference.delete()
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Deleted Firestore document: {doc.id}", flush=True)

        # Clear in-memory caches
        with cache_lock:
            image_uuid_cache["data"] = {}
            image_uuid_cache["timestamp"] = datetime.min
            image_likes_cache["data"] = {}
            image_likes_cache["timestamp"] = datetime.min
        print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: In-memory caches cleared.", flush=True)

        # Clean local cache directory
        if os.path.exists(LOCAL_CACHE_DIR):
            for filename in os.listdir(LOCAL_CACHE_DIR):
                file_path = os.path.join(LOCAL_CACHE_DIR, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        # This should not happen if LOCAL_CACHE_DIR only contains files, but for safety
                        import shutil
                        shutil.rmtree(file_path)
                    print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Deleted local cached file: {file_path}", flush=True)
                except Exception as e:
                    print(f"{datetime.now().strftime('%H:%M:%S')} ERROR: Failed to delete {file_path}. Reason: {e}", flush=True)
        else:
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Local cache directory {LOCAL_CACHE_DIR} does not exist. Skipping cleanup.", flush=True)

        return jsonify({"message": "All data (GCS, Firestore, caches) initialized successfully"}), 200
    except Exception as e:
        print(f"{datetime.now().strftime('%H:%M:%S')} ERROR: Initialization failed: {e}", flush=True)
        return jsonify({"error": str(e)}), 500

def get_profile_data_from_sheets():
    """
    Retrieves profile data from Google Sheets with caching using Google Sheets API v4.
    """
    global profile_cache
    with cache_lock:
        # Check if cache is still valid
        if (datetime.now() - profile_cache["timestamp"]).total_seconds() < PROFILE_CACHE_EXPIRATION_SECONDS and profile_cache["data"] is not None:
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Using cached profile data.", flush=True)
            return profile_cache["data"]

        print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Cache expired or not set. Fetching profile data from Google Sheets.", flush=True)
        
        try:
            # Import service account credentials for Google Sheets API only
            from google.oauth2 import service_account
            
            # Load credentials from file for Google Sheets API
            credentials = service_account.Credentials.from_service_account_file(
                GOOGLE_SHEETS_CREDENTIALS_FILE,
                scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
            )
            
            # Build Google Sheets API service
            discovery_url = ('https://sheets.googleapis.com/$discovery/rest?version=v4')
            service = discovery.build('sheets', 'v4', credentials=credentials, discoveryServiceUrl=discovery_url)
            
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Using Google Sheets API v4 with credentials from {GOOGLE_SHEETS_CREDENTIALS_FILE}", flush=True)
            
            # Get spreadsheet data
            result = service.spreadsheets().values().get(
                spreadsheetId=SHEET_ID, 
                range=SHEET_RANGE, 
                majorDimension='ROWS'
            ).execute()
            
            all_values = result.get('values', [])
            
            if not all_values or len(all_values) < 2:
                print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: No data found in Google Sheets.", flush=True)
                return {"headers": [], "profiles": []}
            
            # First row contains headers
            headers = all_values[0]
            # Rest of the rows contain profile data
            profiles = all_values[1:]
            
            # Filter out empty rows
            profiles = [profile for profile in profiles if any(cell.strip() for cell in profile)]
            
            profile_data = {
                "headers": headers,
                "profiles": profiles
            }
            
            # Update cache
            profile_cache["data"] = profile_data
            profile_cache["timestamp"] = datetime.now()
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Profile data cache updated.", flush=True)
            
            return profile_data
            
        except Exception as e:
            print(f"{datetime.now().strftime('%H:%M:%S')} ERROR: Failed to fetch profile data from Google Sheets: {e}", flush=True)
            import traceback
            print(f"{datetime.now().strftime('%H:%M:%S')} EXCEPTION TRACEBACK:", flush=True)
            print(traceback.format_exc(), flush=True)
            # Return cached data if available, otherwise empty data
            if profile_cache["data"] is not None:
                return profile_cache["data"]
            return {"headers": [], "profiles": []}

def get_team_data_from_sheets():
    """
    Fetch team data from Google Sheets with caching.
    Returns a dictionary with 'headers' and 'teams' keys.
    """
    global team_cache
    with cache_lock:
        # Check if cache is still valid
        if (datetime.now() - team_cache["timestamp"]).total_seconds() < TEAM_CACHE_EXPIRATION_SECONDS and team_cache["data"] is not None:
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Using cached team data.", flush=True)
            return team_cache["data"]

        print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Cache expired or not set. Fetching team data from Google Sheets.", flush=True)
        
        try:
            # Import service account credentials for Google Sheets API only
            from google.oauth2 import service_account
            
            # Load credentials from file for Google Sheets API
            credentials = service_account.Credentials.from_service_account_file(
                GOOGLE_SHEETS_CREDENTIALS_FILE,
                scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
            )
            
            # Build Google Sheets API service
            discovery_url = ('https://sheets.googleapis.com/$discovery/rest?version=v4')
            service = discovery.build('sheets', 'v4', credentials=credentials, discoveryServiceUrl=discovery_url)
            
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Using Google Sheets API v4 with credentials from {GOOGLE_SHEETS_CREDENTIALS_FILE}", flush=True)
            
            # Get spreadsheet data
            result = service.spreadsheets().values().get(
                spreadsheetId=TEAM_SHEET_ID, 
                range=TEAM_SHEET_RANGE, 
                majorDimension='ROWS'
            ).execute()
            
            all_values = result.get('values', [])
            
            if not all_values or len(all_values) < 2:
                print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: No team data found in Google Sheets.", flush=True)
                return {"headers": [], "teams": []}
            
            # First row contains headers
            headers = all_values[0]
            # Rest of the rows contain team data
            teams = all_values[1:]
            
            # Since first row is comment, assume column positions
            # Based on the API response, columns are: 팀(조) 번호, 인원, 현재 실제 인원, 팀장, 팀장 학번, 팀원1, 팀원2, 팀원3, 팀원4, 팀원5, 주제 발표 일정, 주제는 여기
            team_number_index = 0  # First column is team number
            team_leader_index = 3   # Fourth column is team leader
            
            # Filter teams that have a valid team number
            filtered_teams = []
            for team in teams:
                if len(team) > team_number_index and team[team_number_index].strip():
                    # Check if team number is a valid number
                    team_number = team[team_number_index].strip()
                    if team_number.isdigit() and int(team_number) > 0:
                        filtered_teams.append(team)
            
            teams = filtered_teams
            
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Found {len(teams)} teams with valid team numbers.", flush=True)
            for team in teams:
                if len(team) > team_number_index:
                    print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Team {team[team_number_index]} found", flush=True)
            
            team_data = {
                "headers": headers,
                "teams": teams
            }
            
            # Update cache
            team_cache["data"] = team_data
            team_cache["timestamp"] = datetime.now()
            print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: Team data cache updated.", flush=True)
            
            return team_data
            
        except Exception as e:
            print(f"{datetime.now().strftime('%H:%M:%S')} ERROR: Failed to fetch team data from Google Sheets: {e}", flush=True)
            import traceback
            print(f"{datetime.now().strftime('%H:%M:%S')} EXCEPTION TRACEBACK:", flush=True)
            print(traceback.format_exc(), flush=True)
            # Return cached data if available, otherwise empty data
            if team_cache["data"] is not None:
                return team_cache["data"]
            return {"headers": [], "teams": []}

@app.route('/profile_viewer')
def profile_viewer():
    """Route to serve the profile viewer HTML page."""
    return render_template('profile_viewer.html')

@app.route('/team_viewer')
def team_viewer():
    """Route to serve the team viewer HTML page."""
    return render_template('team_viewer.html')

@app.route('/api/profiles')
@require_password
def get_profiles():
    """API endpoint to get profile data from Google Sheets."""
    print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: get_profiles called", flush=True)
    try:
        profile_data = get_profile_data_from_sheets()
        return jsonify(profile_data), 200
    except Exception as e:
        print(f"{datetime.now().strftime('%H:%M:%S')} ERROR: get_profiles failed: {e}", flush=True)
        return jsonify({"error": str(e)}), 500

@app.route('/api/verify_password', methods=['POST'])
def verify_password():
    """API endpoint to verify password from Firestore."""
    print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: verify_password called", flush=True)
    try:
        data = request.get_json()
        password = data.get('password')
        
        if not password:
            return jsonify({"error": "Password is required"}), 400
        
        # Get password from Firestore - search for student account
        try:
            credentials_ref = db.collection('credentials')
            query = credentials_ref.where('account', '==', 'student')
            docs = query.get()
            
            if not docs:
                return jsonify({"error": "Student credentials not found"}), 404
            
            # Get the first matching document
            doc = docs[0]
            doc_data = doc.to_dict()
            stored_password = doc_data.get('password')
            
            if password == stored_password:
                return jsonify({"success": True, "message": "Password verified"}), 200
            else:
                return jsonify({"error": "Invalid password"}), 401
        except Exception as firestore_error:
            print(f"{datetime.now().strftime('%H:%M:%S')} ERROR: Firestore access failed: {firestore_error}", flush=True)
            return jsonify({"error": "Authentication service unavailable"}), 500
            
    except Exception as e:
        print(f"{datetime.now().strftime('%H:%M:%S')} ERROR: verify_password failed: {e}", flush=True)
        import traceback
        print(f"{datetime.now().strftime('%H:%M:%S')} EXCEPTION TRACEBACK:", flush=True)
        print(traceback.format_exc(), flush=True)
        return jsonify({"error": str(e)}), 500

@app.route('/api/teams')
@require_password
def get_teams():
    """API endpoint to get team data from Google Sheets."""
    print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: get_teams called", flush=True)
    try:
        team_data = get_team_data_from_sheets()
        return jsonify(team_data), 200
    except Exception as e:
        print(f"{datetime.now().strftime('%H:%M:%S')} DEBUG: get_teams failed: {e}", flush=True)
        return jsonify({"error": str(e)}), 500

# Ensure the local cache directory exists for temporary files
if not os.path.exists(LOCAL_CACHE_DIR):
    os.makedirs(LOCAL_CACHE_DIR)

# WSGI application entry point
application = app

# Command line execution
if __name__ == '__main__':
    # Development server configuration
    app.run(
        host='0.0.0.0',  # Allow external connections
        port=5000,       # Default Flask port
        debug=True,      # Enable debug mode for development
        threaded=True    # Enable threading for concurrent requests
    )
