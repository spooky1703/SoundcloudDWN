import os
import sys
import threading
import queue
import time
import json
import logging
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional, Dict, Any, List
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import yt_dlp


class Config:
    DEFAULT_BITRATE = "192"
    SUPPORTED_FORMATS = ["mp3", "m4a", "flac", "wav"]
    BITRATE_OPTIONS = ["320", "256", "192", "128", "96"]
    DEFAULT_OUT_TEMPLATE = "%(artist)s - %(title).200s.%(ext)s"
    CONFIG_FILE = "downloader_config.json"
    LOG_FILE = "downloader.log"
    PROVIDERS = {"SoundCloud": "scsearch1:", "YouTube Music": "ytsearch1:"}


class ThemeDark:
    name = "dark"
    BG_MAIN = "#0D1117"
    BG_CARD = "#161B22"
    BG_INPUT = "#21262D"
    BG_HOVER = "#30363D"
    ACCENT = "#1DB954"
    ACCENT_HOVER = "#1ED760"
    ACCENT_ALT = "#8B5CF6"
    SUCCESS = "#22C55E"
    WARNING = "#F59E0B"
    ERROR = "#EF4444"
    TEXT_PRIMARY = "#E6EDF3"
    TEXT_SECONDARY = "#8B949E"
    TEXT_MUTED = "#484F58"
    BORDER = "#30363D"

class ThemeLight:
    name = "light"
    BG_MAIN = "#FFFFFF"
    BG_CARD = "#F6F8FA"
    BG_INPUT = "#FFFFFF"
    BG_HOVER = "#F3F4F6"
    ACCENT = "#1DB954"
    ACCENT_HOVER = "#1ED760"
    ACCENT_ALT = "#8B5CF6"
    SUCCESS = "#16A34A"
    WARNING = "#D97706"
    ERROR = "#DC2626"
    TEXT_PRIMARY = "#1F2937"
    TEXT_SECONDARY = "#6B7280"
    TEXT_MUTED = "#9CA3AF"
    BORDER = "#E5E7EB"

# Global theme
Theme = ThemeDark

def set_theme(theme_class):
    global Theme
    Theme = theme_class


def setup_logging():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                       handlers=[logging.FileHandler(Config.LOG_FILE, encoding='utf-8'), logging.StreamHandler(sys.stdout)])
    return logging.getLogger(__name__)

class ConfigManager:
    def __init__(self):
        self.path = Path(Config.CONFIG_FILE)
        self.defaults = {"output_dir": str(Path.home() / "Downloads"), "bitrate": "192", "format": "mp3",
                        "provider": "SoundCloud", "theme": "dark", "template": Config.DEFAULT_OUT_TEMPLATE}
    
    def load(self):
        try:
            if self.path.exists():
                with open(self.path, 'r') as f:
                    return {**self.defaults, **json.load(f)}
        except: pass
        return self.defaults.copy()
    
    def save(self, cfg):
        try:
            with open(self.path, 'w') as f:
                json.dump(cfg, f, indent=2)
        except: pass

class QueueStatus:
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETE = "complete"
    ERROR = "error"
    CANCELED = "canceled"

class QueueItem:
    def __init__(self, query: str):
        self.query = query.strip()
        self.status = QueueStatus.PENDING
        self.progress = 0
        self.title = query[:40] + "..." if len(query) > 40 else query
        self.error = None
        self.preview_url = None

class DownloaderThread(threading.Thread):
    def __init__(self, item: QueueItem, config: dict, progress_q: queue.Queue, stop_event: threading.Event, provider: str):
        super().__init__(daemon=True)
        self.item = item
        self.config = config
        self.progress_q = progress_q
        self.stop_event = stop_event
        self.provider = provider
    
    def run(self):
        try:
            self._download()
        except Exception as e:
            if self.stop_event.is_set():
                self.progress_q.put(("item_status", self.item, QueueStatus.CANCELED, "Cancelado"))
            else:
                self.progress_q.put(("item_status", self.item, QueueStatus.ERROR, str(e)))
    
    def _is_url(self, t):
        return t.startswith('http://') or t.startswith('https://')
    
    def _download(self):
        output_dir = Path(self.config['output_dir'])
        output_dir.mkdir(parents=True, exist_ok=True)
        
        is_url = self._is_url(self.item.query)
        search_prefix = Config.PROVIDERS.get(self.provider, "scsearch1:")
        
        ydl_opts = {
            # MÁXIMA CALIDAD: descargar el mejor audio disponible
            'format': 'bestaudio/best',
            'format_sort': ['quality', 'abr', 'asr'],
            'format_sort_force': True,
            'outtmpl': str(output_dir / self.config.get('template', Config.DEFAULT_OUT_TEMPLATE)),
            'noplaylist': True, 'quiet': True, 'no_warnings': True,
            'progress_hooks': [self._hook],
            'writethumbnail': True, 'nocheckcertificate': True, 'socket_timeout': 30,
            # Postprocesadores con máxima calidad
            'postprocessors': [
                {
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': self.config.get('format', 'mp3'),
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
        
        self.progress_q.put(("item_status", self.item, QueueStatus.DOWNLOADING, None))
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_q = self.item.query if is_url else f"{search_prefix}{self.item.query}"
            info = ydl.extract_info(search_q, download=False)
            
            if info.get('_type') == 'playlist' and info.get('entries'):
                info = info['entries'][0]
            
            self.item.title = info.get('title', self.item.query)[:50]
            self.item.preview_url = info.get('webpage_url') or info.get('url')  # URL for preview
            
            self.progress_q.put(("item_update", self.item))
            
            ydl.download([info.get('webpage_url') or search_q])
            
            if not self.stop_event.is_set():
                self.progress_q.put(("item_status", self.item, QueueStatus.COMPLETE, None))
    
    def _hook(self, d):
        if self.stop_event.is_set():
            raise yt_dlp.DownloadError("Cancelled")
        if d.get('status') == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            done = d.get('downloaded_bytes', 0)
            if total > 0:
                self.item.progress = int(done / total * 100)
                self.progress_q.put(("item_progress", self.item))

class QueueManager:
    def __init__(self, config: dict, progress_q: queue.Queue, provider: str):
        self.queue: List[QueueItem] = []
        self.config = config
        self.progress_q = progress_q
        self.provider = provider
        self.current_worker = None
        self.stop_event = threading.Event()
        self.running = False
    
    def add_items(self, queries: List[str]):
        for q in queries:
            if q.strip():
                self.queue.append(QueueItem(q))
    
    def start(self):
        if not self.running and self.queue:
            self.running = True
            self.stop_event.clear()
            self._process_next()
    
    def _process_next(self):
        pending = [i for i in self.queue if i.status == QueueStatus.PENDING]
        if pending and not self.stop_event.is_set():
            item = pending[0]
            self.current_worker = DownloaderThread(item, self.config, self.progress_q, self.stop_event, self.provider)
            self.current_worker.start()
        else:
            self.running = False
            self.progress_q.put(("queue_complete", None))
    
    def on_item_done(self):
        if self.running:
            self._process_next()
    
    def cancel_all(self):
        self.stop_event.set()
        for item in self.queue:
            if item.status == QueueStatus.PENDING:
                item.status = QueueStatus.CANCELED
        self.running = False
    
    def clear(self):
        self.queue = []

# ---------------------------
# Mini Player (Preview)
# ---------------------------
class MiniPlayer:
    def __init__(self):
        self.playing = False
        self.mixer_init = False
        self.temp_file = None
    
    def init_mixer(self):
        if not self.mixer_init:
            try:
                import pygame
                pygame.mixer.init()
                self.mixer_init = True
            except ImportError:
                return False
        return True
    
    def play_preview(self, webpage_url: str, callback=None):
        """Download preview using yt-dlp and play it"""
        if not webpage_url or not self.init_mixer():
            if callback:
                callback(False, "pygame no disponible")
            return False
        
        def _download_and_play():
            try:
                import pygame
                import glob
                
                # Create temp directory for preview
                temp_dir = tempfile.mkdtemp()
                temp_base = os.path.join(temp_dir, 'preview')
                
                # Download at low quality for faster preview
                ydl_opts = {
                    'format': 'worstaudio/worst',  # Lowest quality for speed
                    'outtmpl': temp_base + '.%(ext)s',
                    'quiet': True,
                    'no_warnings': True,
                    'nocheckcertificate': True,
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '64',  # Low quality for preview
                    }],
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([webpage_url])
                
                # Find the downloaded mp3 file
                mp3_files = glob.glob(os.path.join(temp_dir, '*.mp3'))
                
                if mp3_files and os.path.getsize(mp3_files[0]) > 0:
                    pygame.mixer.music.load(mp3_files[0])
                    pygame.mixer.music.play()
                    self.playing = True
                    self.temp_file = type('obj', (object,), {'name': mp3_files[0], 'dir': temp_dir})()
                    if callback:
                        callback(True)
                else:
                    if callback:
                        callback(False, "No se encontró archivo")
                    # Cleanup
                    import shutil
                    shutil.rmtree(temp_dir, ignore_errors=True)
                        
            except Exception as e:
                if callback:
                    callback(False, str(e)[:40])
        
        threading.Thread(target=_download_and_play, daemon=True).start()
        return True
    
    def stop(self):
        if self.mixer_init:
            try:
                import pygame
                pygame.mixer.music.stop()
            except: pass
        self.playing = False
        if self.temp_file and hasattr(self.temp_file, 'name') and os.path.exists(self.temp_file.name):
            try: os.unlink(self.temp_file.name)
            except: pass

# ---------------------------
# Modern Button
# ---------------------------
class ModernButton(tk.Canvas):
    def __init__(self, parent, text, command, bg_color=None, fg_color=None, width=140, height=44, **kw):
        super().__init__(parent, width=width, height=height, highlightthickness=0, bg=Theme.BG_MAIN, **kw)
        self.command = command
        self.bg_color = bg_color or Theme.ACCENT
        self.fg_color = fg_color or Theme.BG_MAIN
        self.text = text
        self.w, self.h = width, height
        self.enabled = True
        self._draw()
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", lambda e: self._draw(True) if self.enabled else None)
        self.bind("<Leave>", lambda e: self._draw())
    
    def _draw(self, hover=False):
        self.delete("all")
        c = Theme.ACCENT_HOVER if hover and self.enabled else self.bg_color
        if not self.enabled: c = Theme.TEXT_MUTED
        r = 10
        x1, y1, x2, y2 = 1, 1, self.w-1, self.h-1
        pts = [x1+r,y1, x2-r,y1, x2,y1, x2,y1+r, x2,y2-r, x2,y2, x2-r,y2, x1+r,y2, x1,y2, x1,y2-r, x1,y1+r, x1,y1]
        self.create_polygon(pts, smooth=True, fill=c)
        self.create_text(self.w//2, self.h//2, text=self.text, fill=self.fg_color, font=('SF Pro Display', 11, 'bold'))
    
    def _click(self, e):
        if self.enabled and self.command: self.command()
    
    def set_enabled(self, e):
        self.enabled = e
        self._draw()
    
    def update_theme(self):
        self.config(bg=Theme.BG_MAIN)
        self._draw()

# ---------------------------
# Main App
# ---------------------------
class AudioDownloaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Audio Downloader Pro")
        self.root.geometry("700x800")
        self.root.minsize(600, 700)
        
        self.logger = setup_logging()
        self.config_mgr = ConfigManager()
        self.config = self.config_mgr.load()
        
        # Set theme from config
        if self.config.get('theme') == 'light':
            set_theme(ThemeLight)
        
        self.root.configure(bg=Theme.BG_MAIN)
        self._configure_styles()
        
        # Variables
        self.provider_var = tk.StringVar(value=self.config.get('provider', 'SoundCloud'))
        self.format_var = tk.StringVar(value=self.config.get('format', 'mp3'))
        self.bitrate_var = tk.StringVar(value=self.config.get('bitrate', '192'))
        self.outdir_var = tk.StringVar(value=self.config.get('output_dir', str(Path.home() / "Downloads")))
        self.theme_var = tk.StringVar(value=self.config.get('theme', 'dark'))
        
        # Queue & Player
        self.progress_q = queue.Queue()
        self.queue_mgr = QueueManager(self.config, self.progress_q, self.provider_var.get())
        self.player = MiniPlayer()
        self.selected_item: Optional[QueueItem] = None
        
        # Editor vars
        self.editor_file = None
        self.editor_cover = None
        self.editor_title = tk.StringVar()
        self.editor_artist = tk.StringVar()
        self.editor_album = tk.StringVar()
        
        self._build_ui()
        self._periodic_check()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
    
    def _configure_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Dark.TNotebook", background=Theme.BG_MAIN, borderwidth=0)
        style.configure("Dark.TNotebook.Tab", background=Theme.BG_CARD, foreground=Theme.TEXT_SECONDARY,
                       padding=[18, 10], font=('SF Pro Display', 10))
        style.map("Dark.TNotebook.Tab", background=[("selected", Theme.ACCENT)], foreground=[("selected", Theme.BG_MAIN)])
        style.configure("TCombobox", fieldbackground=Theme.BG_INPUT, background=Theme.BG_INPUT, foreground=Theme.TEXT_PRIMARY)
    
    def _build_ui(self):
        # Header with theme toggle
        header = tk.Frame(self.root, bg=Theme.BG_MAIN)
        header.pack(fill=tk.X, padx=25, pady=(20, 10))
        
        left = tk.Frame(header, bg=Theme.BG_MAIN)
        left.pack(side=tk.LEFT)
        
        tk.Label(left, text="🎵", font=('SF Pro Display', 26), bg=Theme.BG_MAIN, fg=Theme.ACCENT).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(left, text="Audio Downloader Pro", font=('SF Pro Display', 20, 'bold'),
                bg=Theme.BG_MAIN, fg=Theme.TEXT_PRIMARY).pack(side=tk.LEFT)
        
        # Theme toggle
        self.theme_btn = tk.Button(header, text="🌙" if Theme.name == "dark" else "☀️", font=('SF Pro Display', 16),
                                  bg=Theme.BG_CARD, fg=Theme.TEXT_PRIMARY, relief=tk.FLAT, cursor="hand2",
                                  command=self._toggle_theme)
        self.theme_btn.pack(side=tk.RIGHT)
        
        # Notebook
        self.notebook = ttk.Notebook(self.root, style="Dark.TNotebook")
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=25, pady=(5, 20))
        
        # Tabs
        queue_tab = tk.Frame(self.notebook, bg=Theme.BG_MAIN)
        self.notebook.add(queue_tab, text="  Cola de Descargas  ")
        self._build_queue_tab(queue_tab)
        
        editor_tab = tk.Frame(self.notebook, bg=Theme.BG_MAIN)
        self.notebook.add(editor_tab, text="  Editor Metadatos  ")
        self._build_editor_tab(editor_tab)
    
    def _build_queue_tab(self, parent):
        # Input card
        card1 = tk.Frame(parent, bg=Theme.BG_CARD)
        card1.pack(fill=tk.X, pady=(12, 10), padx=5)
        inner1 = tk.Frame(card1, bg=Theme.BG_CARD)
        inner1.pack(fill=tk.X, padx=18, pady=16)
        
        tk.Label(inner1, text="Pegar URLs o nombres (uno por línea)", font=('SF Pro Display', 11, 'bold'),
                bg=Theme.BG_CARD, fg=Theme.TEXT_PRIMARY).pack(anchor="w", pady=(0, 8))
        
        text_frame = tk.Frame(inner1, bg=Theme.BG_INPUT, highlightbackground=Theme.BORDER, highlightthickness=1)
        text_frame.pack(fill=tk.BOTH, expand=True)
        
        self.input_text = tk.Text(text_frame, height=5, font=('SF Pro Display', 11), bg=Theme.BG_INPUT,
                                 fg=Theme.TEXT_PRIMARY, insertbackground=Theme.TEXT_PRIMARY, relief=tk.FLAT, wrap=tk.WORD)
        self.input_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Provider selector
        opts_row = tk.Frame(inner1, bg=Theme.BG_CARD)
        opts_row.pack(fill=tk.X, pady=(10, 0))
        
        tk.Label(opts_row, text="Buscar en:", font=('SF Pro Display', 10), bg=Theme.BG_CARD, fg=Theme.TEXT_SECONDARY).pack(side=tk.LEFT)
        ttk.Combobox(opts_row, textvariable=self.provider_var, values=list(Config.PROVIDERS.keys()), width=14, state="readonly").pack(side=tk.LEFT, padx=(6, 20))
        
        tk.Label(opts_row, text="Formato:", font=('SF Pro Display', 10), bg=Theme.BG_CARD, fg=Theme.TEXT_SECONDARY).pack(side=tk.LEFT)
        ttk.Combobox(opts_row, textvariable=self.format_var, values=Config.SUPPORTED_FORMATS, width=6, state="readonly").pack(side=tk.LEFT, padx=(6, 20))
        
        tk.Label(opts_row, text="Calidad:", font=('SF Pro Display', 10), bg=Theme.BG_CARD, fg=Theme.TEXT_SECONDARY).pack(side=tk.LEFT)
        ttk.Combobox(opts_row, textvariable=self.bitrate_var, values=Config.BITRATE_OPTIONS, width=6, state="readonly").pack(side=tk.LEFT, padx=(6, 0))
        
        # Folder
        folder_row = tk.Frame(inner1, bg=Theme.BG_CARD)
        folder_row.pack(fill=tk.X, pady=(10, 0))
        
        tk.Label(folder_row, text="Guardar en:", font=('SF Pro Display', 10), bg=Theme.BG_CARD, fg=Theme.TEXT_SECONDARY).pack(side=tk.LEFT)
        
        folder_entry = tk.Entry(folder_row, textvariable=self.outdir_var, font=('SF Pro Display', 10),
                               bg=Theme.BG_INPUT, fg=Theme.TEXT_PRIMARY, relief=tk.FLAT)
        folder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8), ipady=4)
        
        tk.Button(folder_row, text="📁", font=('SF Pro Display', 11), bg=Theme.BG_INPUT, fg=Theme.TEXT_PRIMARY,
                 relief=tk.FLAT, cursor="hand2", command=self._choose_folder).pack(side=tk.RIGHT)
        
        # Queue display card
        card2 = tk.Frame(parent, bg=Theme.BG_CARD)
        card2.pack(fill=tk.BOTH, expand=True, pady=(0, 10), padx=5)
        inner2 = tk.Frame(card2, bg=Theme.BG_CARD)
        inner2.pack(fill=tk.BOTH, expand=True, padx=18, pady=16)
        
        header_row = tk.Frame(inner2, bg=Theme.BG_CARD)
        header_row.pack(fill=tk.X, pady=(0, 8))
        
        tk.Label(header_row, text="Cola de Descargas", font=('SF Pro Display', 11, 'bold'),
                bg=Theme.BG_CARD, fg=Theme.TEXT_PRIMARY).pack(side=tk.LEFT)
        
        self.queue_count = tk.Label(header_row, text="0 items", font=('SF Pro Display', 10),
                                   bg=Theme.BG_CARD, fg=Theme.TEXT_SECONDARY)
        self.queue_count.pack(side=tk.RIGHT)
        
        # Queue listbox
        list_frame = tk.Frame(inner2, bg=Theme.BG_INPUT)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        self.queue_listbox = tk.Listbox(list_frame, font=('SF Pro Display', 11), bg=Theme.BG_INPUT,
                                        fg=Theme.TEXT_PRIMARY, selectbackground=Theme.ACCENT,
                                        selectforeground=Theme.BG_MAIN, relief=tk.FLAT, highlightthickness=0)
        self.queue_listbox.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.queue_listbox.bind('<<ListboxSelect>>', self._on_queue_select)
        
        # Preview / status
        preview_row = tk.Frame(inner2, bg=Theme.BG_CARD)
        preview_row.pack(fill=tk.X, pady=(10, 0))
        
        self.preview_btn = ModernButton(preview_row, "▶ Preview", self._play_preview, bg_color=Theme.ACCENT_ALT, width=100, height=36)
        self.preview_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.preview_btn.set_enabled(False)
        
        self.stop_preview_btn = ModernButton(preview_row, "⏹ Stop", self._stop_preview, bg_color=Theme.BG_HOVER, fg_color=Theme.TEXT_PRIMARY, width=80, height=36)
        self.stop_preview_btn.pack(side=tk.LEFT)
        
        self.status_label = tk.Label(preview_row, text="", font=('SF Pro Display', 10),
                                     bg=Theme.BG_CARD, fg=Theme.TEXT_SECONDARY)
        self.status_label.pack(side=tk.RIGHT)
        
        # Buttons
        btn_frame = tk.Frame(parent, bg=Theme.BG_MAIN)
        btn_frame.pack(fill=tk.X, padx=5, pady=(0, 5))
        
        self.start_btn = ModernButton(btn_frame, "Descargar Todo", self._start_queue, width=150, height=44)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 8))
        
        self.cancel_btn = ModernButton(btn_frame, "Cancelar", self._cancel_queue, bg_color=Theme.ERROR, fg_color=Theme.TEXT_PRIMARY, width=100, height=44)
        self.cancel_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.cancel_btn.set_enabled(False)
        
        ModernButton(btn_frame, "Limpiar", self._clear_queue, bg_color=Theme.BG_HOVER, fg_color=Theme.TEXT_PRIMARY, width=90, height=44).pack(side=tk.LEFT)
        
        ModernButton(btn_frame, "Abrir Carpeta", self._open_folder, bg_color=Theme.BG_HOVER, fg_color=Theme.TEXT_PRIMARY, width=120, height=44).pack(side=tk.RIGHT)
    
    def _build_editor_tab(self, parent):
        card = tk.Frame(parent, bg=Theme.BG_CARD)
        card.pack(fill=tk.X, pady=(12, 10), padx=5)
        inner = tk.Frame(card, bg=Theme.BG_CARD)
        inner.pack(fill=tk.X, padx=18, pady=16)
        
        tk.Label(inner, text="Archivo de Audio", font=('SF Pro Display', 11, 'bold'),
                bg=Theme.BG_CARD, fg=Theme.TEXT_PRIMARY).pack(anchor="w", pady=(0, 8))
        
        file_row = tk.Frame(inner, bg=Theme.BG_CARD)
        file_row.pack(fill=tk.X)
        
        self.file_label = tk.Label(file_row, text="Ningún archivo seleccionado", font=('SF Pro Display', 10),
                                   bg=Theme.BG_CARD, fg=Theme.TEXT_MUTED)
        self.file_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        ModernButton(file_row, "Seleccionar", self._select_file, width=110, height=36).pack(side=tk.RIGHT)
        
        # Fields
        card2 = tk.Frame(parent, bg=Theme.BG_CARD)
        card2.pack(fill=tk.X, pady=(0, 10), padx=5)
        inner2 = tk.Frame(card2, bg=Theme.BG_CARD)
        inner2.pack(fill=tk.X, padx=18, pady=16)
        
        for label, var in [("Título", self.editor_title), ("Artista", self.editor_artist), ("Álbum", self.editor_album)]:
            row = tk.Frame(inner2, bg=Theme.BG_CARD)
            row.pack(fill=tk.X, pady=4)
            tk.Label(row, text=label, font=('SF Pro Display', 10), bg=Theme.BG_CARD, fg=Theme.TEXT_SECONDARY, width=8, anchor="w").pack(side=tk.LEFT)
            tk.Entry(row, textvariable=var, font=('SF Pro Display', 10), bg=Theme.BG_INPUT, fg=Theme.TEXT_PRIMARY, relief=tk.FLAT).pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5, padx=(8, 0))
        
        # Cover art card
        card3 = tk.Frame(parent, bg=Theme.BG_CARD)
        card3.pack(fill=tk.X, pady=(0, 10), padx=5)
        inner3 = tk.Frame(card3, bg=Theme.BG_CARD)
        inner3.pack(fill=tk.X, padx=18, pady=16)
        
        tk.Label(inner3, text="Carátula (opcional)", font=('SF Pro Display', 11, 'bold'),
                bg=Theme.BG_CARD, fg=Theme.TEXT_PRIMARY).pack(anchor="w", pady=(0, 8))
        
        cover_row = tk.Frame(inner3, bg=Theme.BG_CARD)
        cover_row.pack(fill=tk.X)
        
        self.cover_label = tk.Label(cover_row, text="Ninguna imagen seleccionada", font=('SF Pro Display', 10),
                                    bg=Theme.BG_CARD, fg=Theme.TEXT_MUTED)
        self.cover_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        ModernButton(cover_row, "Seleccionar", self._select_cover, bg_color=Theme.ACCENT_ALT, width=110, height=36).pack(side=tk.RIGHT)
        
        btn_row = tk.Frame(parent, bg=Theme.BG_MAIN)
        btn_row.pack(fill=tk.X, padx=5, pady=(0, 5))
        
        self.apply_btn = ModernButton(btn_row, "Aplicar Cambios", self._apply_meta, width=150, height=44)
        self.apply_btn.pack(side=tk.LEFT)
        self.apply_btn.set_enabled(False)
    
    # ===== Actions =====
    def _choose_folder(self):
        d = filedialog.askdirectory(initialdir=self.outdir_var.get())
        if d: self.outdir_var.set(d)
    
    def _open_folder(self):
        d = self.outdir_var.get()
        if os.path.exists(d):
            if sys.platform == 'darwin': os.system(f'open "{d}"')
            elif sys.platform == 'win32': os.startfile(d)
            else: os.system(f'xdg-open "{d}"')
    
    def _toggle_theme(self):
        if Theme.name == "dark":
            set_theme(ThemeLight)
            self.theme_var.set("light")
        else:
            set_theme(ThemeDark)
            self.theme_var.set("dark")
        
        self.config['theme'] = self.theme_var.get()
        self.config_mgr.save(self.config)
        
        # Rebuild UI
        self.root.destroy()
        new_root = tk.Tk()
        AudioDownloaderApp(new_root)
        new_root.mainloop()
    
    def _start_queue(self):
        text = self.input_text.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("Vacío", "Ingresa URLs o nombres de canciones")
            return
        
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        self.queue_mgr.clear()
        self.queue_mgr.add_items(lines)
        
        # Update config
        self.config.update({'output_dir': self.outdir_var.get(), 'format': self.format_var.get(),
                           'bitrate': self.bitrate_var.get(), 'provider': self.provider_var.get()})
        self.config_mgr.save(self.config)
        self.queue_mgr.config = self.config
        self.queue_mgr.provider = self.provider_var.get()
        
        self._refresh_queue_list()
        self.start_btn.set_enabled(False)
        self.cancel_btn.set_enabled(True)
        self.queue_mgr.start()
    
    def _cancel_queue(self):
        self.queue_mgr.cancel_all()
        self._refresh_queue_list()
        self.start_btn.set_enabled(True)
        self.cancel_btn.set_enabled(False)
        self.status_label.config(text="Cancelado")
    
    def _clear_queue(self):
        self.queue_mgr.clear()
        self.input_text.delete("1.0", tk.END)
        self.queue_listbox.delete(0, tk.END)
        self.queue_count.config(text="0 items")
        self.status_label.config(text="")
    
    def _refresh_queue_list(self):
        self.queue_listbox.delete(0, tk.END)
        for item in self.queue_mgr.queue:
            icon = {"pending": "⏸", "downloading": "⏳", "complete": "✅", "error": "❌", "canceled": "⚠️"}.get(item.status, "?")
            progress = f" [{item.progress}%]" if item.status == QueueStatus.DOWNLOADING else ""
            self.queue_listbox.insert(tk.END, f"{icon} {item.title}{progress}")
        self.queue_count.config(text=f"{len(self.queue_mgr.queue)} items")
    
    def _on_queue_select(self, e):
        sel = self.queue_listbox.curselection()
        if sel and sel[0] < len(self.queue_mgr.queue):
            self.selected_item = self.queue_mgr.queue[sel[0]]
            self.preview_btn.set_enabled(self.selected_item.preview_url is not None)
        else:
            self.selected_item = None
            self.preview_btn.set_enabled(False)
    
    def _play_preview(self):
        if self.selected_item and self.selected_item.preview_url:
            self.status_label.config(text="Cargando preview...")
            def cb(ok, err=None):
                self.root.after(0, lambda: self.status_label.config(text="▶ Reproduciendo..." if ok else f"Error: {err}"))
            self.player.play_preview(self.selected_item.preview_url, cb)
    
    def _stop_preview(self):
        self.player.stop()
        self.status_label.config(text="Preview detenido")
    
    # ===== Editor =====
    def _select_file(self):
        f = filedialog.askopenfilename(filetypes=[("Audio", "*.mp3 *.m4a *.flac")])
        if f:
            self.editor_file = f
            self.file_label.config(text=Path(f).name, fg=Theme.TEXT_PRIMARY)
            self.apply_btn.set_enabled(True)
            self._load_meta(f)
    
    def _load_meta(self, fp):
        try:
            from mutagen import File
            audio = File(fp)
            if audio and audio.tags:
                t = audio.tags
                self.editor_title.set(str(t.get('TIT2', t.get('title', ['']))[0]) if t.get('TIT2') or t.get('title') else '')
                self.editor_artist.set(str(t.get('TPE1', t.get('artist', ['']))[0]) if t.get('TPE1') or t.get('artist') else '')
                self.editor_album.set(str(t.get('TALB', t.get('album', ['']))[0]) if t.get('TALB') or t.get('album') else '')
        except: pass
    
    def _select_cover(self):
        f = filedialog.askopenfilename(filetypes=[("Imágenes", "*.jpg *.jpeg *.png"), ("Todos", "*.*")])
        if f:
            self.editor_cover = f
            self.cover_label.config(text=Path(f).name, fg=Theme.TEXT_PRIMARY)
    
    def _apply_meta(self):
        if not self.editor_file: return
        try:
            from mutagen.id3 import ID3, TIT2, TPE1, TPE2, TALB, APIC
            from mutagen.mp4 import MP4, MP4Cover
            from mutagen.flac import FLAC, Picture
            
            ext = Path(self.editor_file).suffix.lower()
            if ext == '.mp3':
                try: audio = ID3(self.editor_file)
                except: audio = ID3()
                if self.editor_title.get(): audio.delall('TIT2'); audio['TIT2'] = TIT2(encoding=3, text=self.editor_title.get())
                if self.editor_artist.get(): audio.delall('TPE1'); audio.delall('TPE2'); audio['TPE1'] = TPE1(encoding=3, text=self.editor_artist.get()); audio['TPE2'] = TPE2(encoding=3, text=self.editor_artist.get())
                if self.editor_album.get(): audio.delall('TALB'); audio['TALB'] = TALB(encoding=3, text=self.editor_album.get())
                if self.editor_cover:
                    with open(self.editor_cover, 'rb') as f:
                        data = f.read()
                    mime = 'image/png' if self.editor_cover.lower().endswith('.png') else 'image/jpeg'
                    audio.delall('APIC')
                    audio['APIC'] = APIC(encoding=3, mime=mime, type=3, desc='Cover', data=data)
                audio.save(self.editor_file, v2_version=3)
            elif ext == '.m4a':
                audio = MP4(self.editor_file)
                if self.editor_title.get(): audio['\xa9nam'] = [self.editor_title.get()]
                if self.editor_artist.get(): audio['\xa9ART'] = [self.editor_artist.get()]; audio['aART'] = [self.editor_artist.get()]
                if self.editor_album.get(): audio['\xa9alb'] = [self.editor_album.get()]
                if self.editor_cover:
                    with open(self.editor_cover, 'rb') as f:
                        data = f.read()
                    fmt = MP4Cover.FORMAT_PNG if self.editor_cover.lower().endswith('.png') else MP4Cover.FORMAT_JPEG
                    audio['covr'] = [MP4Cover(data, imageformat=fmt)]
                audio.save()
            elif ext == '.flac':
                audio = FLAC(self.editor_file)
                if self.editor_title.get(): audio['title'] = [self.editor_title.get()]
                if self.editor_artist.get(): audio['artist'] = [self.editor_artist.get()]; audio['albumartist'] = [self.editor_artist.get()]
                if self.editor_album.get(): audio['album'] = [self.editor_album.get()]
                if self.editor_cover:
                    pic = Picture()
                    pic.type = 3
                    pic.mime = 'image/png' if self.editor_cover.lower().endswith('.png') else 'image/jpeg'
                    with open(self.editor_cover, 'rb') as f:
                        pic.data = f.read()
                    audio.clear_pictures()
                    audio.add_picture(pic)
                audio.save()
            messagebox.showinfo("Éxito", "Metadatos guardados (compatible Apple Music)")
            self.editor_cover = None
            self.cover_label.config(text="Ninguna imagen seleccionada", fg=Theme.TEXT_MUTED)
        except ImportError:
            messagebox.showerror("Error", "Instala mutagen: pip install mutagen")
        except Exception as e:
            messagebox.showerror("Error", str(e))
    
    # ===== Periodic Check =====
    def _periodic_check(self):
        try:
            while True:
                msg_type, *data = self.progress_q.get_nowait()
                if msg_type == "item_status":
                    item, status, err = data
                    item.status = status
                    if err: item.error = err
                    self._refresh_queue_list()
                    if status in (QueueStatus.COMPLETE, QueueStatus.ERROR, QueueStatus.CANCELED):
                        self.queue_mgr.on_item_done()
                elif msg_type == "item_progress":
                    self._refresh_queue_list()
                elif msg_type == "item_update":
                    self._refresh_queue_list()
                elif msg_type == "queue_complete":
                    self.start_btn.set_enabled(True)
                    self.cancel_btn.set_enabled(False)
                    done = len([i for i in self.queue_mgr.queue if i.status == QueueStatus.COMPLETE])
                    self.status_label.config(text=f"✅ {done} descargados")
                    messagebox.showinfo("Completado", f"{done} canciones descargadas")
        except queue.Empty:
            pass
        self.root.after(150, self._periodic_check)
    
    def _on_close(self):
        self.queue_mgr.cancel_all()
        self.player.stop()
        self.root.destroy()

# Main
def main():
    try:
        import yt_dlp
    except ImportError:
        tk.Tk().withdraw()
        messagebox.showerror("Error", "Instala yt-dlp: pip install yt-dlp")
        sys.exit(1)
    
    root = tk.Tk()
    AudioDownloaderApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
