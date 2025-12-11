"""
Audio Downloader Pro - Web Version
Flask backend with REST API for audio downloading
"""

import os
import sys
import json
import uuid
import threading
import queue
import time
import tempfile
import shutil
import re
import urllib.request
from pathlib import Path
from typing import Dict, Any, Optional, List
from flask import Flask, render_template, request, jsonify, send_file, Response
import yt_dlp

app = Flask(__name__)
app.config['SECRET_KEY'] = 'audio-downloader-secret'

# ---------------------------
# Configuration
# ---------------------------
class Config:
    DOWNLOAD_DIR = str(Path.home() / "Downloads" / "AudioDownloaderWeb")
    TEMP_DIR = tempfile.mkdtemp(prefix="audio_dl_")
    PROVIDERS = {"soundcloud": "scsearch1:", "youtube": "ytsearch1:"}
    FORMATS = ["mp3", "m4a", "flac", "wav"]
    BITRATES = ["320", "256", "192", "128"]

# Ensure directories exist
Path(Config.DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)

# ---------------------------
# Download Queue Manager
# ---------------------------
class DownloadQueue:
    def __init__(self):
        self.items: Dict[str, Dict] = {}
        self.lock = threading.Lock()
    
    def add(self, query: str) -> str:
        item_id = str(uuid.uuid4())[:8]
        with self.lock:
            self.items[item_id] = {
                "id": item_id,
                "query": query,
                "status": "pending",
                "progress": 0,
                "title": query[:50],
                "artist": "",
                "error": None,
                "file_path": None,
                "preview_url": None
            }
        return item_id
    
    def update(self, item_id: str, **kwargs):
        with self.lock:
            if item_id in self.items:
                self.items[item_id].update(kwargs)
    
    def get(self, item_id: str) -> Optional[Dict]:
        return self.items.get(item_id)
    
    def get_all(self) -> list:
        return list(self.items.values())
    
    def clear(self):
        with self.lock:
            self.items = {}

download_queue = DownloadQueue()

# ---------------------------
# Downloader Worker
# ---------------------------
def download_worker(item_id: str, query: str, provider: str, audio_format: str, bitrate: str):
    """Background worker to download audio"""
    try:
        download_queue.update(item_id, status="searching")
        
        is_url = query.startswith('http://') or query.startswith('https://')
        search_prefix = Config.PROVIDERS.get(provider, "scsearch1:")
        
        output_dir = Path(Config.DOWNLOAD_DIR)
        template = "%(artist)s - %(title).100s.%(ext)s"
        
        ydl_opts = {
            # MÁXIMA CALIDAD: descargar el mejor audio disponible
            'format': 'bestaudio/best',
            'format_sort': ['quality', 'abr', 'asr'],
            'format_sort_force': True,
            'outtmpl': str(output_dir / template),
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'writethumbnail': True,
            'progress_hooks': [lambda d: progress_hook(d, item_id)],
            # Postprocesadores con máxima calidad
            'postprocessors': [
                {
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': audio_format,
                    'preferredquality': '320',  # CBR 320kbps
                },
                {'key': 'FFmpegMetadata', 'add_metadata': True},
                {'key': 'EmbedThumbnail'}
            ],
            # Argumentos EXPLÍCITOS para FFmpeg - máxima calidad
            'postprocessor_args': [
                '-b:a', '320k',           # Bitrate 320kbps CBR
                '-ar', '48000',           # Sample rate 48kHz
                '-ac', '2',               # Stereo
            ],
        }
        
        if not is_url:
            ydl_opts['default_search'] = search_prefix.rstrip(':')
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_q = query if is_url else f"{search_prefix}{query}"
            info = ydl.extract_info(search_q, download=False)
            
            if info.get('_type') == 'playlist' and info.get('entries'):
                info = info['entries'][0]
            
            title = info.get('title', query)[:50]
            artist = info.get('artist') or info.get('uploader', 'Unknown')
            webpage_url = info.get('webpage_url', query)
            
            download_queue.update(item_id, 
                                 title=title, 
                                 artist=artist, 
                                 status="downloading",
                                 preview_url=webpage_url)
            
            ydl.download([webpage_url])
            
            # Find downloaded file
            expected_name = f"{artist} - {title[:100]}.{audio_format}"
            file_path = output_dir / expected_name
            
            if not file_path.exists():
                # Try to find any recent file
                files = list(output_dir.glob(f"*.{audio_format}"))
                if files:
                    file_path = max(files, key=os.path.getctime)
            
            download_queue.update(item_id, 
                                 status="complete", 
                                 progress=100,
                                 file_path=str(file_path) if file_path.exists() else None)
            
    except Exception as e:
        download_queue.update(item_id, status="error", error=str(e)[:100])

def progress_hook(d: dict, item_id: str):
    if d.get('status') == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
        done = d.get('downloaded_bytes', 0)
        if total > 0:
            progress = int(done / total * 100)
            download_queue.update(item_id, progress=progress, status="downloading")
    elif d.get('status') == 'finished':
        download_queue.update(item_id, status="processing", progress=95)

def search_songs(query: str, provider: str, limit: int = 12):
    """Search for songs with improved relevance filtering"""
    search_prefix = Config.PROVIDERS.get(provider, "scsearch:")
    
    # Clean query for better results
    clean_query = query.strip()
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': 'in_playlist',
        'nocheckcertificate': True,
        'ignoreerrors': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Search for more results to filter
            search_count = limit * 2  # Get double to filter
            search_query = f"{search_prefix.replace('1:', str(search_count) + ':')}{clean_query}"
            info = ydl.extract_info(search_query, download=False)
            
            results = []
            seen_titles = set()
            entries = info.get('entries', []) if info.get('_type') == 'playlist' else [info]
            
            # Keywords to filter out (covers, remixes, etc. unless in original query)
            query_lower = clean_query.lower()
            skip_keywords = []
            if 'cover' not in query_lower:
                skip_keywords.append('cover')
            if 'remix' not in query_lower:
                skip_keywords.append('remix')
            if 'karaoke' not in query_lower:
                skip_keywords.extend(['karaoke', 'instrumental'])
            if 'live' not in query_lower:
                skip_keywords.append('live')
            
            for entry in entries:
                if entry and len(results) < limit:
                    title = entry.get('title', 'Unknown')
                    title_lower = title.lower()
                    
                    # Skip filtered content
                    if any(kw in title_lower for kw in skip_keywords):
                        continue
                    
                    # Skip duplicates (similar titles)
                    title_key = ''.join(c for c in title_lower if c.isalnum())[:30]
                    if title_key in seen_titles:
                        continue
                    seen_titles.add(title_key)
                    
                    # Format duration
                    duration = entry.get('duration', 0)
                    if duration:
                        mins, secs = divmod(int(duration), 60)
                        duration_str = f"{mins}:{secs:02d}"
                    else:
                        duration_str = "--:--"
                    
                    # Get artist
                    artist = (entry.get('artist') or 
                             entry.get('creator') or 
                             entry.get('uploader') or 
                             entry.get('channel') or 'Unknown')
                    
                    results.append({
                        'id': entry.get('id', ''),
                        'title': title[:70],
                        'artist': artist[:40],
                        'duration': duration_str,
                        'url': entry.get('url') or entry.get('webpage_url', ''),
                        'thumbnail': entry.get('thumbnail', '')
                    })
            
            return results
    except Exception as e:
        print(f"Search error: {e}")
        return []


def scrape_apple_music_playlist(url: str) -> List[Dict]:
    """
    Scrape Apple Music playlist to extract song names.
    Returns list of {title, artist} for each track.
    """
    songs = []
    
    try:
        # Validate URL
        if 'music.apple.com' not in url:
            return []
        
        # Fetch the page
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        
        # Disable SSL verification
        import ssl
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15, context=ssl_context) as response:
            html = response.read().decode('utf-8')
        
        # Method 1: Extract from JSON-LD schema
        json_ld_pattern = r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>'
        json_matches = re.findall(json_ld_pattern, html, re.DOTALL)
        
        for json_str in json_matches:
            try:
                data = json.loads(json_str)
                if isinstance(data, dict) and data.get('@type') == 'MusicPlaylist':
                    tracks = data.get('track', [])
                    for track in tracks:
                        if isinstance(track, dict):
                            name = track.get('name', '')
                            
                            # Try multiple ways to get artist
                            artist = ''
                            if 'byArtist' in track:
                                artist_data = track['byArtist']
                                if isinstance(artist_data, str):
                                    artist = artist_data
                                elif isinstance(artist_data, dict):
                                    artist = artist_data.get('name', '') or artist_data.get('@id', '')
                                elif isinstance(artist_data, list) and artist_data:
                                    first = artist_data[0]
                                    if isinstance(first, str):
                                        artist = first
                                    elif isinstance(first, dict):
                                        artist = first.get('name', '')
                            
                            # Fallback to other fields
                            if not artist:
                                artist = track.get('creator', '') or track.get('author', '')
                            
                            if name:
                                songs.append({
                                    'title': name,
                                    'artist': artist,
                                    'query': f"{artist} - {name}" if artist else name
                                })
            except json.JSONDecodeError:
                continue
        
        # Method 2: Fallback - parse meta tags and song-name classes
        if not songs:
            # Try to find song names in meta tags or specific patterns
            song_patterns = [
                r'data-testid="track-title"[^>]*>([^<]+)</span>',
                r'class="songs-list-row__song-name"[^>]*>([^<]+)<',
                r'"name"\s*:\s*"([^"]+)"[^}]*"@type"\s*:\s*"MusicRecording"',
            ]
            
            for pattern in song_patterns:
                matches = re.findall(pattern, html)
                for match in matches:
                    if match and len(match) > 2:
                        songs.append({
                            'title': match.strip(),
                            'artist': '',
                            'query': match.strip()
                        })
        
        # Remove duplicates
        seen = set()
        unique_songs = []
        for song in songs:
            key = song['query'].lower()
            if key not in seen:
                seen.add(key)
                unique_songs.append(song)
        
        return unique_songs[:50]  # Limit to 50 songs
        
    except Exception as e:
        print(f"Apple Music scrape error: {e}")
        return []


# ---------------------------
# API Routes
# ---------------------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/import-playlist', methods=['POST'])
def import_playlist():
    """Import songs from Apple Music playlist"""
    data = request.json
    url = data.get('url', '').strip()
    
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    
    if 'music.apple.com' not in url:
        return jsonify({"error": "URL must be from music.apple.com"}), 400
    
    songs = scrape_apple_music_playlist(url)
    
    if not songs:
        return jsonify({"error": "Could not extract songs. Make sure the playlist is public."}), 400
    
    return jsonify({
        "success": True,
        "count": len(songs),
        "songs": songs
    })

@app.route('/api/search', methods=['POST'])
def api_search():
    """Search for songs and return results"""
    data = request.json
    query = data.get('query', '').strip()
    provider = data.get('provider', 'soundcloud')
    
    if not query:
        return jsonify({"error": "No query provided"}), 400
    
    results = search_songs(query, provider)
    return jsonify({"results": results})

@app.route('/api/download', methods=['POST'])
def start_download():
    """Start downloading audio"""
    data = request.json
    queries = data.get('queries', [])
    provider = data.get('provider', 'soundcloud')
    audio_format = data.get('format', 'mp3')
    bitrate = data.get('bitrate', '192')
    
    if not queries:
        return jsonify({"error": "No queries provided"}), 400
    
    item_ids = []
    for query in queries:
        query = query.strip()
        if query:
            item_id = download_queue.add(query)
            item_ids.append(item_id)
            threading.Thread(
                target=download_worker,
                args=(item_id, query, provider, audio_format, bitrate),
                daemon=True
            ).start()
    
    return jsonify({"success": True, "items": item_ids})

@app.route('/api/queue')
def get_queue():
    """Get current download queue status"""
    return jsonify(download_queue.get_all())

@app.route('/api/queue/<item_id>')
def get_item(item_id):
    """Get specific item status"""
    item = download_queue.get(item_id)
    if item:
        return jsonify(item)
    return jsonify({"error": "Not found"}), 404

@app.route('/api/queue/clear', methods=['POST'])
def clear_queue():
    """Clear the download queue"""
    download_queue.clear()
    return jsonify({"success": True})

@app.route('/api/preview/<item_id>')
def get_preview(item_id):
    """Get preview audio stream for an item"""
    item = download_queue.get(item_id)
    if not item or not item.get('preview_url'):
        return jsonify({"error": "No preview available"}), 404
    
    # Stream preview using yt-dlp
    try:
        temp_dir = tempfile.mkdtemp()
        temp_file = os.path.join(temp_dir, 'preview.mp3')
        
        ydl_opts = {
            'format': 'worstaudio/worst',
            'outtmpl': temp_file.replace('.mp3', '.%(ext)s'),
            'quiet': True,
            'nocheckcertificate': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '64'
            }]
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([item['preview_url']])
        
        # Find the mp3 file
        import glob
        mp3_files = glob.glob(os.path.join(temp_dir, '*.mp3'))
        if mp3_files:
            return send_file(mp3_files[0], mimetype='audio/mpeg')
        
        return jsonify({"error": "Preview failed"}), 500
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/download-file/<item_id>')
def download_file(item_id):
    """Download the completed file"""
    item = download_queue.get(item_id)
    if not item or not item.get('file_path'):
        return jsonify({"error": "File not found"}), 404
    
    if os.path.exists(item['file_path']):
        return send_file(item['file_path'], as_attachment=True)
    
    return jsonify({"error": "File not found"}), 404

@app.route('/api/metadata', methods=['POST'])
def update_metadata():
    """Update audio file metadata"""
    data = request.json
    file_path = data.get('file_path')
    title = data.get('title')
    artist = data.get('artist')
    album = data.get('album')
    
    if not file_path or not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404
    
    try:
        from mutagen.id3 import ID3, TIT2, TPE1, TPE2, TALB
        from mutagen.mp4 import MP4
        from mutagen.flac import FLAC
        
        ext = Path(file_path).suffix.lower()
        
        if ext == '.mp3':
            try:
                audio = ID3(file_path)
            except:
                audio = ID3()
            if title:
                audio.delall('TIT2')
                audio['TIT2'] = TIT2(encoding=3, text=title)
            if artist:
                audio.delall('TPE1')
                audio.delall('TPE2')
                audio['TPE1'] = TPE1(encoding=3, text=artist)
                audio['TPE2'] = TPE2(encoding=3, text=artist)
            if album:
                audio.delall('TALB')
                audio['TALB'] = TALB(encoding=3, text=album)
            audio.save(file_path, v2_version=3)
            
        elif ext == '.m4a':
            audio = MP4(file_path)
            if title:
                audio['\xa9nam'] = [title]
            if artist:
                audio['\xa9ART'] = [artist]
                audio['aART'] = [artist]
            if album:
                audio['\xa9alb'] = [album]
            audio.save()
            
        elif ext == '.flac':
            audio = FLAC(file_path)
            if title:
                audio['title'] = [title]
            if artist:
                audio['artist'] = [artist]
                audio['albumartist'] = [artist]
            if album:
                audio['album'] = [album]
            audio.save()
        
        return jsonify({"success": True})
        
    except ImportError:
        return jsonify({"error": "mutagen not installed"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/config')
def get_config():
    """Get configuration options"""
    return jsonify({
        "providers": list(Config.PROVIDERS.keys()),
        "formats": Config.FORMATS,
        "bitrates": Config.BITRATES,
        "download_dir": Config.DOWNLOAD_DIR
    })

# ---------------------------
# Main
# ---------------------------
if __name__ == '__main__':
    print("🎵 Audio Downloader Pro - Web Version")
    print("=" * 40)
    print(f"📁 Download folder: {Config.DOWNLOAD_DIR}")
    print(f"🌐 Open: http://localhost:5000")
    print("=" * 40)
    app.run(debug=True, port=5000)
