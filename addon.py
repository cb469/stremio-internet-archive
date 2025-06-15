from flask import Flask, jsonify
from flask_cors import CORS
from internetarchive import search_items, get_item
import os
import re

app = Flask(__name__)
CORS(app)

# --- ADDON MANIFEST (with new name) ---
MANIFEST = {
    "id": "org.yourname.archive-streams",
    "version": "1.5.0",
    "name": "Internet Archive Streams", # <--- RENAMED AS REQUESTED
    "description": "Provides streams from The Internet Archive.",
    "types": ["movie", "series"],
    "resources": ["stream"],
    "idPrefixes": ["tt"]
}

# --- REGEX FOR FILE MATCHING ---
VIDEO_FILE_REGEX = re.compile(r'.*\.(mkv|mp4|avi|mov)$', re.IGNORECASE)

# --- ENDPOINTS ---
@app.route('/manifest.json')
def manifest():
    return jsonify(MANIFEST)

@app.route('/stream/<type>/<id>.json')
def stream(type, id):
    # This is a hardcoded test. It IGNORES the movie you click.
    # It will ALWAYS search for "Night of the Living Dead".
    # This helps us see if the core search functionality is working.
    
    print("--- 1. Stream function initiated. ---")

    try:
        # STEP 1: Define the hardcoded search query
        search_query = '("Night of the Living Dead" OR NightOfTheLivingDead) AND mediatype:movies'
        print(f"--- 2. Hardcoded search query is: [{search_query}] ---")

        # STEP 2: Search Internet Archive
        search_results = list(search_items(search_query, fields=['identifier', 'title']))
        print(f"--- 3. Internet Archive search found {len(search_results)} result(s). ---")

        if not search_results:
            print("--- 4. No results found. Ending process. ---")
            return jsonify({"streams": []})

        # STEP 3: Get the first item's identifier
        item_id = search_results[0]['identifier']
        print(f"--- 4. Using top result with identifier: [{item_id}] ---")

        # STEP 4: Get file list for that item
        item_details = get_item(item_id)
        streams = []
        print("--- 5. Searching for video files in the item... ---")
        
        for f in item_details.files:
            if VIDEO_FILE_REGEX.match(f['name']):
                stream_object = {
                    "name": "Archive.org",
                    "title": f.get('title', f['name']),
                    "url": f"https://archive.org/download/{item_id}/{f['name']}"
                }
                streams.append(stream_object)
                print(f"--- Found a valid video file: {f['name']} ---")
        
        print(f"--- 6. Found a total of {len(streams)} video files. Returning to Stremio. ---")
        return jsonify({"streams": streams})

    except Exception as e:
        print(f"--- FATAL ERROR: An exception occurred: {e} ---")
        return jsonify({"streams": []})

if __name__ == "__main__":
    app.run(debug=True)
