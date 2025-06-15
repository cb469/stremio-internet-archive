from flask import Flask, jsonify
from flask_cors import CORS
import requests
import os
import re

app = Flask(__name__)
CORS(app)

# --- CONFIGURATION & FILTERS ---
TMDB_API_KEY = os.environ.get('TMDB_API_KEY')
TMDB_API_URL = "https://api.themoviedb.org/3"

# Relevancy Filters
NEGATIVE_KEYWORDS = ['trailer', 'teaser', 'preview', 'sample', 'featurette', 'screener']
# Size limits are disabled by being set to 0.
MIN_SIZE_MB = 0

# --- ADDON MANIFEST ---
MANIFEST = {
    "id": "org.yourname.internet-archive-streams",
    "version": "2.3.0", # Corrected Search
    "name": "Internet Archive Streams",
    "description": "A smart scraper for finding relevant movie and series streams on The Internet Archive.",
    "types": ["movie", "series"],
    "resources": ["stream"],
    "idPrefixes": ["tt"]
}

# --- REGEX & HELPERS ---
VIDEO_FILE_REGEX = re.compile(r'.*\.(mkv|mp4|avi|mov)$', re.IGNORECASE)

# --- CORRECTED HELPER FUNCTIONS ---
# This function is now back to the simple, working version. It only executes the query.
def search_archive(query):
    search_url = "https://archive.org/advancedsearch.php"
    params = {'q': query, 'fl[]': 'identifier', 'rows': '5', 'output': 'json'}
    print(f"INFO: Searching Archive.org with query: [{query}]")
    try:
        response = requests.get(search_url, params=params, timeout=10)
        response.raise_for_status()
        return response.json().get('response', {}).get('docs', [])
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Could not connect to Archive.org: {e}")
        return []

def get_archive_files(identifier):
    metadata_url = f"https://archive.org/metadata/{identifier}"
    try:
        response = requests.get(metadata_url, timeout=10)
        response.raise_for_status()
        return response.json().get('files', [])
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
        return jsonify({"streams": []})

    imdb_id = id.split(':')[0]
    
    try:
        tmdb_url = f"{TMDB_API_URL}/find/{imdb_id}?api_key={TMDB_API_KEY}&external_source=imdb_id"
        response = requests.get(tmdb_url)
        response.raise_for_status()
        data = response.json()
        
        results = data.get('movie_results' if type == 'movie' else 'tv_results', [])
        if not results: return jsonify({"streams": []})

        item = results[0]
        title = item.get('title' if type == 'movie' else 'name')
        year = (item.get('release_date') or item.get('first_air_date', ''))[:4]
        
        if not title or not year: return jsonify({"streams": []})
    except Exception as e:
        print(f"ERROR: Could not get info from TMDB: {e}")
        return jsonify({"streams": []})

    # --- REVERTED TO THE WORKING SEARCH LOGIC ---
    # The query is now built here, with different logic for movies and series.
    if type == 'movie':
        search_query = f'({title}) AND year:({year}) AND mediatype:(movies)'
    else: # type == 'series'
        search_query = f'({title}) AND year:({year})' # Broader search for series

    search_results = search_archive(search_query)

    valid_streams = []
    # Loop through all found archive items to find the best files
    for result in search_results:
        identifier = result.get('identifier')
        if not identifier: continue

        files = get_archive_files(identifier)

        for f in files:
            filename = f.get('name')
            if not filename or not VIDEO_FILE_REGEX.match(filename):
                continue

            # --- Apply Filters ---
            if any(keyword in filename.lower() for keyword in NEGATIVE_KEYWORDS):
                continue
            
            try: # Disable size filter by checking against 0
                file_size_mb = int(f.get('size', 0)) / (1024*1024)
                if file_size_mb < MIN_SIZE_MB:
                    continue
            except (ValueError, TypeError):
                continue
            
            if type == 'series':
                season_num, episode_num = id.split(':')[1:]
                s_e_pattern = f'[Ss]{int(season_num):02d}[._- ]?[EeXx]{int(episode_num):02d}|{int(season_num):d}[._- ]?[EeXx]{int(episode_num):02d}'
                if not re.search(s_e_pattern, filename):
                    continue

            valid_streams.append({
                "name": "Internet Archive",
                "title": filename,
                "url": f"https://archive.org/download/{identifier}/{filename.replace(' ', '%20')}",
                "_size": int(f.get('size', 0))
            })
    
    # Sort by size (largest file first) and send to Stremio
    sorted_streams = sorted(valid_streams, key=lambda k: k['_size'], reverse=True)
    for s in sorted_streams: del s['_size']

    print(f"INFO: Returning {len(sorted_streams)} relevant streams for {title} ({year})")
    return jsonify({"streams": sorted_streams})

if __name__ == "__main__":
    app.run(debug=True)
