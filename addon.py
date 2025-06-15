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
    "version": "4.2.0",
    "name": "Internet Archive (Movies)",
    "description": "Provides movie streams from The Internet Archive.",
    "types": ["movie"],
    "resources": ["stream"],
    "idPrefixes": ["tt"]
}

# --- SERIES ADDON MANIFEST ---
SERIES_MANIFEST = {
    "id": "org.yourname.internet-archive-series",
    "version": "4.2.0",
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
@app.route('/<base>/stream/<type>/<id>.json')
def stream(base, type, id):
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

    search_results = []
    if type == 'movie':
        search_query = f'({title}) AND year:({year}) AND mediatype:(movies)'
        search_results = search_archive(search_query)
    else: # type == 'series'
        season_num, episode_num = id.split(':')[1:]
        s_e_simple = f'S{int(season_num):02d}E{int(episode_num):02d}'
        
        # --- NEW TWO-PASS SEARCH LOGIC ---
        print(f"--- INFO (Series): Attempting specific search for {title} {s_e_simple}... ---")
        specific_query = f'("{title} {s_e_simple}")'
        search_results = search_archive(specific_query)
        
        # If the specific search fails, fall back to a broad search
        if not search_results:
            print(f"--- INFO (Series): Specific search failed, trying broad search... ---")
            broad_query = f'({title}) AND year:({year})'
            search_results = search_archive(broad_query)

    valid_streams = []
    VIDEO_FILE_REGEX = re.compile(r'.*\.(mkv|mp4|avi|mov)$', re.IGNORECASE)

    for result in search_results:
        identifier = result.get('identifier')
        if not identifier: continue

        files = get_archive_files(identifier)
        for f in files:
            filename = f.get('name')
            if filename and VIDEO_FILE_REGEX.match(filename):
                if type == 'series':
                    season_num, episode_num = id.split(':')[1:]
                    s_e_pattern = f'[Ss]{int(season_num):02d}[._- ]?[EeXx]{int(episode_num):02d}|{int(season_num):d}[._- ]?[EeXx]{int(episode_num):02d}'
                    # If we found this via a specific search, we can be less strict
                    # But for now, we'll keep the filter to ensure relevance
                    if not re.search(s_e_pattern, filename):
                        continue
                
                valid_streams.append({
                    "name": "Internet Archive",
                    "title": filename,
                    "url": f"https://archive.org/download/{identifier}/{filename.replace(' ', '%20')}"
                })

    print(f"INFO: Returning {len(valid_streams)} streams for {title} ({year})")
    return jsonify({"streams": valid_streams})

def search_archive(query):
    search_url = "https://archive.org/advancedsearch.php"
    # Added 'television' and 'vids' to collections for better series coverage
    full_query = f'{query} AND (mediatype:(movies) OR collection:(television OR televisionseries OR vids))'
    params = {'q': full_query, 'fl[]': 'identifier', 'rows': '10', 'output': 'json'}
    print(f"INFO: Searching Archive.org with query: [{full_query}]")
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

if __name__ == "__main__":
    app.run(debug=True)
