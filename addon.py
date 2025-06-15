from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import os
import re

app = Flask(__name__)
CORS(app)

# --- CONFIGURATION ---
TMDB_API_KEY = os.environ.get('TMDB_API_KEY')
TMDB_API_URL = "https://api.themoviedb.org/3"

# --- MOVIE ADDON MANIFEST ---
MOVIE_MANIFEST = {
    "id": "org.yourname.internet-archive-movies",
    "version": "4.1.0",
    "name": "Internet Archive (Movies)",
    "description": "Provides movie streams from The Internet Archive.",
    "types": ["movie"],
    "resources": ["stream"],
    "idPrefixes": ["tt"]
}

# --- SERIES ADDON MANIFEST ---
SERIES_MANIFEST = {
    "id": "org.yourname.internet-archive-series",
    "version": "4.1.0",
    "name": "Internet Archive (Series)",
    "description": "Provides series streams from The Internet Archive.",
    "types": ["series"],
    "resources": ["stream"],
    "idPrefixes": ["tt"]
}

# --- USER-FRIENDLY LANDING PAGE ---
@app.route('/')
def landing_page():
    host_name = request.host
    return f"""
    <html>
        <head><title>Internet Archive Addons</title></head>
        <body>
            <h1>Install Your Internet Archive Stremio Addons</h1>
            <p><a href="stremio://{host_name}/movie/manifest.json">Click here to install the MOVIE addon</a></p>
            <p><a href="stremio://{host_name}/series/manifest.json">Click here to install the SERIES addon</a></p>
        </body>
    </html>
    """

# --- MANIFEST ENDPOINTS ---
@app.route('/movie/manifest.json')
def movie_manifest():
    return jsonify(MOVIE_MANIFEST)

@app.route('/series/manifest.json')
def series_manifest():
    return jsonify(SERIES_MANIFEST)


# --- UNIFIED STREAMING LOGIC ---
# This version uses the simpler, more reliable scraping logic from the last working version.
@app.route('/<base>/stream/<type>/<id>.json')
def stream(base, type, id):
    if not TMDB_API_KEY:
        print("FATAL: TMDB_API_KEY environment variable is not set.")
        return jsonify({"streams": []})

    imdb_id = id.split(':')[0]
    
    try:
        tmdb_url = f"{TMDB_API_URL}/find/{imdb_id}?api_key={TMDB_API_KEY}&external_source=imdb_id"
        response = requests.get(tmdb_url)
        response.raise_for_status()
        data = response.json()
        
        results = data.get('movie_results' if type == 'movie' else 'tv_results', [])
        if not results:
            return jsonify({"streams": []})

        item = results[0]
        title = item.get('title' if type == 'movie' else 'name')
        year = (item.get('release_date') or item.get('first_air_date', ''))[:4]
        
        if not title or not year:
            return jsonify({"streams": []})
    except Exception as e:
        print(f"ERROR: Could not get info from TMDB: {e}")
        return jsonify({"streams": []})

    # --- USING THE SIMPLE AND RELIABLE SEARCH LOGIC ---
    if type == 'movie':
        search_query = f'({title}) AND year:({year}) AND mediatype:(movies)'
    else: # type == 'series'
        search_query = f'({title}) AND year:({year})' # More flexible query for TV

    archive_results = search_archive(search_query)

    if not archive_results:
        return jsonify({"streams": []})

    # We only check the first result for simplicity and relevance.
    best_result_id = archive_results[0].get('identifier')
    if not best_result_id:
        return jsonify({"streams": []})

    files = get_archive_files(best_result_id)
    streams = []
    VIDEO_FILE_REGEX = re.compile(r'.*\.(mkv|mp4|avi|mov)$', re.IGNORECASE)

    for f in files:
        filename = f.get('name')
        if filename and VIDEO_FILE_REGEX.match(filename):
            if type == 'series':
                season_num, episode_num = id.split(':')[1:]
                # Simple and effective S/E pattern matching
                s_e_pattern = f'[Ss]{int(season_num):02d}[._- ]?[EeXx]{int(episode_num):02d}|{int(season_num):d}[._- ]?[EeXx]{int(episode_num):02d}'
                if not re.search(s_e_pattern, filename):
                    continue
            
            streams.append({
                "name": "Internet Archive",
                "title": filename,
                "url": f"https://archive.org/download/{best_result_id}/{filename.replace(' ', '%20')}"
            })

    print(f"INFO: Returning {len(streams)} streams for {title} ({year})")
    return jsonify({"streams": streams})

def search_archive(query):
    search_url = "https://archive.org/advancedsearch.php"
    params = {'q': query, 'fl[]': 'identifier', 'rows': '5', 'output': 'json'}
    print(f"INFO: Searching Archive.org with query: [{query}]")
    try:
        response = requests.get(search_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        docs = data.get('response', {}).get('docs', [])
        print(f"INFO: Archive.org found {len(docs)} documents.")
        return docs
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Could not connect to Archive.org: {e}")
        return []

def get_archive_files(identifier):
    metadata_url = f"https://archive.org/metadata/{identifier}"
    print(f"INFO: Getting file list for identifier: {identifier}")
    try:
        response = requests.get(metadata_url, timeout=10)
        response.raise_for_status()
        return response.json().get('files', [])
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Could not get metadata for {identifier}: {e}")
        return []

if __name__ == "__main__":
    app.run(debug=True)
