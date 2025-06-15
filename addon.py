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

# --- MANIFESTS (No changes here) ---
MOVIE_MANIFEST = { "id": "org.yourname.internet-archive-movies", "version": "4.3.0", "name": "Internet Archive (Movies)", "description": "Provides movie streams from The Internet Archive.", "types": ["movie"], "resources": ["stream"], "idPrefixes": ["tt"] }
SERIES_MANIFEST = { "id": "org.yourname.internet-archive-series", "version": "4.3.0", "name": "Internet Archive (Series)", "description": "Provides series streams from The Internet Archive.", "types": ["series"], "resources": ["stream"], "idPrefixes": ["tt"] }

# --- LANDING PAGE AND MANIFEST ENDPOINTS (No changes here) ---
@app.route('/')
def landing_page():
    host_name = request.host
    return f"""<html><head><title>Internet Archive Addons</title></head><body><h1>Install Your Internet Archive Stremio Addons</h1><p><a href="stremio://{host_name}/movie/manifest.json">Click here to install the MOVIE addon</a></p><p><a href="stremio://{host_name}/series/manifest.json">Click here to install the SERIES addon</a></p></body></html>"""
@app.route('/movie/manifest.json')
def movie_manifest(): return jsonify(MOVIE_MANIFEST)
@app.route('/series/manifest.json')
def series_manifest(): return jsonify(SERIES_MANIFEST)


# --- UNIFIED STREAMING LOGIC ---
@app.route('/<base>/stream/<type>/<id>.json')
def stream(base, type, id):
    print(f"--- LOG: Received request for {type} with id {id} ---")
    if not TMDB_API_KEY:
        print("--- FATAL: TMDB_API_KEY not set. ---")
        return jsonify({"streams": []})

    imdb_id = id.split(':')[0]
    
    try:
        print("--- STEP 1: Getting metadata from TMDB... ---")
        tmdb_url = f"{TMDB_API_URL}/find/{imdb_id}?api_key={TMDB_API_KEY}&external_source=imdb_id"
        response = requests.get(tmdb_url)
        response.raise_for_status()
        data = response.json()
        
        results = data.get('movie_results' if type == 'movie' else 'tv_results', [])
        if not results:
            print("--- FAIL: TMDB found no results. ---")
            return jsonify({"streams": []})

        item = results[0]
        title = item.get('title' if type == 'movie' else 'name')
        year = (item.get('release_date') or item.get('first_air_date', ''))[:4]
        
        if not title or not year:
            print("--- FAIL: Could not get title or year from TMDB. ---")
            return jsonify({"streams": []})
        print(f"--- SUCCESS: Found TMDB info: {title} ({year}) ---")

    except Exception as e:
        print(f"--- FATAL: Error during TMDB request: {e} ---")
        return jsonify({"streams": []})

    search_results = []
    if type == 'movie':
        search_query = f'({title}) AND year:({year}) AND mediatype:(movies)'
        search_results = search_archive(search_query, is_movie=True)
    else: # type == 'series'
        season_num, episode_num = id.split(':')[1:]
        s_e_simple = f'S{int(season_num):02d}E{int(episode_num):02d}'
        
        print("--- STEP 2 (Series): Trying specific search... ---")
        specific_query = f'("{title} {s_e_simple}")'
        search_results = search_archive(specific_query, is_movie=False)
        
        if not search_results:
            print("--- STEP 2 (Series): Specific search failed. Trying broad search... ---")
            broad_query = f'({title}) AND year:({year})'
            search_results = search_archive(broad_query, is_movie=False)

    if not search_results:
        print("--- FAIL: Archive.org search returned no results. ---")
        return jsonify({"streams": []})
    print(f"--- STEP 3: Found {len(search_results)} potential items on Archive.org. Processing... ---")

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
                    season_num, episode_num = int(id.split(':')[1]), int(id.split(':')[2])
                    
                    # --- NEW HYPER-FLEXIBLE REGEX ---
                    patterns = [
                        # S01E05, S01.E05, S01_E05
                        re.compile(f'[Ss]{season_num:02d}[._- ]?[Ee]{episode_num:02d}'),
                        # 1x05, 1x5
                        re.compile(f'[{season_num}][xX]{episode_num:02d}'),
                        re.compile(f'[{season_num}][xX]{episode_num}'),
                        # Season 1 Episode 5
                        re.compile(f'[Ss]eason[._- ]{season_num}[._- ]?[Ee]pisode[._- ]{episode_num}', re.I)
                    ]
                    
                    if not any(p.search(filename) for p in patterns):
                        continue # If no pattern matches, skip this file

                valid_streams.append({ "name": "Internet Archive", "title": filename, "url": f"https://archive.org/download/{identifier}/{filename.replace(' ', '%20')}" })

    print(f"--- SUCCESS: Found {len(valid_streams)} valid stream(s). Returning to Stremio. ---")
    return jsonify({"streams": valid_streams})

# --- Helper functions with improved logic ---
def search_archive(query, is_movie):
    # For series, we now use a much less restrictive query.
    if is_movie:
        full_query = f'{query} AND mediatype:(movies)'
    else:
        full_query = query # Raw keyword search for series

    search_url = "https://archive.org/advancedsearch.php"
    params = {'q': full_query, 'fl[]': 'identifier', 'rows': '10', 'output': 'json'}
    print(f"--- LOG (Search): Querying with: [{full_query}] ---")
    try:
        response = requests.get(search_url, params=params, timeout=10)
        response.raise_for_status()
        return response.json().get('response', {}).get('docs', [])
    except requests.exceptions.RequestException as e:
        print(f"--- FATAL (Search): {e} ---")
        return []

def get_archive_files(identifier):
    metadata_url = f"https://archive.org/metadata/{identifier}"
    try:
        response = requests.get(metadata_url, timeout=10)
        response.raise_for_status()
        return response.json().get('files', [])
    except requests.exceptions.RequestException as e:
        print(f"--- FATAL (Files): {e} ---")
        return []

if __name__ == "__main__":
    app.run(debug=True)
