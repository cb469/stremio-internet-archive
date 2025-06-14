from flask import Flask, request, jsonify
from flask_cors import CORS # <--- ADD THIS LINE
from tmdbv3api import TMDb, Movie, TV, Discover
from internetarchive import search_items, get_item
import os
import re

app = Flask(__name__)
CORS(app) # <--- AND ADD THIS LINE

# --- CONFIGURATION ---
# IMPORTANT: You need a TMDB API key for this to work.
# 1. Get a free API key from https://www.themoviedb.org/signup
# 2. Add it as an Environment Variable in Vercel named TMDB_API_KEY
tmdb = TMDb()
tmdb.api_key = os.environ.get('TMDB_API_KEY')
tmdb.language = 'en'

movie = Movie()
tv = TV()
discover = Discover()

# --- ADDON MANIFEST ---
MANIFEST = {
    "id": "org.yourname.archive-tmdb",
    "version": "1.1.0",
    "name": "Archive.org (TMDB)",
    "description": "Finds movies and series on The Internet Archive using TMDB.",
    "types": ["movie", "series"],
    "catalogs": [
        {"type": "movie", "id": "popular-movies", "name": "Popular Movies"},
        {"type": "series", "id": "popular-series", "name": "Popular Series"}
    ],
    "resources": ["catalog", "stream", "meta"],
    "idPrefixes": ["tt"] # This tells Stremio we can handle IMDb IDs
}

# (The rest of the file is exactly the same as before)

# --- REGEX FOR FILE MATCHING ---
VIDEO_FILE_REGEX = re.compile(r'.*\.(mkv|mp4|avi|mov)$', re.IGNORECASE)

def search_archive_for_title(title, year):
    """Searches Internet Archive for a given title and year."""
    search_query = f'"{title}" AND collection:movies AND mediatype:(movies OR etree) AND year:{year}'
    try:
        # We only need the best match, so we limit the search.
        search_results = search_items(search_query, fields=['identifier', 'title'])
        # Return the identifier of the first result if found
        return next(iter(search_results), None)
    except Exception as e:
        print(f"Error searching archive: {e}")
        return None

# --- ENDPOINTS ---
@app.route('/manifest.json')
def manifest():
    return jsonify(MANIFEST)

@app.route('/catalog/<type>/<id>.json')
def catalog(type, id):
    metas = []
    if id == 'popular-movies' and tmdb.api_key:
        results = discover.discover_movies({'sort_by': 'popularity.desc'})
    elif id == 'popular-series' and tmdb.api_key:
        results = discover.discover_tv_shows({'sort_by': 'popularity.desc'})
    else:
        return jsonify({'metas': []})

    for result in results:
        # Stremio uses IMDb IDs, which TMDB provides for items that have one.
        imdb_id = movie.details(result.id).get('imdb_id') or tv.details(result.id).get('imdb_id')
        if imdb_id:
            metas.append({
                "id": imdb_id,
                "type": type,
                "name": result.title if type == 'movie' else result.name,
                "poster": f"https://image.tmdb.org/t/p/w500{result.poster_path}"
            })
    return jsonify({'metas': metas})

@app.route('/meta/<type>/<id>.json')
def meta(type, id):
    """
    Provides metadata for a given IMDb ID.
    Then, searches archive.org for the title to see if a file exists.
    """
    if not tmdb.api_key:
        return jsonify({"meta": {}})

    try:
        if type == 'movie':
            m = movie.details(external_id=id, external_source='imdb_id')
            meta_obj = {
                "id": id,
                "type": "movie",
                "name": m.title,
                "poster": f"https://image.tmdb.org/t/p/w500{m.poster_path}",
                "background": f"https://image.tmdb.org/t/p/original{m.backdrop_path}",
                "description": m.overview,
                "year": m.release_date.split('-')[0] if m.release_date else None,
                "imdbRating": m.vote_average
            }
        else: # series
            s = tv.details(external_id=id, external_source='imdb_id')
            meta_obj = {
                "id": id,
                "type": "series",
                "name": s.name,
                "poster": f"https://image.tmdb.org/t/p/w500{s.poster_path}",
                "background": f"https://image.tmdb.org/t/p/original{s.backdrop_path}",
                "description": s.overview,
                "year": s.first_air_date.split('-')[0] if s.first_air_date else None,
                "imdbRating": s.vote_average,
                "videos": [
                    {
                        "id": f"{id}:{ep.season_number}:{ep.episode_number}",
                        "title": ep.name,
                        "season": ep.season_number,
                        "episode": ep.episode_number,
                        "released": ep.air_date
                    } for season in s.seasons for ep in tv.season(s.id, season.season_number).episodes
                ]
            }
        return jsonify({"meta": meta_obj})
    except Exception as e:
        print(f"Error getting meta from TMDB for {id}: {e}")
        return jsonify({"meta": {}})


@app.route('/stream/<type>/<id>.json')
def stream(type, id):
    """
    Searches archive.org for a title that matches the TMDB entry.
    """
    if not tmdb.api_key:
        return jsonify({"streams": []})

    try:
        title_to_search = None
        year = None
        s_e_match = None

        if type == 'movie':
            imdb_id = id
            m = movie.details(external_id=imdb_id, external_source='imdb_id')
            title_to_search = m.title
            year = m.release_date.split('-')[0] if m.release_date else None
        else: # series
            imdb_id, season_num, episode_num = id.split(':')
            s = tv.details(external_id=imdb_id, external_source='imdb_id')
            title_to_search = s.name
            year = s.first_air_date.split('-')[0] if s.first_air_date else None
            # Regex to find S(season)E(episode), e.g., S01E01
            s_e_match = re.compile(f'S{int(season_num):02d}E{int(episode_num):02d}', re.IGNORECASE)

        if not title_to_search or not year:
            return jsonify({"streams": []})

        archive_item = search_archive_for_title(title_to_search, year)
        if not archive_item:
            return jsonify({"streams": []})

        item_details = get_item(archive_item['identifier'])
        streams = []
        for f in item_details.files:
            if VIDEO_FILE_REGEX.match(f['name']):
                # If it's a series, make sure the file name matches the episode (S01E01)
                if type == 'series' and s_e_match and not s_e_match.search(f['name']):
                    continue # Skip files that don't match the episode pattern

                streams.append({
                    "title": f['name'],
                    "url": f"https://archive.org/download/{archive_item['identifier']}/{f['name']}"
                })
        
        return jsonify({"streams": streams})
    except Exception as e:
        print(f"Error getting stream for {id}: {e}")
        return jsonify({"streams": []})

# Vercel entry point
if __name__ == "__main__":
    app.run(debug=True)
