from flask import Flask, jsonify
from flask_cors import CORS
from tmdbv3api import TMDb, Movie, TV
from internetarchive import search_items, get_item
import os
import re

app = Flask(__name__)
CORS(app)

# --- CONFIGURATION ---
tmdb = TMDb()
tmdb.api_key = os.environ.get('TMDB_API_KEY')
tmdb.language = 'en'

movie = Movie()
tv = TV()

# --- ADDON MANIFEST ---
MANIFEST = {
    "id": "org.yourname.archive-provider-debug",
    "version": "1.4.0-debug",
    "name": "Archive.org Provider (DEBUG)",
    "description": "Debug version for finding streams on The Internet Archive.",
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
    print("--- LOG: Stream request received ---")
    print(f"Request type: {type}, Request ID: {id}")

    # --- STEP 1: Check for TMDB API Key ---
    if not tmdb.api_key:
        print("--- FATAL: TMDB_API_KEY environment variable is not set. Exiting. ---")
        return jsonify({"streams": []})
    print("--- LOG: TMDB API Key is present. ---")

    # --- STEP 2: Get Title and Year (DEBUGGING OVERRIDE) ---
    title_to_search = None
    year = None
    
    # FOR DEBUGGING: We will IGNORE the movie you clicked on and ALWAYS search for "The Kid".
    # This tells us if the Internet Archive search itself is the problem.
    if type == 'movie':
        print("--- DEBUG OVERRIDE: Forcing search for 'The Kid' (1921) ---")
        title_to_search = "The Kid"
        year = "1921"
    else: # For series, we'll keep the original logic for now
        try:
            imdb_id, season_num, episode_num = id.split(':')
            s = tv.details(external_id=imdb_id, external_source='imdb_id')
            title_to_search = s.name
            year = s.first_air_date.split('-')[0] if s.first_air_date else None
            print(f"--- LOG: Series info from TMDB: {title_to_search} ({year}) ---")
        except Exception as e:
            print(f"--- ERROR: Could not get series info from TMDB: {e} ---")
            return jsonify({"streams": []})

    if not title_to_search or not year:
        print("--- FATAL: Could not determine a title or year to search for. Exiting. ---")
        return jsonify({"streams": []})

    # --- STEP 3: Search Internet Archive ---
    search_query = f'{title_to_search} {year} AND mediatype:movies'
    print(f"--- LOG: Performing search on Internet Archive with query: [{search_query}] ---")
    
    try:
        search_results = search_items(search_query, fields=['identifier', 'title'])
        # We need to convert the generator to a list to see the results
        results_list = list(search_results)
        print(f"--- LOG: Internet Archive search returned {len(results_list)} results. ---")
        if results_list:
            print(f"--- LOG: Top result: {results_list[0]} ---")
            archive_item = results_list[0]
        else:
            archive_item = None
            
    except Exception as e:
        print(f"--- FATAL: Exception during Internet Archive search: {e} ---")
        return jsonify({"streams": []})

    # --- STEP 4: Process Results ---
    if not archive_item:
        print("--- LOG: No items found on Archive.org matching the query. Exiting. ---")
        return jsonify({"streams": []})

    item_id = archive_item['identifier']
    print(f"--- LOG: Found matching item. Getting file list for identifier: {item_id} ---")
    
    item_details = get_item(item_id)
    streams = []
    for f in item_details.files:
        if VIDEO_FILE_REGEX.match(f['name']):
            print(f"--- LOG: Found video file: {f['name']} ---")
            streams.append({
                "name": "Archive.org",
                "title": f.get('title', f['name']),
                "url": f"https://archive.org/download/{item_id}/{f['name']}"
            })
            
    print(f"--- LOG: Found a total of {len(streams)} stream(s). Returning to Stremio. ---")
    return jsonify({"streams": streams})

if __name__ == "__main__":
    app.run(debug=True)
