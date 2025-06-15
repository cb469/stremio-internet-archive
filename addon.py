from flask import Flask, jsonify
from flask_cors import CORS
import requests # Using the standard requests library for reliability
import os
import re

app = Flask(__name__)
CORS(app)

# --- CONFIGURATION ---
TMDB_API_KEY = os.environ.get('TMDB_API_KEY')
TMDB_API_URL = "https://api.themoviedb.org/3"

# --- ADDON MANIFEST ---
MANIFEST = {
    "id": "org.yourname.internet-archive-streams",
    "version": "2.0.0", # Major version change
    "name": "Internet Archive Streams", # As requested
    "description": "Finds streams for movies and series on The Internet Archive.",
    "types": ["movie", "series"],
    "resources": ["stream"],
    "idPrefixes": ["tt"]
}

# --- REGEX FOR FILE MATCHING ---
VIDEO_FILE_REGEX = re.compile(r'.*\.(mkv|mp4|avi|mov)$', re.IGNORECASE)

# --- HELPER FUNCTIONS ---
def search_archive(query):
    """Performs a direct web request to the Internet Archive search API."""
    # This is the public API endpoint for searching the archive
    search_url = "https://archive.org/advancedsearch.php"
    params = {
        'q': query,
        'fl[]': 'identifier', # We only need the unique identifier
        'rows': '5',          # Limit to 5 results for speed
        'output': 'json'
    }
    print(f"INFO: Searching Archive.org with query: {query}")
    try:
        response = requests.get(search_url, params=params, timeout=10)
        response.raise_for_status() # Raises an error for bad status codes (4xx or 5xx)
        data = response.json()
        docs = data.get('response', {}).get('docs', [])
        print(f"INFO: Archive.org found {len(docs)} documents.")
        return docs
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Could not connect to Archive.org: {e}")
        return []

def get_archive_files(identifier):
    """Gets the list of files for a specific Internet Archive item."""
    metadata_url = f"https://archive.org/metadata/{identifier}"
    print(f"INFO: Getting file list for identifier: {identifier}")
    try:
        response = requests.get(metadata_url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get('files', [])
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Could not get metadata for {identifier}: {e}")
        return []

# --- MAIN ENDPOINT ---
@app.route('/manifest.json')
def manifest():
    return jsonify(MANIFEST)

@app.route('/stream/<type>/<id>.json')
def stream(type, id):
    if not TMDB_API_KEY:
        print("FATAL: TMDB_API_KEY environment variable is not set.")
        return jsonify({"streams": []})

    imdb_id = id.split(':')[0]
    
    # Step 1: Get metadata from TMDB using the IMDb ID
    try:
        # Use TMDB's "find by external id" endpoint
        tmdb_url = f"{TMDB_API_URL}/find/{imdb_id}?api_key={TMDB_API_KEY}&external_source=imdb_id"
        response = requests.get(tmdb_url)
        response.raise_for_status()
        data = response.json()
        
        results = data.get('movie_results', []) if type == 'movie' else data.get('tv_results', [])
        if not results:
            print(f"INFO: TMDB found no results for {imdb_id}")
            return jsonify({"streams": []})

        item = results[0]
        title = item.get('title' if type == 'movie' else 'name')
        year = (item.get('release_date') or item.get('first_air_date', ''))[:4]
        
        if not title or not year:
            print(f"ERROR: Could not get title or year from TMDB for {imdb_id}")
            return jsonify({"streams": []})

    except requests.exceptions.RequestException as e:
        print(f"ERROR: Could not connect to TMDB: {e}")
        return jsonify({"streams": []})

    # Step 2: Search Internet Archive with the title and year
    search_query = f'({title}) AND year:({year}) AND mediatype:(movies)'
    archive_results = search_archive(search_query)

    if not archive_results:
        return jsonify({"streams": []})

    # Step 3: Get files from the best match and create stream links
    best_result_id = archive_results[0].get('identifier')
    if not best_result_id:
        return jsonify({"streams": []})

    files = get_archive_files(best_result_id)
    streams = []
    for f in files:
        filename = f.get('name')
        if filename and VIDEO_FILE_REGEX.match(filename):
            # If it's a series, try to match season/episode
            if type == 'series':
                season_num, episode_num = id.split(':')[1:]
                s_e_match = re.search(f'S0?{season_num}E0?{episode_num}', filename, re.IGNORECASE)
                if not s_e_match:
                    continue # Skip files that don't match the episode

            streams.append({
                "name": "Archive.org",
                "title": filename,
                "url": f"https://archive.org/download/{best_result_id}/{filename}"
            })

    print(f"INFO: Returning {len(streams)} streams for {title} ({year})")
    return jsonify({"streams": streams})

if __name__ == "__main__":
    app.run(debug=True)
