import os
import shutil
import json
import uuid
import threading
import datetime
import re
import sys
import atexit


import webbrowser
import time
import socket
import logging
import logging.handlers
import urllib.parse as urlparse
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import yt_dlp

# ---------------------------------------------------------------------------
# Logging Setup — Enterprise-grade structured logging with rotation
# ---------------------------------------------------------------------------
LOG_DIR = os.path.join(os.path.expanduser('~'), '.yt_downloader_pro', 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger('yt_downloader')
logger.setLevel(logging.DEBUG)

# File handler — rotating 5 MB × 3 backups
_file_handler = logging.handlers.RotatingFileHandler(
    os.path.join(LOG_DIR, 'app.log'),
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding='utf-8',
)
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(logging.Formatter(
    '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
))
logger.addHandler(_file_handler)

# Console handler — only when not frozen (frozen mode has no console)
if not getattr(sys, 'frozen', False):
    _console_handler = logging.StreamHandler(sys.stdout)
    _console_handler.setLevel(logging.INFO)
    _console_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S',
    ))
    logger.addHandler(_console_handler)

# Redirect stdout/stderr to prevent crashes in frozen (hidden console) mode,
# but keep the file logger active so errors are never lost.
class DummyStream:
    def write(self, x): pass
    def flush(self): pass

if getattr(sys, 'frozen', False):
    sys.stdout = DummyStream()
    sys.stderr = DummyStream()

# ---------------------------------------------------------------------------
# Thread-safety primitives
# ---------------------------------------------------------------------------
downloads_lock = threading.Lock()       # Guards the in-memory `downloads` dict
file_io_lock = threading.Lock()         # Guards JSON file read/write operations
shutdown_event = threading.Event()      # Signals background threads to stop
atexit.register(shutdown_event.set)

# Determine base paths
if getattr(sys, 'frozen', False):
    # Running inside a PyInstaller bundle
    BUNDLE_DIR = sys._MEIPASS
    APP_DIR = os.path.dirname(sys.executable)
else:
    # Running in normal Python environment
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
    APP_DIR = BUNDLE_DIR

# Ensure ffmpeg/ffprobe are on the PATH for subprocesses (like yt-dlp)
ffmpeg_dirs = []
for d in [BUNDLE_DIR, APP_DIR]:
    if d and os.path.exists(d):
        if os.path.exists(os.path.join(d, 'ffmpeg.exe')) or os.path.exists(os.path.join(d, 'ffmpeg')):
            ffmpeg_dirs.append(d)

for directory in ffmpeg_dirs:
    if directory not in os.environ.get('PATH', ''):
        os.environ['PATH'] = directory + os.pathsep + os.environ.get('PATH', '')


def is_local_mode():
    if getattr(sys, 'frozen', False):
        return True
    if os.environ.get('PORT') or os.environ.get('RENDER') or os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('GAE_INSTANCE'):
        return False
    return True

def find_free_port(start_port=5000):
    port = start_port
    while port < 65535:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(('127.0.0.1', port))
                return port
            except OSError:
                port += 1
    return start_port

app = Flask(__name__, 
            static_folder=os.path.join(BUNDLE_DIR, 'static'), 
            template_folder=os.path.join(BUNDLE_DIR, 'templates'))
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB request body limit
CORS(app)

# Create a dedicated configuration folder in user's home directory
CONFIG_DIR = os.path.join(os.path.expanduser('~'), '.yt_downloader_pro')
os.makedirs(CONFIG_DIR, exist_ok=True)

# Resolve default download folder to standard system Downloads folder
def get_default_download_dir():
    try:
        home_downloads = os.path.join(os.path.expanduser('~'), 'Downloads')
        if os.path.exists(home_downloads):
            return home_downloads
    except Exception:
        pass
    return os.path.join(APP_DIR, 'downloads')

DOWNLOAD_DIR = get_default_download_dir()
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

HISTORY_FILE = os.path.join(CONFIG_DIR, 'downloads_history.json')
SETTINGS_FILE = os.path.join(CONFIG_DIR, 'settings.json')

# Migrate legacy history and settings files if they exist next to the executable
OLD_HISTORY_FILE = os.path.join(APP_DIR, 'downloads_history.json')
OLD_SETTINGS_FILE = os.path.join(APP_DIR, 'settings.json')

if os.path.exists(OLD_HISTORY_FILE) and not os.path.exists(HISTORY_FILE):
    try:
        shutil.copy2(OLD_HISTORY_FILE, HISTORY_FILE)
    except Exception:
        pass

if os.path.exists(OLD_SETTINGS_FILE) and not os.path.exists(SETTINGS_FILE):
    try:
        shutil.copy2(OLD_SETTINGS_FILE, SETTINGS_FILE)
    except Exception:
        pass

def load_settings():
    default_settings = {
        "locations": [
            {
                "id": "default",
                "name": "Default Downloads",
                "path": DOWNLOAD_DIR,
                "is_default": True
            }
        ]
    }
    with file_io_lock:
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        has_default = any(loc.get('id') == 'default' for loc in data.get('locations', []))
                        if not has_default:
                            data.setdefault('locations', []).append(default_settings['locations'][0])
                        return data
            except Exception as e:
                logger.warning('Failed to load settings: %s', e)
                return default_settings
    return default_settings

def save_json_atomic(filepath, data):
    """Write data to a unique temporary file then atomic rename to prevent corruption."""
    with file_io_lock:
        temp_filepath = f"{filepath}.{uuid.uuid4().hex}.tmp"
        try:
            with open(temp_filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(temp_filepath, filepath)
        except Exception as e:
            if os.path.exists(temp_filepath):
                try:
                    os.remove(temp_filepath)
                except Exception:
                    pass
            logger.error('Failed to save %s: %s', filepath, e)

def save_settings(settings):
    save_json_atomic(SETTINGS_FILE, settings)

# Store download progress in memory — guarded by downloads_lock
downloads = {}

def cleanup_old_downloads():
    """Background thread that removes expired downloads (server mode only).
    Respects shutdown_event for graceful termination."""
    while not shutdown_event.is_set():
        try:
            # Sleep in small increments so we can respond to shutdown quickly
            if shutdown_event.wait(timeout=900):
                break  # shutdown requested
            if is_local_mode():
                continue
                
            history = load_history()
            now = datetime.datetime.now()
            updated_history = []
            changed = False
            
            for item in history:
                try:
                    ts = datetime.datetime.fromisoformat(item.get('timestamp'))
                    age = (now - ts).total_seconds()
                except Exception:
                    # Default to 0 (recent) so unparseable timestamps aren't accidentally deleted
                    age = 0
                    
                if age > 7200:  # 2 hours
                    filepath = item.get('filepath')
                    if filepath and os.path.exists(filepath):
                        try:
                            os.remove(filepath)
                            logger.info('Cleanup: removed expired file %s', filepath)
                        except Exception as e:
                            logger.warning('Cleanup: failed to remove %s: %s', filepath, e)
                    dl_id = item.get('download_id')
                    with downloads_lock:
                        if dl_id in downloads:
                            try:
                                del downloads[dl_id]
                            except Exception:
                                pass
                    changed = True
                else:
                    updated_history.append(item)
                    
            if changed:
                save_history(updated_history)
                logger.info('Cleanup: pruned %d expired items from history', len(history) - len(updated_history))
        except Exception as e:
            logger.error('Error in cleanup thread: %s', e)

def get_ffmpeg_location():
    """Returns directory path containing ffmpeg if available, else None."""
    for d in [BUNDLE_DIR, APP_DIR, os.getcwd()]:
        if d and (os.path.exists(os.path.join(d, 'ffmpeg.exe')) or os.path.exists(os.path.join(d, 'ffmpeg'))):
            return d
    which = shutil.which("ffmpeg")
    if which:
        return os.path.dirname(which)
    return None

def check_ffmpeg():
    return get_ffmpeg_location() is not None

# Strip ANSI color codes — compiled once at module level for optimal performance
ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def clean_ansi(s):
    if not s:
        return ""
    return ANSI_ESCAPE.sub('', s).strip()

def load_history():
    with file_io_lock:
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    return []
            except Exception as e:
                logger.warning('Failed to load history: %s', e)
                return []
    return []

def save_history(history):
    save_json_atomic(HISTORY_FILE, history)

def add_history_item(history_item):
    """Thread-safe and atomic prepend to persistent history."""
    with file_io_lock:
        history = []
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        history = data
            except Exception as e:
                logger.warning('Failed to load history in add_history_item: %s', e)
                history = []
        history.insert(0, history_item)
        temp_filepath = f"{HISTORY_FILE}.{uuid.uuid4().hex}.tmp"
        try:
            with open(temp_filepath, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
            os.replace(temp_filepath, HISTORY_FILE)
        except Exception as e:
            if os.path.exists(temp_filepath):
                try:
                    os.remove(temp_filepath)
                except Exception:
                    pass
            logger.error('Failed to save %s in add_history_item: %s', HISTORY_FILE, e)

def parse_youtube_url(url):
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    parsed = urlparse.urlparse(url)
    video_id = None
    playlist_id = None
    netloc = parsed.netloc.lower()

    if netloc.startswith('www.'):
        netloc = netloc[4:]

    if netloc == 'youtu.be':
        parts = [p for p in parsed.path.split('/') if p]
        if parts:
            video_id = parts[0]
        query = urlparse.parse_qs(parsed.query)
        playlist_id = query.get('list', [None])[0]
    elif netloc == 'youtube.com' or netloc.endswith('.youtube.com'):
        query = urlparse.parse_qs(parsed.query)
        video_id = query.get('v', [None])[0]
        playlist_id = query.get('list', [None])[0]
        if not video_id:
            parts = [p for p in parsed.path.split('/') if p]
            if len(parts) >= 2 and parts[0] in ('shorts', 'live', 'embed', 'v', 'e', 'watch'):
                video_id = parts[1]
            elif len(parts) == 1 and parts[0] not in ('playlist', 'results', 'channel', 'feed', 'c', 'user'):
                if len(parts[0]) == 11 and re.match(r'^[a-zA-Z0-9_-]{11}$', parts[0]):
                    video_id = parts[0]

    # Filter out unviewable/dynamic playlists (e.g. YouTube Mixes, Liked, Watch Later, Uploads radio)
    if playlist_id:
        if playlist_id.startswith('RD') or playlist_id.startswith('UL') or playlist_id in ('WL', 'LL'):
            playlist_id = None

    return video_id, playlist_id

@app.route('/')
def index():
    from flask import render_template
    desktop_app_url = os.environ.get('DESKTOP_APP_URL', '/static/dist/YT_Downloader_Pro.exe')
    return render_template('index.html', desktop_app_url=desktop_app_url)

@app.route('/api/info', methods=['POST'])
def get_info():
    data = request.json
    if not data:
        return jsonify({'error': 'Request body is required', 'code': 'MISSING_BODY'}), 400
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL is required', 'code': 'MISSING_URL'}), 400
    if len(url) > 2048:
        return jsonify({'error': 'URL is too long', 'code': 'URL_TOO_LONG'}), 400
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    logger.info('Fetching info for URL: %s', url[:120])
    video_id, playlist_id = parse_youtube_url(url)
    
    # If it is a playlist-only URL or contains playlist in the path and no video_id
    is_playlist_only = ('playlist' in url) or (playlist_id and not video_id)
    
    ffmpeg_loc = get_ffmpeg_location()
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'ignoreconfig': True,
    }
    if ffmpeg_loc:
        ydl_opts['ffmpeg_location'] = ffmpeg_loc
    
    if is_playlist_only:
        ydl_opts['extract_flat'] = 'in_playlist'
    else:
        ydl_opts['extract_flat'] = False
        ydl_opts['noplaylist'] = True  # Avoid extracting long mix playlists on video urls

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return jsonify({'error': 'Could not extract info from URL', 'code': 'EXTRACTION_FAILED'}), 404
            
            if info.get('_type') == 'playlist':
                entries = []
                for entry in info.get('entries', []):
                    if entry:
                        thumb = None
                        if entry.get('thumbnails'):
                            thumb = entry['thumbnails'][-1].get('url')
                        elif entry.get('thumbnail'):
                            thumb = entry.get('thumbnail')
                        entries.append({
                            'id': entry.get('id'),
                            'title': entry.get('title'),
                            'duration': entry.get('duration'),
                            'thumbnail': thumb
                        })
                return jsonify({
                    'type': 'playlist',
                    'title': info.get('title'),
                    'playlist_id': info.get('id'),
                    'entries': entries,
                    'has_ffmpeg': check_ffmpeg()
                })
            else:
                resolutions = set()
                for f in info.get('formats', []):
                    if f.get('vcodec') != 'none' and f.get('height'):
                        resolutions.add(f.get('height'))
                resolutions = sorted(list(resolutions), reverse=True)
                
                return jsonify({
                    'type': 'video',
                    'title': info.get('title'),
                    'thumbnail': info.get('thumbnail'),
                    'duration': info.get('duration'),
                    'resolutions': resolutions,
                    'video_id': info.get('id'),
                    'associated_playlist': playlist_id if (playlist_id and video_id) else None,
                    'has_ffmpeg': check_ffmpeg()
                })
    except Exception as e:
        logger.error('Failed to extract info for %s: %s', url[:120], e)
        return jsonify({'error': str(e), 'code': 'EXTRACTION_FAILED'}), 500

def parse_time_to_seconds(time_str):
    if time_str is None:
        return None
    if isinstance(time_str, (int, float)):
        return float(time_str)
    time_str = str(time_str).strip()
    if not time_str:
        return None

    # Check if the string uses dot as a time separator (e.g., 03.58 or 1.04.30)
    # We treat dots as colons if:
    # 1. There are multiple dots (e.g., 1.04.30)
    # 2. Or the string matches MM.SS (e.g., 03.58, 1.30, 00.41) where the last part has exactly 2 digits
    if '.' in time_str and ':' not in time_str:
        parts = time_str.split('.')
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 2):
            time_str = time_str.replace('.', ':')

    try:
        # If it's a pure number of seconds (e.g., "45" or "45.5" or "0")
        if ':' not in time_str:
            return float(time_str)
    except ValueError:
        pass

    parts = time_str.split(':')
    try:
        if len(parts) == 2:  # MM:SS
            return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:  # HH:MM:SS
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        pass
    return None


def download_worker(url, download_type, resolution, bitrate, subtitles, download_id, title, thumbnail, duration, location_id=None, start_time=None, end_time=None, embed_metadata=False, client_id=None):
    # Resolve target directory
    settings = load_settings()
    target_dir = DOWNLOAD_DIR
    for loc in settings.get('locations', []):
        if location_id and loc['id'] == location_id:
            target_dir = loc['path']
            break
        elif not location_id and loc.get('is_default'):
            target_dir = loc['path']
            
    try:
        os.makedirs(target_dir, exist_ok=True)
    except Exception as e:
        logger.warning('Could not create target_dir %s: %s. Falling back to %s', target_dir, e, DOWNLOAD_DIR)
        target_dir = DOWNLOAD_DIR
        os.makedirs(target_dir, exist_ok=True)

    with downloads_lock:
        downloads[download_id] = {
            'status': 'downloading',
            'status_text': 'Starting download...',
            'progress': 0,
            'title': title or 'Fetching video info...',
            'thumbnail': thumbnail or '',
            'duration': duration or 0,
            'format': download_type,
            'resolution': resolution,
            'bitrate': bitrate,
            'speed': '0 KiB/s',
            'eta': '00:00',
            'filesize': 'Unknown',
            'cancel_requested': False,
            'client_id': client_id
        }
    
    logger.info('Download started: %s [%s] id=%s', title or url, download_type, download_id)
    
    def my_hook(d):
        with downloads_lock:
            if downloads.get(download_id, {}).get('cancel_requested'):
                raise ValueError("Download aborted by user")
            
        if d['status'] == 'downloading':
            try:
                p = d.get('_percent_str', '0%')
                p = clean_ansi(p).replace('%', '').strip()
                with downloads_lock:
                    downloads[download_id]['progress'] = float(p)
                    downloads[download_id]['status_text'] = f"Downloading... {downloads[download_id]['progress']:.1f}%"
                    downloads[download_id]['speed'] = clean_ansi(d.get('_speed_str', 'N/A'))
                    downloads[download_id]['eta'] = clean_ansi(d.get('_eta_str', 'N/A'))
                    
                    total = d.get('total_bytes') or d.get('total_bytes_estimate')
                    if total:
                        downloads[download_id]['filesize'] = f"{total / (1024 * 1024):.1f} MB"
                    else:
                        downloads[download_id]['filesize'] = clean_ansi(d.get('_total_bytes_str', 'N/A'))
            except Exception:
                pass
        elif d['status'] == 'finished':
            with downloads_lock:
                downloads[download_id]['progress'] = 100
                downloads[download_id]['status_text'] = 'Processing file...'

    def my_pp_hook(d):
        with downloads_lock:
            if downloads.get(download_id, {}).get('cancel_requested'):
                raise ValueError("Download aborted by user")
            status = d.get('status')
            pp_name = d.get('postprocessor', '')
            if status == 'started':
                if 'ExtractAudio' in pp_name:
                    downloads[download_id]['status_text'] = 'Converting audio to MP3...'
                elif 'EmbedThumbnail' in pp_name:
                    downloads[download_id]['status_text'] = 'Embedding cover artwork...'
                elif 'Metadata' in pp_name:
                    downloads[download_id]['status_text'] = 'Embedding tags & chapters...'
                elif 'ThumbnailsConvertor' in pp_name:
                    downloads[download_id]['status_text'] = 'Processing thumbnail image...'
                elif 'Convertor' in pp_name or 'Remuxer' in pp_name:
                    downloads[download_id]['status_text'] = 'Remuxing video & audio...'
                else:
                    downloads[download_id]['status_text'] = 'Processing media with FFmpeg...'

    ffmpeg_loc = get_ffmpeg_location()

    ydl_opts = {
        'outtmpl': os.path.join(target_dir, '%(title)s.%(ext)s'),
        'progress_hooks': [my_hook],
        'postprocessor_hooks': [my_pp_hook],
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'ignoreconfig': True
    }
    if ffmpeg_loc:
        ydl_opts['ffmpeg_location'] = ffmpeg_loc

    # Add trimming options
    start_s = parse_time_to_seconds(start_time)
    end_s = parse_time_to_seconds(end_time)
    if start_s is not None or end_s is not None:
        ydl_opts['force_keyframes_at_cuts'] = True
        # Use default args to capture current values (avoids late-binding closure bug)
        def _make_ranges(s=start_s, e=end_s):
            def _ranges(info_dict, ydl):
                return [{'start_time': s if s is not None else 0.0, 'end_time': e if e is not None else float('inf')}]
            return _ranges
        ydl_opts['download_ranges'] = _make_ranges()

    if download_type == 'mp3':
        if embed_metadata and check_ffmpeg():
            ydl_opts.update({
                'format': 'bestaudio/best',
                'writethumbnail': True,
                'postprocessors': [
                    {
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': str(bitrate or '192'),
                    },
                    {
                        'key': 'FFmpegThumbnailsConvertor',
                        'format': 'jpg',
                    },
                    {
                        'key': 'EmbedThumbnail',
                        'already_have_thumbnail': False,
                    },
                    {
                        'key': 'FFmpegMetadata',
                        'add_chapters': True,
                    }
                ],
            })
        else:
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': str(bitrate or '192'),
                }],
            })
    else: # mp4
        if check_ffmpeg():
            res_str = f"[height<={resolution}]" if resolution else ""
            ydl_opts.update({
                'format': f'bestvideo{res_str}[ext=mp4]+bestaudio[ext=m4a]/bestvideo{res_str}+bestaudio/best{res_str}[ext=mp4]/best{res_str}/best',
                'merge_output_format': 'mp4'
            })
        else:
            res_str = f"[height<={resolution}]" if resolution else ""
            ydl_opts.update({
                'format': f'best{res_str}[ext=mp4]/best{res_str}/best'
            })

    # --- Subtitles (appends to existing postprocessors, never overwrites) ---
    if subtitles:
        ydl_opts['writesubtitles'] = True
        ydl_opts['writeautomaticsub'] = True
        ydl_opts['subtitleslangs'] = ['en', 'es', 'fr', 'de']
        if check_ffmpeg():
            existing_pp = ydl_opts.get('postprocessors', [])
            existing_pp.append({
                'key': 'FFmpegSubtitlesConvertor',
                'format': 'srt',
            })
            ydl_opts['postprocessors'] = existing_pp

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                raise ValueError("Download produced no info from yt-dlp")
            actual_title = info.get('title', title or 'video')
            downloads[download_id]['title'] = actual_title
            
            # Find final path accurately from yt-dlp metadata first
            expected_filename = None
            if info.get('requested_downloads'):
                for req in info['requested_downloads']:
                    if req.get('filepath') and os.path.exists(req['filepath']):
                        expected_filename = req['filepath']
                        break
            if not expected_filename and info.get('filepath') and os.path.exists(info['filepath']):
                expected_filename = info['filepath']
            if not expected_filename and info.get('_filename') and os.path.exists(info['_filename']):
                expected_filename = info['_filename']

            if not expected_filename:
                filename = ydl.prepare_filename(info)
                expected_ext = '.mp3' if download_type == 'mp3' else '.mp4'
                candidate = filename.rsplit('.', 1)[0] + expected_ext
                if os.path.exists(candidate):
                    expected_filename = candidate
                else:
                    # Search matching base
                    base_no_ext = os.path.splitext(os.path.basename(filename))[0]
                    try:
                        for f in os.listdir(target_dir):
                            if f.startswith(base_no_ext) and (f.endswith(download_type) or f.endswith(expected_ext)):
                                expected_filename = os.path.join(target_dir, f)
                                break
                    except Exception as e:
                        logger.warning('Could not list target_dir %s: %s', target_dir, e)
                    if not expected_filename:
                        expected_filename = candidate
                        
            with downloads_lock:
                downloads[download_id]['filepath'] = expected_filename
                basename = os.path.basename(expected_filename)
                downloads[download_id]['filename'] = basename
                downloads[download_id]['status'] = 'completed'
                downloads[download_id]['status_text'] = 'Finished successfully'
            
            logger.info('Download completed: %s -> %s', actual_title, expected_filename)
            
            # Save to persistent history atomically
            history_item = {
                'download_id': download_id,
                'client_id': client_id,
                'title': actual_title,
                'thumbnail': info.get('thumbnail') or thumbnail or '',
                'duration': info.get('duration') or duration or 0,
                'format': download_type,
                'resolution': resolution if download_type == 'mp4' else None,
                'bitrate': bitrate if download_type == 'mp3' else None,
                'filename': basename,
                'filepath': expected_filename,
                'filesize': downloads[download_id].get('filesize', 'Unknown'),
                'timestamp': datetime.datetime.now().isoformat()
            }
            add_history_item(history_item)
            
    except Exception as e:
        with downloads_lock:
            if downloads.get(download_id, {}).get('cancel_requested'):
                downloads[download_id]['status'] = 'aborted'
                logger.info('Download aborted by user: %s', download_id)
            else:
                downloads[download_id]['status'] = 'error'
                downloads[download_id]['error'] = str(e)
                logger.error('Download failed [%s]: %s', download_id, e)

@app.route('/api/settings', methods=['GET'])
def get_settings():
    return jsonify(load_settings())

@app.route('/api/settings/location', methods=['POST'])
def add_location():
    data = request.json
    name = data.get('name', '').strip()
    path = data.get('path', '').strip()
    
    if not name or not path:
        return jsonify({'error': 'Name and Path are required'}), 400
        
    path = os.path.abspath(path)
    
    try:
        os.makedirs(path, exist_ok=True)
        # Test write permission
        temp_file = os.path.join(path, f'.write_test_{uuid.uuid4().hex}')
        with open(temp_file, 'w') as f:
            f.write('test')
        os.remove(temp_file)
    except Exception as e:
        return jsonify({'error': f"Invalid or unwritable directory path: {str(e)}"}), 400
        
    settings = load_settings()
    
    # Check if duplicate path or name
    for loc in settings['locations']:
        if loc['path'].lower() == path.lower():
            return jsonify({'error': f"Directory already exists in list: '{loc['name']}'"}), 400
            
    loc_id = str(uuid.uuid4())
    new_loc = {
        'id': loc_id,
        'name': name,
        'path': path,
        'is_default': False
    }
    settings['locations'].append(new_loc)
    save_settings(settings)
    
    return jsonify(new_loc)

@app.route('/api/settings/location/active', methods=['POST'])
def set_active_location():
    data = request.json
    loc_id = data.get('id')
    if not loc_id:
        return jsonify({'error': 'Location ID is required'}), 400
        
    settings = load_settings()
    found = False
    for loc in settings['locations']:
        if loc['id'] == loc_id:
            loc['is_default'] = True
            found = True
        else:
            loc['is_default'] = False
            
    if not found:
        return jsonify({'error': 'Location not found'}), 404
        
    save_settings(settings)
    return jsonify({'success': True})

@app.route('/api/settings/location/<loc_id>', methods=['DELETE'])
def delete_location(loc_id):
    if loc_id == 'default':
        return jsonify({'error': 'Cannot delete default downloads location'}), 400
        
    settings = load_settings()
    loc_to_delete = None
    for loc in settings['locations']:
        if loc['id'] == loc_id:
            loc_to_delete = loc
            break
            
    if not loc_to_delete:
        return jsonify({'error': 'Location not found'}), 404
        
    settings['locations'].remove(loc_to_delete)
    
    # If deleted location was default, reset default to 'default'
    if loc_to_delete.get('is_default'):
        for loc in settings['locations']:
            if loc['id'] == 'default':
                loc['is_default'] = True
                break
                
    save_settings(settings)
    return jsonify({'success': True})

@app.route('/api/download', methods=['POST'])
def start_download():
    client_id = request.headers.get('X-Client-ID')
    data = request.json
    if not data:
        return jsonify({'error': 'Request body is required', 'code': 'MISSING_BODY'}), 400
    url = data.get('url', '').strip()
    download_type = data.get('type') or data.get('format_type') or 'mp4'
    resolution = data.get('resolution')
    bitrate = data.get('bitrate', '192')
    subtitles = data.get('subtitles', False)
    location_id = data.get('location_id')
    
    # New options
    start_time = data.get('start_time')
    end_time = data.get('end_time')
    embed_metadata = data.get('embed_metadata', False)
    
    # Optional metadata passed to show queue item instantly
    title = data.get('title')
    thumbnail = data.get('thumbnail')
    duration = data.get('duration')

    if not url:
        return jsonify({'error': 'URL is required', 'code': 'MISSING_URL'}), 400
    if len(url) > 2048:
        return jsonify({'error': 'URL is too long', 'code': 'URL_TOO_LONG'}), 400
    if download_type not in ('mp4', 'mp3'):
        return jsonify({'error': 'Invalid download type. Must be mp4 or mp3', 'code': 'INVALID_TYPE'}), 400

    # Validate trimming inputs
    start_s = parse_time_to_seconds(start_time)
    end_s = parse_time_to_seconds(end_time)
    if start_time is not None and str(start_time).strip() != '' and start_s is None:
        return jsonify({'error': 'Invalid start time format. Use MM:SS or seconds.', 'code': 'INVALID_START_TIME'}), 400
    if end_time is not None and str(end_time).strip() != '' and end_s is None:
        return jsonify({'error': 'Invalid end time format. Use MM:SS or seconds.', 'code': 'INVALID_END_TIME'}), 400
    if start_s is not None and start_s < 0:
        return jsonify({'error': 'Start time cannot be negative.', 'code': 'NEGATIVE_START_TIME'}), 400
    if end_s is not None and end_s <= 0:
        return jsonify({'error': 'End time must be greater than zero.', 'code': 'INVALID_END_TIME'}), 400
    if start_s is not None and end_s is not None and start_s >= end_s:
        return jsonify({'error': 'Start time must be earlier than end time.', 'code': 'START_TIME_AFTER_END'}), 400

    download_id = str(uuid.uuid4())
    
    thread = threading.Thread(
        target=download_worker, 
        args=(url, download_type, resolution, bitrate, subtitles, download_id, title, thumbnail, duration, location_id, start_time, end_time, embed_metadata, client_id),
        daemon=True
    )
    thread.start()

    logger.info('Queued download %s for %s', download_id, url[:120])
    return jsonify({'download_id': download_id})

@app.route('/api/status/<download_id>', methods=['GET'])
def get_status(download_id):
    client_id = request.headers.get('X-Client-ID')
    with downloads_lock:
        if download_id in downloads:
            dl = dict(downloads[download_id])  # snapshot copy
            if not is_local_mode() and client_id and dl.get('client_id') != client_id:
                return jsonify({'error': 'Unauthorized'}), 403
            return jsonify(dl)
    return jsonify({'error': 'Not found'}), 404

@app.route('/api/active', methods=['GET'])
def get_active_downloads():
    client_id = request.headers.get('X-Client-ID')
    with downloads_lock:
        if not is_local_mode() and client_id:
            client_dls = {id: dict(dl) for id, dl in downloads.items() if dl.get('client_id') == client_id}
            return jsonify(client_dls)
        return jsonify({id: dict(dl) for id, dl in downloads.items()})

@app.route('/api/abort/<download_id>', methods=['POST'])
def abort_download(download_id):
    client_id = request.headers.get('X-Client-ID')
    with downloads_lock:
        if download_id in downloads:
            dl = downloads[download_id]
            if not is_local_mode() and client_id and dl.get('client_id') != client_id:
                return jsonify({'error': 'Unauthorized'}), 403
            dl['cancel_requested'] = True
            dl['status'] = 'aborting'
            logger.info('Abort requested for download %s', download_id)
            return jsonify({'success': True})
    return jsonify({'error': 'Not found'}), 404

@app.route('/api/history', methods=['GET'])
def get_history():
    client_id = request.headers.get('X-Client-ID')
    history = load_history()
    if not is_local_mode() and client_id:
        history = [item for item in history if item.get('client_id') == client_id]
    for item in history:
        filepath = item.get('filepath')
        item['file_exists'] = bool(filepath and os.path.exists(filepath))
    return jsonify(history)

@app.route('/api/history/<download_id>', methods=['DELETE'])
def delete_history_item(download_id):
    client_id = request.headers.get('X-Client-ID')
    history = load_history()
    item_to_delete = None
    for item in history:
        if item.get('download_id') == download_id:
            if not is_local_mode() and client_id and item.get('client_id') != client_id:
                return jsonify({'error': 'Unauthorized'}), 403
            item_to_delete = item
            break
            
    if item_to_delete:
        history.remove(item_to_delete)
        save_history(history)
        
        # Delete local file to save space
        filepath = item_to_delete.get('filepath') or (os.path.join(DOWNLOAD_DIR, item_to_delete['filename']) if item_to_delete.get('filename') else None)
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass
        return jsonify({'success': True})
    return jsonify({'error': 'Item not found'}), 404

@app.route('/api/history/clear', methods=['POST'])
def clear_all_history():
    client_id = request.headers.get('X-Client-ID')
    data = request.json or {}
    delete_files = data.get('delete_files', False)
    
    history = load_history()
    
    if not is_local_mode() and client_id:
        remaining_history = []
        for item in history:
            if item.get('client_id') == client_id:
                if delete_files:
                    filepath = item.get('filepath') or (os.path.join(DOWNLOAD_DIR, item['filename']) if item.get('filename') else None)
                    if filepath and os.path.exists(filepath):
                        try:
                            os.remove(filepath)
                        except Exception:
                            pass
            else:
                remaining_history.append(item)
        save_history(remaining_history)
    else:
        if delete_files:
            for item in history:
                filepath = item.get('filepath') or (os.path.join(DOWNLOAD_DIR, item['filename']) if item.get('filename') else None)
                if filepath and os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except Exception:
                        pass
        save_history([])
    return jsonify({'success': True})

@app.route('/api/active/clear', methods=['POST'])
def clear_completed_active_downloads():
    client_id = request.headers.get('X-Client-ID')
    with downloads_lock:
        to_delete = []
        for id, dl in downloads.items():
            if dl['status'] in ('completed', 'error', 'aborted'):
                if not is_local_mode() and client_id and dl.get('client_id') != client_id:
                    continue
                to_delete.append(id)
        for id in to_delete:
            del downloads[id]
    return jsonify({'success': True})

@app.route('/api/search', methods=['POST'])
def search_youtube():
    data = request.json
    query = data.get('query')
    if not query:
        return jsonify({'error': 'Query is required'}), 400
        
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': 'in_playlist',
        'ignoreconfig': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch30:{query}", download=False)
            results = []
            for entry in info.get('entries', []):
                if entry:
                    thumbnail = None
                    if entry.get('thumbnails'):
                        thumbnail = entry['thumbnails'][0].get('url')
                    elif entry.get('thumbnail'):
                        thumbnail = entry.get('thumbnail')
                        
                    results.append({
                        'id': entry.get('id'),
                        'title': entry.get('title'),
                        'duration': entry.get('duration'),
                        'uploader': entry.get('uploader') or entry.get('channel') or 'Unknown',
                        'thumbnail': thumbnail,
                        'url': f"https://www.youtube.com/watch?v={entry.get('id')}"
                    })
            return jsonify({'results': results})
    except Exception as e:
        logger.error('Search failed for query "%s": %s', query[:100], e)
        return jsonify({'error': str(e), 'code': 'SEARCH_FAILED'}), 500

SUGGESTIONS = [
    # 15 Music items
    {
        "id": "JGwWNGJdvx8",
        "title": "Ed Sheeran - Shape of You [Official Video]",
        "uploader": "Ed Sheeran",
        "duration": 263,
        "thumbnail": "https://i.ytimg.com/vi/JGwWNGJdvx8/mqdefault.jpg",
        "category": "music",
        "url": "https://www.youtube.com/watch?v=JGwWNGJdvx8"
    },
    {
        "id": "4NRXx6U8ABQ",
        "title": "The Weeknd - Blinding Lights [Official Music Video]",
        "uploader": "The Weeknd",
        "duration": 223,
        "thumbnail": "https://i.ytimg.com/vi/4NRXx6U8ABQ/mqdefault.jpg",
        "category": "music",
        "url": "https://www.youtube.com/watch?v=4NRXx6U8ABQ"
    },
    {
        "id": "DWcJFNfaw9c",
        "title": "1 A.M Study Session 📚 [lofi hip hop/chill beats]",
        "uploader": "Lofi Girl",
        "duration": 3600,
        "thumbnail": "https://i.ytimg.com/vi/DWcJFNfaw9c/mqdefault.jpg",
        "category": "music",
        "url": "https://www.youtube.com/watch?v=DWcJFNfaw9c"
    },
    {
        "id": "U3ASj1L6_sY",
        "title": "Adele - Easy On Me [Official Video]",
        "uploader": "Adele",
        "duration": 344,
        "thumbnail": "https://i.ytimg.com/vi/U3ASj1L6_sY/mqdefault.jpg",
        "category": "music",
        "url": "https://www.youtube.com/watch?v=U3ASj1L6_sY"
    },
    {
        "id": "kJQP7kiw5Fk",
        "title": "Luis Fonsi - Despacito ft. Daddy Yankee",
        "uploader": "Luis Fonsi",
        "duration": 282,
        "thumbnail": "https://i.ytimg.com/vi/kJQP7kiw5Fk/mqdefault.jpg",
        "category": "music",
        "url": "https://www.youtube.com/watch?v=kJQP7kiw5Fk"
    },
    {
        "id": "OPf0YbXqDm0",
        "title": "Mark Ronson - Uptown Funk ft. Bruno Mars",
        "uploader": "Mark Ronson",
        "duration": 270,
        "thumbnail": "https://i.ytimg.com/vi/OPf0YbXqDm0/mqdefault.jpg",
        "category": "music",
        "url": "https://www.youtube.com/watch?v=OPf0YbXqDm0"
    },
    {
        "id": "RgKAFK5djSk",
        "title": "Wiz Khalifa - See You Again ft. Charlie Puth",
        "uploader": "Wiz Khalifa",
        "duration": 237,
        "thumbnail": "https://i.ytimg.com/vi/RgKAFK5djSk/mqdefault.jpg",
        "category": "music",
        "url": "https://www.youtube.com/watch?v=RgKAFK5djSk"
    },
    {
        "id": "hT_nvWreIhg",
        "title": "OneRepublic - Counting Stars [Official Music Video]",
        "uploader": "OneRepublic",
        "duration": 283,
        "thumbnail": "https://i.ytimg.com/vi/hT_nvWreIhg/mqdefault.jpg",
        "category": "music",
        "url": "https://www.youtube.com/watch?v=hT_nvWreIhg"
    },
    {
        "id": "9bZkp7q19f0",
        "title": "PSY - GANGNAM STYLE (강남스타일) M/V",
        "uploader": "officialpsy",
        "duration": 252,
        "thumbnail": "https://i.ytimg.com/vi/9bZkp7q19f0/mqdefault.jpg",
        "category": "music",
        "url": "https://www.youtube.com/watch?v=9bZkp7q19f0"
    },
    {
        "id": "09R8_2nJtjg",
        "title": "Maroon 5 - Sugar [Official Music Video]",
        "uploader": "Maroon 5",
        "duration": 301,
        "thumbnail": "https://i.ytimg.com/vi/09R8_2nJtjg/mqdefault.jpg",
        "category": "music",
        "url": "https://www.youtube.com/watch?v=09R8_2nJtjg"
    },
    {
        "id": "K4DyBUG242c",
        "title": "Billie Eilish - bad guy [Official Video]",
        "uploader": "Billie Eilish",
        "duration": 205,
        "thumbnail": "https://i.ytimg.com/vi/K4DyBUG242c/mqdefault.jpg",
        "category": "music",
        "url": "https://www.youtube.com/watch?v=K4DyBUG242c"
    },
    {
        "id": "fKopy74weus",
        "title": "Imagine Dragons - Thunder [Official Music Video]",
        "uploader": "Imagine Dragons",
        "duration": 204,
        "thumbnail": "https://i.ytimg.com/vi/fKopy74weus/mqdefault.jpg",
        "category": "music",
        "url": "https://www.youtube.com/watch?v=fKopy74weus"
    },
    {
        "id": "rtO53tW8V9E",
        "title": "Post Malone, Swae Lee - Sunflower (Spider-Man: Into the Spider-Verse)",
        "uploader": "Post Malone",
        "duration": 161,
        "thumbnail": "https://i.ytimg.com/vi/rtO53tW8V9E/mqdefault.jpg",
        "category": "music",
        "url": "https://www.youtube.com/watch?v=rtO53tW8V9E"
    },
    {
        "id": "Jrg9K6sWvTo",
        "title": "Dua Lipa - New Rules [Official Music Video]",
        "uploader": "Dua Lipa",
        "duration": 225,
        "thumbnail": "https://i.ytimg.com/vi/Jrg9K6sWvTo/mqdefault.jpg",
        "category": "music",
        "url": "https://www.youtube.com/watch?v=Jrg9K6sWvTo"
    },
    {
        "id": "vRXZj0DzXIA",
        "title": "Shawn Mendes, Camila Cabello - Señorita [Official Music Video]",
        "uploader": "Shawn Mendes",
        "duration": 205,
        "thumbnail": "https://i.ytimg.com/vi/vRXZj0DzXIA/mqdefault.jpg",
        "category": "music",
        "url": "https://www.youtube.com/watch?v=vRXZj0DzXIA"
    },

    # 15 Video items
    {
        "id": "dtp6b76pMak",
        "title": "Apple Vision Pro Review: Tomorrow's Tech Today",
        "uploader": "Marques Brownlee",
        "duration": 1760,
        "thumbnail": "https://i.ytimg.com/vi/dtp6b76pMak/mqdefault.jpg",
        "category": "video",
        "url": "https://www.youtube.com/watch?v=dtp6b76pMak"
    },
    {
        "id": "Uj3_Krxee5I",
        "title": "The Infinite Hotel Paradox - Veritasium",
        "uploader": "Veritasium",
        "duration": 360,
        "thumbnail": "https://i.ytimg.com/vi/Uj3_Krxee5I/mqdefault.jpg",
        "category": "video",
        "url": "https://www.youtube.com/watch?v=Uj3_Krxee5I"
    },
    {
        "id": "h4T_LlK1VE4",
        "title": "Glitterbomb vs. Package Thieves - Mark Rober",
        "uploader": "Mark Rober",
        "duration": 1240,
        "thumbnail": "https://i.ytimg.com/vi/h4T_LlK1VE4/mqdefault.jpg",
        "category": "video",
        "url": "https://www.youtube.com/watch?v=h4T_LlK1VE4"
    },
    {
        "id": "JyECrGp-F5Y",
        "title": "What If We Detonated All Nuclear Bombs at Once?",
        "uploader": "Kurzgesagt – In a Nutshell",
        "duration": 480,
        "thumbnail": "https://i.ytimg.com/vi/JyECrGp-F5Y/mqdefault.jpg",
        "category": "video",
        "url": "https://www.youtube.com/watch?v=JyECrGp-F5Y"
    },
    {
        "id": "2Vv-BfVoq4g",
        "title": "Ed Sheeran - Perfect [Official Music Video]",
        "uploader": "Ed Sheeran",
        "duration": 279,
        "thumbnail": "https://i.ytimg.com/vi/2Vv-BfVoq4g/mqdefault.jpg",
        "category": "video",
        "url": "https://www.youtube.com/watch?v=2Vv-BfVoq4g"
    },
    {
        "id": "L_LUpnjgPso",
        "title": "How to Build a PC in 2024 - Step-by-Step Guide",
        "uploader": "Linus Tech Tips",
        "duration": 1820,
        "thumbnail": "https://i.ytimg.com/vi/L_LUpnjgPso/mqdefault.jpg",
        "category": "video",
        "url": "https://www.youtube.com/watch?v=L_LUpnjgPso"
    },
    {
        "id": "g-dKXBXiHoc",
        "title": "Is the Universe a Hologram? - Space Time",
        "uploader": "PBS Space Time",
        "duration": 945,
        "thumbnail": "https://i.ytimg.com/vi/g-dKXBXiHoc/mqdefault.jpg",
        "category": "video",
        "url": "https://www.youtube.com/watch?v=g-dKXBXiHoc"
    },
    {
        "id": "I2O7blSSzpI",
        "title": "Boston Dynamics' New Atlas Robot Showcases Amazing Capabilities",
        "uploader": "Boston Dynamics",
        "duration": 180,
        "thumbnail": "https://i.ytimg.com/vi/I2O7blSSzpI/mqdefault.jpg",
        "category": "video",
        "url": "https://www.youtube.com/watch?v=I2O7blSSzpI"
    },
    {
        "id": "w82a1_ENn2Y",
        "title": "Why is the Space Shuttle Orbiter Shaped Like That?",
        "uploader": "Everyday Astronaut",
        "duration": 1420,
        "thumbnail": "https://i.ytimg.com/vi/w82a1_ENn2Y/mqdefault.jpg",
        "category": "video",
        "url": "https://www.youtube.com/watch?v=w82a1_ENn2Y"
    },
    {
        "id": "s805aA-Hwio",
        "title": "Inside a $150 Million Mega Mansion",
        "uploader": "Enes Yilmazer",
        "duration": 2100,
        "thumbnail": "https://i.ytimg.com/vi/s805aA-Hwio/mqdefault.jpg",
        "category": "video",
        "url": "https://www.youtube.com/watch?v=s805aA-Hwio"
    },
    {
        "id": "r7p-yP3Z9_o",
        "title": "I Spent 50 Hours In Solitary Confinement",
        "uploader": "MrBeast",
        "duration": 920,
        "thumbnail": "https://i.ytimg.com/vi/r7p-yP3Z9_o/mqdefault.jpg",
        "category": "video",
        "url": "https://www.youtube.com/watch?v=r7p-yP3Z9_o"
    },
    {
        "id": "R2_cObd5bC0",
        "title": "Quantum Computers Explained - Limits of Human Technology",
        "uploader": "Kurzgesagt – In a Nutshell",
        "duration": 580,
        "thumbnail": "https://i.ytimg.com/vi/R2_cObd5bC0/mqdefault.jpg",
        "category": "video",
        "url": "https://www.youtube.com/watch?v=R2_cObd5bC0"
    },
    {
        "id": "k1-TrAvp_xs",
        "title": "M1 Mac Review: The Real Deal",
        "uploader": "Marques Brownlee",
        "duration": 820,
        "thumbnail": "https://i.ytimg.com/vi/k1-TrAvp_xs/mqdefault.jpg",
        "category": "video",
        "url": "https://www.youtube.com/watch?v=k1-TrAvp_xs"
    },
    {
        "id": "W6NZfCO5SIk",
        "title": "JavaScript Tutorial for Beginners: Learn JavaScript in 1 Hour",
        "uploader": "Programming with Mosh",
        "duration": 2880,
        "thumbnail": "https://i.ytimg.com/vi/W6NZfCO5SIk/mqdefault.jpg",
        "category": "video",
        "url": "https://www.youtube.com/watch?v=W6NZfCO5SIk"
    },
    {
        "id": "0e3GPea1TNY",
        "title": "How the Internet Works in 5 Minutes",
        "uploader": "Aaron Jack",
        "duration": 315,
        "thumbnail": "https://i.ytimg.com/vi/0e3GPea1TNY/mqdefault.jpg",
        "category": "video",
        "url": "https://www.youtube.com/watch?v=0e3GPea1TNY"
    }
]

# Thread safety and dynamic caching for recommendations
dynamic_suggestions = []
last_suggestions_fetch = 0
suggestions_lock = threading.Lock()

def fetch_dynamic_suggestions_sync():
    global dynamic_suggestions, last_suggestions_fetch
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': 'in_playlist',
            'ignoreconfig': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Fetch 15 trending songs
            music_info = ydl.extract_info("ytsearch15:trending music", download=False)
            music_entries = []
            for entry in music_info.get('entries', []):
                if entry and entry.get('id'):
                    thumbnail = None
                    if entry.get('thumbnails'):
                        thumbnail = entry['thumbnails'][0].get('url')
                    elif entry.get('thumbnail'):
                        thumbnail = entry.get('thumbnail')
                    music_entries.append({
                        "id": entry.get('id'),
                        "title": entry.get('title'),
                        "uploader": entry.get('uploader') or entry.get('channel') or 'Unknown',
                        "duration": entry.get('duration') or 0,
                        "thumbnail": thumbnail or f"https://i.ytimg.com/vi/{entry.get('id')}/mqdefault.jpg",
                        "category": "music",
                        "url": f"https://www.youtube.com/watch?v={entry.get('id')}"
                    })
            
            # Fetch 15 trending videos
            video_info = ydl.extract_info("ytsearch15:trending videos", download=False)
            video_entries = []
            for entry in video_info.get('entries', []):
                if entry and entry.get('id'):
                    thumbnail = None
                    if entry.get('thumbnails'):
                        thumbnail = entry['thumbnails'][0].get('url')
                    elif entry.get('thumbnail'):
                        thumbnail = entry.get('thumbnail')
                    video_entries.append({
                        "id": entry.get('id'),
                        "title": entry.get('title'),
                        "uploader": entry.get('uploader') or entry.get('channel') or 'Unknown',
                        "duration": entry.get('duration') or 0,
                        "thumbnail": thumbnail or f"https://i.ytimg.com/vi/{entry.get('id')}/mqdefault.jpg",
                        "category": "video",
                        "url": f"https://www.youtube.com/watch?v={entry.get('id')}"
                    })
            
            combined = music_entries + video_entries
            if len(combined) >= 10:
                with suggestions_lock:
                    dynamic_suggestions = combined
                    last_suggestions_fetch = time.time()
                logger.info('Loaded %d dynamic suggestions successfully.', len(combined))
                return combined
    except Exception as e:
        logger.error('Error fetching dynamic suggestions: %s', e)
    return []

def fetch_dynamic_suggestions_thread():
    fetch_dynamic_suggestions_sync()

def trigger_suggestions_update():
    global last_suggestions_fetch
    now = time.time()
    # Cache for 1 hour (3600 seconds)
    if now - last_suggestions_fetch > 3600:
        with suggestions_lock:
            last_suggestions_fetch = now  # set temporarily to prevent multiple threads starting
        threading.Thread(target=fetch_dynamic_suggestions_thread, daemon=True).start()

@app.route('/api/suggestions', methods=['GET'])
def get_suggestions():
    force = request.args.get('force', 'false').lower() == 'true'
    if force:
        results = fetch_dynamic_suggestions_sync()
        if results:
            return jsonify(results)
    else:
        trigger_suggestions_update()
    
    with suggestions_lock:
        if dynamic_suggestions:
            return jsonify(dynamic_suggestions)
    return jsonify(SUGGESTIONS)

@app.route('/api/files/<path:filename>', methods=['GET'])
def serve_file(filename):
    filename = os.path.basename(filename)
    client_id = request.args.get('client_id') or request.headers.get('X-Client-ID')
    download = request.args.get('download', 'false').lower() == 'true'
    # Safe serving of files from their actual downloaded directories
    history = load_history()
    for item in history:
        if item.get('filename') == filename and item.get('filepath'):
            if not is_local_mode() and client_id and item.get('client_id') != client_id:
                continue
            filepath = item['filepath']
            dirpath = os.path.dirname(filepath)
            if os.path.exists(filepath):
                return send_from_directory(dirpath, filename, as_attachment=download)
                
    # Fallback to default downloads folder
    if is_local_mode():
        return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=download)
    return jsonify({'error': 'Unauthorized or file not found'}), 404

@app.route('/api/files/by-id/<download_id>', methods=['GET'])
def serve_file_by_id(download_id):
    client_id = request.args.get('client_id') or request.headers.get('X-Client-ID')
    download = request.args.get('download', 'false').lower() == 'true'
    history = load_history()
    for item in history:
        if item.get('download_id') == download_id:
            if not is_local_mode() and client_id and item.get('client_id') != client_id:
                return jsonify({'error': 'Unauthorized'}), 403
            filepath = item.get('filepath')
            if filepath and os.path.exists(filepath):
                dirpath = os.path.dirname(filepath)
                fname = os.path.basename(filepath)
                return send_from_directory(dirpath, fname, as_attachment=download)
            return jsonify({'error': 'File not found on disk'}), 404
    return jsonify({'error': 'Download record not found'}), 404

@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify({
        'is_local': is_local_mode(),
        'has_ffmpeg': check_ffmpeg()
    })

@app.route('/api/open-folder', methods=['POST'])
def open_folder():
    if not is_local_mode():
        return jsonify({'error': 'Not available in server mode'}), 403
        
    data = request.json or {}
    download_id = data.get('download_id')
    history = load_history()
    for item in history:
        if item.get('download_id') == download_id:
            filepath = item.get('filepath')
            if filepath and os.path.exists(filepath):
                try:
                    import subprocess
                    if sys.platform == 'win32':
                        subprocess.Popen(['explorer', f'/select,{os.path.abspath(filepath)}'])
                    elif sys.platform == 'darwin':
                        subprocess.Popen(['open', '-R', filepath])
                    else:
                        subprocess.Popen(['xdg-open', os.path.dirname(filepath)])
                    return jsonify({'success': True})
                except Exception as e:
                    return jsonify({'error': str(e)}), 500
            break
            
    return jsonify({'error': 'File not found'}), 404

def open_browser(port):
    # Wait a bit for server to start
    time.sleep(1.5)
    webbrowser.open(f'http://127.0.0.1:{port}/')

if __name__ == '__main__':
    # Auto-switch to the project virtual environment if run directly from global Python
    if not getattr(sys, 'frozen', False) and sys.prefix == sys.base_prefix:
        _app_dir = os.path.dirname(os.path.abspath(__file__))
        _venv_py = os.path.join(_app_dir, '.venv', 'Scripts', 'python.exe')
        if not os.path.exists(_venv_py):
            _venv_py = os.path.join(_app_dir, '.venv', 'bin', 'python')
        if os.path.exists(_venv_py) and os.environ.get('__YT_DOWN_VENV_SWITCHED') != '1':
            import subprocess
            os.environ['__YT_DOWN_VENV_SWITCHED'] = '1'
            sys.exit(subprocess.call([_venv_py] + sys.argv))

    logger.info('=' * 50)
    if not check_ffmpeg():
        logger.warning('ffmpeg not found in PATH!')
        logger.warning('High-resolution video merging and MP3 extraction will NOT work.')
        logger.warning('Please download ffmpeg from https://ffmpeg.org/download.html and add it to your PATH.')
    else:
        logger.info('ffmpeg found. All features enabled.')
    logger.info('=' * 50)
    logger.info('Downloads will be saved to: %s', DOWNLOAD_DIR)
    logger.info('Logs will be saved to: %s', LOG_DIR)
    
    # Start cleanup thread if running in server mode
    if not is_local_mode():
        threading.Thread(target=cleanup_old_downloads, daemon=True).start()
        
    # Start background thread to pre-fetch dynamic recommendations
    threading.Thread(target=fetch_dynamic_suggestions_thread, daemon=True).start()
        
    # Auto-open browser when compiled
    is_frozen = getattr(sys, 'frozen', False)
    is_debug = not is_frozen
    
    if is_local_mode():
        port = find_free_port(5000)
        host = '127.0.0.1'
        if is_frozen:
            threading.Thread(target=open_browser, args=(port,), daemon=True).start()
    else:
        port = int(os.environ.get('PORT', 5000))
        host = '0.0.0.0'
    
    logger.info('Starting server on %s:%d (debug=%s)', host, port, is_debug)
    app.run(host=host, port=port, debug=is_debug, use_reloader=is_debug)
