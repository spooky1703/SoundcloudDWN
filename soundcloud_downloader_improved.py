"""
soundcloud_downloader_improved.py
Descargador GUI mejorado con yt-dlp - Versión con interfaz moderna y scrollbars
"""

import os
import sys
import threading
import queue
import time
import json
import logging
import shutil
from pathlib import Path
from typing import Optional, Dict, Any
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import yt_dlp

# ---------------------------
# Configuration & Constants
# ---------------------------
class Config:
    DEFAULT_BITRATE = "192"
    SUPPORTED_FORMATS = ["mp3", "m4a", "flac", "wav"]
    BITRATE_OPTIONS = ["320", "256", "192", "128", "96"]
    DEFAULT_OUT_TEMPLATE = "%(artist)s - %(title).200s.%(ext)s"
    FALLBACK_TEMPLATE = "%(uploader)s - %(title).200s.%(ext)s"
    CONFIG_FILE = "downloader_config.json"
    LOG_FILE = "downloader.log"
    MAX_LOG_SIZE = 1024 * 1024  # 1MB
    SUPPORTED_IMAGE_FORMATS = [("Imágenes", "*.jpg *.jpeg *.png"), ("Todos los archivos", "*.*")]

# ---------------------------
# Modern Color Scheme
# ---------------------------
class Colors:
    PRIMARY = "#2D3748"      # Gris oscuro elegante
    SECONDARY = "#4A5568"    # Gris medio
    ACCENT = "#667EEA"       # Púrpura moderno
    ACCENT_HOVER = "#5A67D8" # Púrpura más oscuro
    SUCCESS = "#48BB78"      # Verde éxito
    WARNING = "#F6AD55"      # Naranja advertencia
    ERROR = "#FC8181"        # Rojo error
    BG_LIGHT = "#F7FAFC"     # Fondo claro
    BG_CARD = "#FFFFFF"      # Fondo tarjetas
    TEXT_DARK = "#2D3748"    # Texto oscuro
    TEXT_LIGHT = "#718096"   # Texto claro
    BORDER = "#E2E8F0"       # Bordes sutiles

# ---------------------------
# Scrollable Frame Widget
# ---------------------------
class ScrollableFrame(ttk.Frame):
    """Frame con scrollbar vertical automática"""
    def __init__(self, parent, **kwargs):
        ttk.Frame.__init__(self, parent, **kwargs)
        
        # Canvas y Scrollbar
        self.canvas = tk.Canvas(self, bg=Colors.BG_LIGHT, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas, style="TFrame")
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas_frame = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        # Bind para redimensionar el frame interior
        self.canvas.bind('<Configure>', self._on_canvas_configure)
        
        # Layout
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        
        # Bind mouse wheel
        self._bind_mouse_wheel()
    
    def _on_canvas_configure(self, event):
        """Ajustar el ancho del frame interior al canvas"""
        canvas_width = event.width
        self.canvas.itemconfig(self.canvas_frame, width=canvas_width)
    
    def _bind_mouse_wheel(self):
        """Bind mouse wheel y trackpad para scroll (optimizado para Mac)"""
        def _on_mousewheel(event):
            # Mac trackpad y mouse
            if sys.platform == 'darwin':
                self.canvas.yview_scroll(-1 * event.delta, "units")
            # Windows
            elif sys.platform == 'win32':
                self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            # Linux con mouse wheel
            else:
                if event.num == 4:
                    self.canvas.yview_scroll(-1, "units")
                elif event.num == 5:
                    self.canvas.yview_scroll(1, "units")
        
        def _bind_to_mousewheel(event):
            if sys.platform == 'darwin':
                # Mac - usa MouseWheel para trackpad y mouse
                self.canvas.bind_all("<MouseWheel>", _on_mousewheel)
            elif sys.platform == 'win32':
                # Windows
                self.canvas.bind_all("<MouseWheel>", _on_mousewheel)
            else:
                # Linux
                self.canvas.bind_all("<Button-4>", _on_mousewheel)
                self.canvas.bind_all("<Button-5>", _on_mousewheel)
        
        def _unbind_from_mousewheel(event):
            if sys.platform == 'darwin':
                self.canvas.unbind_all("<MouseWheel>")
            elif sys.platform == 'win32':
                self.canvas.unbind_all("<MouseWheel>")
            else:
                self.canvas.unbind_all("<Button-4>")
                self.canvas.unbind_all("<Button-5>")
        
        self.canvas.bind('<Enter>', _bind_to_mousewheel)
        self.canvas.bind('<Leave>', _unbind_from_mousewheel)
        
        # Para Mac: bind directo adicional
        if sys.platform == 'darwin':
            self.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 * e.delta, "units"))

# ---------------------------
# Logging Setup
# ---------------------------
def setup_logging():
    """Configure logging with rotation"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(Config.LOG_FILE, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

# ---------------------------
# Configuration Manager
# ---------------------------
class ConfigManager:
    def __init__(self):
        self.config_path = Path(Config.CONFIG_FILE)
        self.default_config = {
            "output_dir": str(Path.home() / "Downloads"),
            "bitrate": Config.DEFAULT_BITRATE,
            "format": "mp3",
            "template": Config.DEFAULT_OUT_TEMPLATE,
            "create_artist_folders": False,
            "skip_existing": True,
            "max_concurrent": 3,
            "save_cover_art": True,
            "cover_format": "jpg",
            "cover_size": "original"
        }
    
    def load_config(self) -> Dict[str, Any]:
        """Load configuration from file"""
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    return {**self.default_config, **config}
        except Exception as e:
            logging.warning(f"Failed to load config: {e}")
        return self.default_config.copy()
    
    def save_config(self, config: Dict[str, Any]):
        """Save configuration to file"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logging.error(f"Failed to save config: {e}")

# ---------------------------
# Enhanced Downloader Thread
# ---------------------------
class DownloaderThread(threading.Thread):
    def __init__(self, url: str, config: Dict[str, Any], progress_queue: queue.Queue, 
                 stop_event: threading.Event, logger: logging.Logger, custom_cover: Optional[str] = None):
        super().__init__(daemon=True)
        self.url = url
        self.config = config
        self.progress_queue = progress_queue
        self.stop_event = stop_event
        self.logger = logger
        self.download_info = {}
        self.custom_cover = custom_cover
        self.temp_cover_path = None
        
    def run(self):
        try:
            self._download()
        except Exception as e:
            if self.stop_event.is_set():
                self.progress_queue.put(("canceled", "Descarga cancelada por usuario"))
            else:
                self.logger.error(f"Download error: {e}")
                self.progress_queue.put(("error", f"Error: {str(e)}"))
        finally:
            self._cleanup_temp_files()

    def _cleanup_temp_files(self):
        """Clean up temporary cover file if created"""
        if self.temp_cover_path and os.path.exists(self.temp_cover_path):
            try:
                os.remove(self.temp_cover_path)
            except Exception as e:
                self.logger.warning(f"Failed to clean temp cover: {e}")

    def _prepare_custom_cover(self, output_dir: Path) -> Optional[str]:
        """Copy custom cover to temp location for processing"""
        if not self.custom_cover or not os.path.exists(self.custom_cover):
            return None
        
        try:
            ext = Path(self.custom_cover).suffix
            temp_name = f"temp_cover_{int(time.time())}{ext}"
            self.temp_cover_path = str(output_dir / temp_name)
            shutil.copy2(self.custom_cover, self.temp_cover_path)
            return self.temp_cover_path
        except Exception as e:
            self.logger.error(f"Failed to prepare custom cover: {e}")
            return None

    def _download(self):
        """Main download logic with enhanced options and custom cover support"""
        ffmpeg_path = None
        if getattr(sys, 'frozen', False):
            basedir = sys._MEIPASS
            ffmpeg_path = os.path.join(basedir, 'ffmpeg')

        output_dir = Path(self.config['output_dir'])
        
        if self.config.get('create_artist_folders', False):
            try:
                with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                    info = ydl.extract_info(self.url, download=False)
                    artist = info.get('artist') or info.get('uploader') or 'Unknown'
                    output_dir = output_dir / self._sanitize_filename(artist)
            except Exception:
                pass
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        custom_cover_path = self._prepare_custom_cover(output_dir)
        if custom_cover_path:
            self.progress_queue.put(("status", "Portada personalizada preparada"))
        
        template = self.config.get('template', Config.DEFAULT_OUT_TEMPLATE)
        outtmpl = str(output_dir / template)
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': outtmpl,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'progress_hooks': [self._progress_hook],
            'extract_flat': False,
            'writethumbnail': not custom_cover_path,
            'writeinfojson': False,
            'embedthumbnail': False,
            'restrictfilenames': False,
            'nocheckcertificate': True,
            'socket_timeout': 30,
            'retries': 3,
            'fragment_retries': 3,
            'skip_download': False,
        }
        
        if ffmpeg_path:
            ydl_opts['ffmpeg_location'] = ffmpeg_path
        
        if self.config.get('skip_existing', True):
            ydl_opts['overwrites'] = False
        
        audio_format = self.config.get('format', 'mp3')
        bitrate = self.config.get('bitrate', Config.DEFAULT_BITRATE)
        
        postprocessors = []
        
        if audio_format in ['mp3', 'm4a', 'flac', 'wav']:
            postprocessors.append({
                'key': 'FFmpegExtractAudio',
                'preferredcodec': audio_format,
                'preferredquality': bitrate,
            })
        
        postprocessors.append({
            'key': 'FFmpegMetadata',
            'add_metadata': True,
        })
        
        if custom_cover_path:
            pass
        elif self.config.get('save_cover_art', True):
            postprocessors.append({
                'key': 'EmbedThumbnail',
                'already_have_thumbnail': False,
            })
        
        ydl_opts['postprocessors'] = postprocessors
        
        self.progress_queue.put(("status", "Extrayendo información..."))
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(self.url, download=False)
            
            self.download_info = {
                'title': info.get('title', 'Unknown'),
                'artist': info.get('artist') or info.get('uploader', 'Unknown'),
                'duration': info.get('duration'),
                'description': info.get('description', ''),
                'webpage_url': info.get('webpage_url', self.url)
            }
            
            self.progress_queue.put(("info", self.download_info))
            self.progress_queue.put(("status", "Iniciando descarga..."))
            
            ydl.download([self.url])
            
            if custom_cover_path and not self.stop_event.is_set():
                self._embed_custom_cover(output_dir, audio_format, custom_cover_path, ffmpeg_path)
            
            if not self.stop_event.is_set():
                self.progress_queue.put(("complete", "Descarga completada exitosamente"))

    def _embed_custom_cover(self, output_dir: Path, audio_format: str, cover_path: str, ffmpeg_path: Optional[str]):
        """Embed custom cover art into the downloaded audio file"""
        try:
            self.progress_queue.put(("status", "Incrustando portada personalizada..."))
            
            audio_files = list(output_dir.glob(f"*.{audio_format}"))
            if not audio_files:
                self.logger.warning("No audio file found to embed cover")
                return
            
            audio_file = max(audio_files, key=os.path.getctime)
            temp_output = audio_file.with_suffix(f'.temp{audio_file.suffix}')
            
            ffmpeg_cmd = self._build_ffmpeg_command(ffmpeg_path, audio_file, cover_path, temp_output, audio_format)
            
            import subprocess
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                os.replace(temp_output, audio_file)
                self.progress_queue.put(("status", "Portada personalizada incrustada exitosamente"))
            else:
                self.logger.error(f"FFmpeg error: {result.stderr}")
                if temp_output.exists():
                    temp_output.unlink()
                self.progress_queue.put(("status", "Advertencia: No se pudo incrustar la portada personalizada"))
                
        except Exception as e:
            self.logger.error(f"Failed to embed custom cover: {e}")
            self.progress_queue.put(("status", "Advertencia: Error al incrustar portada personalizada"))

    def _build_ffmpeg_command(self, ffmpeg_path: Optional[str], audio_file: Path, 
                             cover_path: str, output: Path, audio_format: str) -> list:
        """Build appropriate FFmpeg command for embedding cover"""
        ffmpeg_exe = ffmpeg_path if ffmpeg_path else 'ffmpeg'
        
        if audio_format == 'mp3':
            return [
                ffmpeg_exe, '-i', str(audio_file), '-i', cover_path,
                '-map', '0:a', '-map', '1:0',
                '-c:a', 'copy', '-c:v', 'mjpeg',
                '-disposition:v', 'attached_pic',
                '-id3v2_version', '3',
                '-metadata:s:v', 'title=Album cover',
                '-metadata:s:v', 'comment=Cover (front)',
                '-y', str(output)
            ]
        elif audio_format == 'm4a':
            return [
                ffmpeg_exe, '-i', str(audio_file), '-i', cover_path,
                '-map', '0:a', '-map', '1:0',
                '-c:a', 'copy', '-c:v', 'mjpeg',
                '-disposition:v', 'attached_pic',
                '-y', str(output)
            ]
        elif audio_format == 'flac':
            return [
                ffmpeg_exe, '-i', str(audio_file), '-i', cover_path,
                '-map', '0:a', '-map', '1:0',
                '-c:a', 'copy', '-c:v', 'mjpeg',
                '-disposition:v', 'attached_pic',
                '-metadata:s:v', 'title=Album cover',
                '-metadata:s:v', 'comment=Cover (front)',
                '-y', str(output)
            ]
        else:
            return [
                ffmpeg_exe, '-i', str(audio_file), '-i', cover_path,
                '-map', '0', '-map', '1',
                '-c:a', 'copy', '-c:v', 'copy',
                '-disposition:v', 'attached_pic',
                '-y', str(output)
            ]

    def _progress_hook(self, d):
        if self.stop_event.is_set():
            raise yt_dlp.DownloadError("User cancelled")
        
        status = d.get('status')
        
        if status == 'downloading':
            self._handle_download_progress(d)
        elif status == 'finished':
            filename = Path(d.get('filename', '')).name
            self.progress_queue.put(("status", f"Descarga finalizada: {filename}"))
            self.progress_queue.put(("status", "Procesando audio..."))
        elif status == 'error':
            error_msg = d.get('error', 'Unknown error')
            self.progress_queue.put(("error", f"Error en descarga: {error_msg}"))

    def _handle_download_progress(self, d):
        downloaded = d.get('downloaded_bytes', 0)
        total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
        speed = d.get('speed', 0)
        eta = d.get('eta', 0)
        filename = Path(d.get('filename', '')).name
        
        percent = None
        if total > 0:
            percent = min(100.0, (downloaded / total) * 100.0)
        
        progress_info = {
            'percent': percent,
            'downloaded': downloaded,
            'total': total,
            'speed': speed,
            'eta': eta,
            'filename': filename
        }
        self.progress_queue.put(("progress", progress_info))

    def _sanitize_filename(self, filename: str) -> str:
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '')
        return filename.strip()

# ---------------------------
# Modern UI Components
# ---------------------------
class ModernButton(tk.Canvas):
    """Custom modern button with hover effects"""
    def __init__(self, parent, text, command, bg_color=Colors.ACCENT, 
                 fg_color="white", width=120, height=40, **kwargs):
        super().__init__(parent, width=width, height=height, 
                        highlightthickness=0, **kwargs)
        self.command = command
        self.bg_color = bg_color
        self.hover_color = Colors.ACCENT_HOVER
        self.fg_color = fg_color
        self.text = text
        self.width = width
        self.height = height
        self.enabled = True
        
        self._draw_button()
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
    
    def _draw_button(self, hover=False):
        self.delete("all")
        color = self.hover_color if hover and self.enabled else self.bg_color
        if not self.enabled:
            color = Colors.TEXT_LIGHT
        
        # Rounded rectangle
        self.create_rounded_rect(0, 0, self.width, self.height, 8, fill=color, outline="")
        self.create_text(self.width//2, self.height//2, text=self.text, 
                        fill=self.fg_color, font=('Segoe UI', 10, 'bold'))
    
    def create_rounded_rect(self, x1, y1, x2, y2, radius, **kwargs):
        points = [x1+radius, y1,
                 x1+radius, y1,
                 x2-radius, y1,
                 x2-radius, y1,
                 x2, y1,
                 x2, y1+radius,
                 x2, y1+radius,
                 x2, y2-radius,
                 x2, y2-radius,
                 x2, y2,
                 x2-radius, y2,
                 x2-radius, y2,
                 x1+radius, y2,
                 x1+radius, y2,
                 x1, y2,
                 x1, y2-radius,
                 x1, y2-radius,
                 x1, y1+radius,
                 x1, y1+radius,
                 x1, y1]
        return self.create_polygon(points, smooth=True, **kwargs)
    
    def _on_click(self, event):
        if self.enabled and self.command:
            self.command()
    
    def _on_enter(self, event):
        if self.enabled:
            self._draw_button(hover=True)
    
    def _on_leave(self, event):
        self._draw_button(hover=False)
    
    def configure_state(self, state):
        self.enabled = (state != "disabled")
        self._draw_button()

# ---------------------------
# Enhanced GUI Application
# ---------------------------
class EnhancedApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Audio Downloader Pro - YouTube & SoundCloud")
        self.root.geometry("900x750")
        self.root.minsize(800, 650)
        
        # Configure colors
        self.root.configure(bg=Colors.BG_LIGHT)

        # Custom style
        self._configure_styles()

        # Initialize components
        self.logger = setup_logging()
        self.config_manager = ConfigManager()
        self.config = self.config_manager.load_config()

        # Variables
        self.url_var = tk.StringVar()
        self.outdir_var = tk.StringVar(value=self.config['output_dir'])
        self.bitrate_var = tk.StringVar(value=self.config['bitrate'])
        self.format_var = tk.StringVar(value=self.config['format'])
        self.artist_folder_var = tk.BooleanVar(value=self.config['create_artist_folders'])
        self.skip_existing_var = tk.BooleanVar(value=self.config['skip_existing'])
        self.save_cover_var = tk.BooleanVar(value=self.config.get('save_cover_art', True))
        self.cover_format_var = tk.StringVar(value=self.config.get('cover_format', 'jpg'))
        
        self.custom_cover_path = None
        self.use_custom_cover_var = tk.BooleanVar(value=False)
        
        # Variables para el editor
        self.editor_file_path = None
        self.editor_cover_path = None
        self.editor_title_var = tk.StringVar()
        self.editor_artist_var = tk.StringVar()
        self.editor_album_var = tk.StringVar()
        self.editor_year_var = tk.StringVar()
        self.editor_genre_var = tk.StringVar()

        # Queues and threading
        self.progress_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None
        self.download_info = {}

        self._build_modern_ui()
        self._periodic_check()

        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _configure_styles(self):
        """Configure modern ttk styles"""
        style = ttk.Style()
        style.theme_use('clam')
        
        # Configure notebook
        style.configure("TNotebook", background=Colors.BG_LIGHT, borderwidth=0)
        style.configure("TNotebook.Tab", 
                       background=Colors.BG_CARD,
                       foreground=Colors.TEXT_DARK,
                       padding=[20, 10],
                       font=('Segoe UI', 10))
        style.map("TNotebook.Tab",
                 background=[("selected", Colors.ACCENT)],
                 foreground=[("selected", "white")])
        
        # Configure frames
        style.configure("Card.TFrame", background=Colors.BG_CARD, relief="flat")
        style.configure("TFrame", background=Colors.BG_LIGHT)
        
        # Configure labels
        style.configure("TLabel", background=Colors.BG_LIGHT, 
                       foreground=Colors.TEXT_DARK, font=('Segoe UI', 10))
        style.configure("Title.TLabel", font=('Segoe UI', 14, 'bold'))
        style.configure("Subtitle.TLabel", font=('Segoe UI', 11), 
                       foreground=Colors.TEXT_LIGHT)
        
        # Configure entries
        style.configure("TEntry", fieldbackground="white", 
                       borderwidth=1, relief="solid")
        
        # Configure checkbuttons
        style.configure("TCheckbutton", background=Colors.BG_CARD,
                       font=('Segoe UI', 10))
        
        # Configure combobox
        style.configure("TCombobox", fieldbackground="white")
        
        # Configure progressbar
        style.configure("Custom.Horizontal.TProgressbar",
                       background=Colors.ACCENT,
                       troughcolor=Colors.BORDER,
                       borderwidth=0,
                       lightcolor=Colors.ACCENT,
                       darkcolor=Colors.ACCENT)

    def _build_modern_ui(self):
        # Header
        header = tk.Frame(self.root, bg=Colors.PRIMARY, height=90)
        header.pack(fill=tk.X, side=tk.TOP)
        header.pack_propagate(False)
        
        title_label = tk.Label(header, text="Audio Downloader Pro", 
                              bg=Colors.PRIMARY, fg="white",
                              font=('Segoe UI', 20, 'bold'))
        title_label.pack(pady=20)
        
        subtitle = tk.Label(header, text="Descarga audio de YouTube, SoundCloud y más",
                           bg=Colors.PRIMARY, fg=Colors.BG_LIGHT,
                           font=('Segoe UI', 10))
        subtitle.pack()

        # Main container
        main_container = tk.Frame(self.root, bg=Colors.BG_LIGHT)
        main_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Notebook
        self.notebook = ttk.Notebook(main_container)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Crear frames scrolleables
        self.download_frame = ScrollableFrame(self.notebook)
        self.notebook.add(self.download_frame, text="  Descarga  ")

        self.settings_frame = ScrollableFrame(self.notebook)
        self.notebook.add(self.settings_frame, text="  Configuración  ")

        self.info_frame = ScrollableFrame(self.notebook)
        self.notebook.add(self.info_frame, text="  Acerca de  ")
        
        self.editor_frame = ScrollableFrame(self.notebook)
        self.notebook.add(self.editor_frame, text="  Editor de Metadatos  ")

        self._build_download_tab()
        self._build_settings_tab()
        self._build_info_tab()
        self._build_editor_tab()

    def _create_card_frame(self, parent, title):
        """Create a modern card-style frame"""
        container = tk.Frame(parent, bg=Colors.BG_LIGHT)
        
        card = tk.Frame(container, bg=Colors.BG_CARD, relief="flat", 
                       highlightbackground=Colors.BORDER, highlightthickness=1)
        card.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        
        if title:
            header = tk.Frame(card, bg=Colors.BG_CARD)
            header.pack(fill=tk.X, padx=20, pady=(15, 10))
            tk.Label(header, text=title, bg=Colors.BG_CARD,
                    fg=Colors.TEXT_DARK, font=('Segoe UI', 12, 'bold')).pack(anchor="w")
            
            separator = tk.Frame(card, bg=Colors.BORDER, height=1)
            separator.pack(fill=tk.X, padx=20)
        
        content = tk.Frame(card, bg=Colors.BG_CARD)
        content.pack(fill=tk.BOTH, expand=True, padx=20, pady=15)
        
        return container, content

    def _build_download_tab(self):
        # Usar scrollable_frame en lugar de download_frame directamente
        frame = self.download_frame.scrollable_frame
        frame.configure(style="TFrame")

        # URL Card
        url_card_container, url_content = self._create_card_frame(frame, "URL del Audio o Video")
        url_card_container.pack(fill=tk.X, pady=(0, 15), padx=20)
        
        # Descripción de plataformas soportadas
        platforms_frame = tk.Frame(url_content, bg=Colors.BG_CARD)
        platforms_frame.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(platforms_frame, text="Plataformas soportadas:", bg=Colors.BG_CARD,
                fg=Colors.TEXT_LIGHT, font=('Segoe UI', 9, 'italic')).pack(side=tk.LEFT, padx=(0, 8))
        
        platforms = ["YouTube", "SoundCloud", "Bandcamp", "Mixcloud", "y más..."]
        tk.Label(platforms_frame, text=" • ".join(platforms), bg=Colors.BG_CARD,
                fg=Colors.ACCENT, font=('Segoe UI', 9, 'bold')).pack(side=tk.LEFT)
        
        url_frame = tk.Frame(url_content, bg=Colors.BG_CARD)
        url_frame.pack(fill=tk.X)
        
        self.url_entry = tk.Entry(url_frame, textvariable=self.url_var, 
                                 font=('Segoe UI', 11), relief="solid",
                                 borderwidth=1, bg="white", fg=Colors.TEXT_DARK)
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8, padx=(0, 10))
        self.url_entry.focus()
        
        # Placeholder text
        self.url_entry.insert(0, "Ej: https://youtube.com/watch?v=... o https://soundcloud.com/...")
        self.url_entry.config(fg=Colors.TEXT_LIGHT)
        
        def on_url_focus_in(event):
            if self.url_entry.get() == "Ej: https://youtube.com/watch?v=... o https://soundcloud.com/...":
                self.url_entry.delete(0, tk.END)
                self.url_entry.config(fg=Colors.TEXT_DARK)
        
        def on_url_focus_out(event):
            if not self.url_entry.get():
                self.url_entry.insert(0, "Ej: https://youtube.com/watch?v=... o https://soundcloud.com/...")
                self.url_entry.config(fg=Colors.TEXT_LIGHT)
        
        self.url_entry.bind("<FocusIn>", on_url_focus_in)
        self.url_entry.bind("<FocusOut>", on_url_focus_out)
        
        paste_btn = ModernButton(url_frame, "Pegar", self._paste_from_clipboard, 
                                width=100, height=36)
        paste_btn.pack(side=tk.RIGHT)

        # Custom Cover Card
        cover_card_container, cover_content = self._create_card_frame(frame, "Portada Personalizada")
        cover_card_container.pack(fill=tk.X, pady=(0, 15), padx=20)
        
        check_frame = tk.Frame(cover_content, bg=Colors.BG_CARD)
        check_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.use_custom_cover_check = ttk.Checkbutton(
            check_frame, 
            text="Usar portada personalizada", 
            variable=self.use_custom_cover_var,
            command=self._toggle_custom_cover,
            style="TCheckbutton"
        )
        self.use_custom_cover_check.pack(anchor="w")
        
        file_frame = tk.Frame(cover_content, bg=Colors.BG_CARD)
        file_frame.pack(fill=tk.X)
        
        tk.Label(file_frame, text="Imagen:", bg=Colors.BG_CARD,
                fg=Colors.TEXT_DARK, font=('Segoe UI', 10)).pack(side=tk.LEFT, padx=(0, 10))
        
        self.cover_path_label = tk.Label(file_frame, text="Ninguna seleccionada",
                                         bg=Colors.BG_CARD, fg=Colors.TEXT_LIGHT,
                                         font=('Segoe UI', 10), anchor="w")
        self.cover_path_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.browse_cover_button = ModernButton(file_frame, "Seleccionar",
                                               self._choose_custom_cover, 
                                               width=100, height=32)
        self.browse_cover_button.pack(side=tk.RIGHT, padx=(10, 5))
        self.browse_cover_button.configure_state("disabled")
        
        self.clear_cover_button = ModernButton(file_frame, "Limpiar",
                                              self._clear_custom_cover,
                                              bg_color=Colors.SECONDARY,
                                              width=80, height=32)
        self.clear_cover_button.pack(side=tk.RIGHT)
        self.clear_cover_button.configure_state("disabled")

        # Output Configuration Card
        output_card_container, output_content = self._create_card_frame(frame, "Configuración de Salida")
        output_card_container.pack(fill=tk.X, pady=(0, 15), padx=20)
        
        tk.Label(output_content, text="Carpeta de salida", bg=Colors.BG_CARD,
                fg=Colors.TEXT_DARK, font=('Segoe UI', 10, 'bold')).pack(anchor="w", pady=(0, 5))
        
        dir_frame = tk.Frame(output_content, bg=Colors.BG_CARD)
        dir_frame.pack(fill=tk.X, pady=(0, 15))
        
        dir_entry = tk.Entry(dir_frame, textvariable=self.outdir_var,
                            font=('Segoe UI', 10), relief="solid", borderwidth=1)
        dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6, padx=(0, 10))
        
        self.browse_button = ModernButton(dir_frame, "Explorar", 
                                         self._choose_outdir, width=100, height=32)
        self.browse_button.pack(side=tk.RIGHT)
        
        # Format and Quality
        format_frame = tk.Frame(output_content, bg=Colors.BG_CARD)
        format_frame.pack(fill=tk.X, pady=(0, 15))
        
        left_format = tk.Frame(format_frame, bg=Colors.BG_CARD)
        left_format.pack(side=tk.LEFT, padx=(0, 30))
        tk.Label(left_format, text="Formato:", bg=Colors.BG_CARD,
                fg=Colors.TEXT_DARK, font=('Segoe UI', 10)).pack(side=tk.LEFT, padx=(0, 8))
        format_combo = ttk.Combobox(left_format, textvariable=self.format_var,
                                   values=Config.SUPPORTED_FORMATS, width=8, state="readonly")
        format_combo.pack(side=tk.LEFT)
        
        right_format = tk.Frame(format_frame, bg=Colors.BG_CARD)
        right_format.pack(side=tk.LEFT)
        tk.Label(right_format, text="Calidad (kbps):", bg=Colors.BG_CARD,
                fg=Colors.TEXT_DARK, font=('Segoe UI', 10)).pack(side=tk.LEFT, padx=(0, 8))
        bitrate_combo = ttk.Combobox(right_format, textvariable=self.bitrate_var,
                                    values=Config.BITRATE_OPTIONS, width=8, state="readonly")
        bitrate_combo.pack(side=tk.LEFT)
        
        # Options
        options_frame = tk.Frame(output_content, bg=Colors.BG_CARD)
        options_frame.pack(fill=tk.X)
        
        ttk.Checkbutton(options_frame, text="Crear carpetas por artista",
                       variable=self.artist_folder_var, style="TCheckbutton").pack(anchor="w", pady=2)
        ttk.Checkbutton(options_frame, text="Omitir archivos existentes",
                       variable=self.skip_existing_var, style="TCheckbutton").pack(anchor="w", pady=2)

        # Progress Card
        progress_card_container, progress_content = self._create_card_frame(frame, "Progreso")
        progress_card_container.pack(fill=tk.BOTH, expand=True, padx=20)
        
        # Control buttons
        control_frame = tk.Frame(progress_content, bg=Colors.BG_CARD)
        control_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.btn_download = ModernButton(control_frame, "Descargar", 
                                        self._on_download, width=140, height=42)
        self.btn_download.pack(side=tk.LEFT, padx=(0, 10))
        
        self.btn_cancel = ModernButton(control_frame, "Cancelar", 
                                      self._on_cancel, bg_color=Colors.ERROR,
                                      width=140, height=42)
        self.btn_cancel.pack(side=tk.LEFT, padx=(0, 10))
        self.btn_cancel.configure_state("disabled")
        
        self.open_folder_button = ModernButton(control_frame, "Abrir Carpeta",
                                              self._open_output_folder,
                                              bg_color=Colors.SECONDARY,
                                              width=140, height=42)
        self.open_folder_button.pack(side=tk.RIGHT)
        
        # Info display
        info_container = tk.Frame(progress_content, bg="#F8FAFC", relief="solid",
                                 borderwidth=1, highlightbackground=Colors.BORDER,
                                 highlightthickness=1)
        info_container.pack(fill=tk.X, pady=(0, 15))
        
        self.info_text = tk.Text(info_container, height=3, wrap='word', state=tk.DISABLED,
                                font=('Segoe UI', 9), relief=tk.FLAT, bg='#F8FAFC',
                                fg=Colors.TEXT_DARK, padx=10, pady=8)
        self.info_text.pack(fill=tk.BOTH)
        
        # Progress bar
        progress_bar_frame = tk.Frame(progress_content, bg=Colors.BG_CARD)
        progress_bar_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.progress = ttk.Progressbar(progress_bar_frame, orient=tk.HORIZONTAL,
                                       mode='determinate', style="Custom.Horizontal.TProgressbar")
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        self.progress_label = tk.Label(progress_bar_frame, text="0%", width=6,
                                      bg=Colors.BG_CARD, fg=Colors.TEXT_DARK,
                                      font=('Segoe UI', 10, 'bold'))
        self.progress_label.pack(side=tk.RIGHT)
        
        # Status label
        self.lbl_status = tk.Label(progress_content, text="Listo para descargar",
                                  font=('Segoe UI', 10), anchor="w",
                                  bg=Colors.BG_CARD, fg=Colors.TEXT_LIGHT)
        self.lbl_status.pack(fill=tk.X, pady=(0, 15))
        
        # Log area
        log_container = tk.Frame(progress_content, bg=Colors.BG_CARD)
        log_container.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(log_container, text="Registro de actividad", bg=Colors.BG_CARD,
                fg=Colors.TEXT_DARK, font=('Segoe UI', 10, 'bold')).pack(anchor="w", pady=(0, 5))
        
        log_text_container = tk.Frame(log_container, bg="white", relief="solid",
                                     borderwidth=1, highlightbackground=Colors.BORDER,
                                     highlightthickness=1)
        log_text_container.pack(fill=tk.BOTH, expand=True)
        
        self.txt_log = tk.Text(log_text_container, wrap='word', state=tk.DISABLED,
                              font=('Consolas', 9), bg='white', fg=Colors.TEXT_DARK,
                              relief="flat", padx=10, pady=8)
        scrollbar = ttk.Scrollbar(log_text_container, orient=tk.VERTICAL,
                                 command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=scrollbar.set)
        self.txt_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_settings_tab(self):
        frame = self.settings_frame.scrollable_frame
        
        # Organization Card
        org_card_container, org_content = self._create_card_frame(frame, "Organización de Archivos")
        org_card_container.pack(fill=tk.X, pady=(0, 15), padx=20)
        
        ttk.Checkbutton(org_content, text="Crear carpetas por artista automáticamente",
                       variable=self.artist_folder_var, style="TCheckbutton").pack(anchor=tk.W, pady=5)
        ttk.Checkbutton(org_content, text="Omitir archivos que ya existen (no sobreescribir)",
                       variable=self.skip_existing_var, style="TCheckbutton").pack(anchor=tk.W, pady=5)

        # Cover Art Card
        cover_card_container, cover_content = self._create_card_frame(frame, "Configuración de Carátulas")
        cover_card_container.pack(fill=tk.X, pady=(0, 15), padx=20)
        
        ttk.Checkbutton(cover_content, text="Guardar carátula como archivo separado",
                       variable=self.save_cover_var, style="TCheckbutton").pack(anchor=tk.W, pady=5)
        
        format_frame = tk.Frame(cover_content, bg=Colors.BG_CARD)
        format_frame.pack(fill=tk.X, pady=(10, 0))
        tk.Label(format_frame, text="Formato de carátula:", bg=Colors.BG_CARD,
                fg=Colors.TEXT_DARK, font=('Segoe UI', 10)).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Combobox(format_frame, textvariable=self.cover_format_var,
                    values=["jpg", "png"], width=8, state="readonly").pack(side=tk.LEFT)

        # Actions Card
        actions_card_container, actions_content = self._create_card_frame(frame, "Acciones")
        actions_card_container.pack(fill=tk.X, pady=(0, 15), padx=20)
        
        btn_frame = tk.Frame(actions_content, bg=Colors.BG_CARD)
        btn_frame.pack(fill=tk.X)
        
        ModernButton(btn_frame, "Guardar Configuración", self._save_settings,
                    width=180, height=40).pack(side=tk.LEFT, padx=(0, 10))
        ModernButton(btn_frame, "Restaurar Valores", self._reset_settings,
                    bg_color=Colors.SECONDARY, width=180, height=40).pack(side=tk.LEFT, padx=(0, 10))
        ModernButton(btn_frame, "Abrir Carpeta Config", self._open_config_folder,
                    bg_color=Colors.SECONDARY, width=180, height=40).pack(side=tk.LEFT)

    def _build_info_tab(self):
        frame = self.info_frame.scrollable_frame
        
        # Header
        header_frame = tk.Frame(frame, bg=Colors.BG_LIGHT)
        header_frame.pack(fill=tk.X, pady=(20, 30), padx=20)
        
        title = tk.Label(header_frame, text="Audio Downloader Pro",
                        bg=Colors.BG_LIGHT, fg=Colors.PRIMARY,
                        font=('Segoe UI', 22, 'bold'))
        title.pack()
        
        version = tk.Label(header_frame, text="Versión 2.2 Pro - YouTube, SoundCloud y más",
                          bg=Colors.BG_LIGHT, fg=Colors.TEXT_LIGHT,
                          font=('Segoe UI', 11))
        version.pack(pady=(5, 0))
        
        author = tk.Label(header_frame, text="Desarrollado por Alonso",
                         bg=Colors.BG_LIGHT, fg=Colors.ACCENT,
                         font=('Segoe UI', 10, 'italic'))
        author.pack(pady=(5, 0))

        # Features Card
        features_card_container, features_content = self._create_card_frame(frame, "Características Principales")
        features_card_container.pack(fill=tk.X, pady=(0, 15), padx=20)
        
        features = [
            ("🎵", "Descarga audio de YouTube, SoundCloud, Bandcamp y más"),
            ("🎥", "Convierte videos de YouTube a audio de alta calidad"),
            ("🎼", "Soporte para MP3, M4A, FLAC y WAV"),
            ("🖼️", "Descarga e incrustación automática de carátulas"),
            ("✨", "Opción para incrustar portada personalizada"),
            ("📁", "Organización inteligente de archivos por artista"),
            ("🎨", "Interfaz moderna e intuitiva con scrollbars"),
            ("💾", "Configuración persistente"),
            ("📊", "Progreso de descarga en tiempo real"),
            ("🌐", "Soporta más de 1000 sitios web de video y audio")
        ]
        
        for icon, text in features:
            feature_frame = tk.Frame(features_content, bg=Colors.BG_CARD)
            feature_frame.pack(fill=tk.X, pady=3)
            tk.Label(feature_frame, text=icon, bg=Colors.BG_CARD,
                    font=('Segoe UI', 12)).pack(side=tk.LEFT, padx=(0, 10))
            tk.Label(feature_frame, text=text, bg=Colors.BG_CARD,
                    fg=Colors.TEXT_DARK, font=('Segoe UI', 10),
                    wraplength=600, justify=tk.LEFT).pack(side=tk.LEFT, anchor="w")

        # Requirements Card
        req_card_container, req_content = self._create_card_frame(frame, "Requisitos del Sistema")
        req_card_container.pack(fill=tk.X, pady=(0, 15), padx=20)
        
        requirements = [
            "Python 3.7 o superior",
            "yt-dlp (pip install yt-dlp)",
            "FFmpeg (esencial para conversión de audio y metadatos)"
        ]
        
        for req in requirements:
            req_frame = tk.Frame(req_content, bg=Colors.BG_CARD)
            req_frame.pack(fill=tk.X, pady=3)
            tk.Label(req_frame, text="•", bg=Colors.BG_CARD,
                    fg=Colors.ACCENT, font=('Segoe UI', 12, 'bold')).pack(side=tk.LEFT, padx=(0, 10))
            tk.Label(req_frame, text=req, bg=Colors.BG_CARD,
                    fg=Colors.TEXT_DARK, font=('Segoe UI', 10)).pack(side=tk.LEFT, anchor="w")

    def _build_editor_tab(self):
        """Build metadata editor tab"""
        frame = self.editor_frame.scrollable_frame
        
        # Header info
        info_header = tk.Frame(frame, bg=Colors.BG_LIGHT)
        info_header.pack(fill=tk.X, pady=(20, 20), padx=20)
        
        tk.Label(info_header, text="Editor de Metadatos y Carátula",
                bg=Colors.BG_LIGHT, fg=Colors.PRIMARY,
                font=('Segoe UI', 16, 'bold')).pack()
        
        tk.Label(info_header, text="Edita información y portada de tus archivos de audio existentes",
                bg=Colors.BG_LIGHT, fg=Colors.TEXT_LIGHT,
                font=('Segoe UI', 10)).pack(pady=(5, 0))
        
        # File Selection Card
        file_card_container, file_content = self._create_card_frame(frame, "Seleccionar Archivo de Audio")
        file_card_container.pack(fill=tk.X, pady=(0, 15), padx=20)
        
        file_select_frame = tk.Frame(file_content, bg=Colors.BG_CARD)
        file_select_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.editor_file_label = tk.Label(file_select_frame, text="Ningún archivo seleccionado",
                                         bg=Colors.BG_CARD, fg=Colors.TEXT_LIGHT,
                                         font=('Segoe UI', 10), anchor="w")
        self.editor_file_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        ModernButton(file_select_frame, "Seleccionar Archivo",
                    self._select_audio_file, width=150, height=36).pack(side=tk.RIGHT)
        
        # Current Metadata Display
        current_meta_frame = tk.Frame(file_content, bg="#F8FAFC", relief="solid",
                                     borderwidth=1, highlightbackground=Colors.BORDER,
                                     highlightthickness=1)
        current_meta_frame.pack(fill=tk.X)
        
        tk.Label(current_meta_frame, text="Metadatos actuales:",
                bg="#F8FAFC", fg=Colors.TEXT_DARK,
                font=('Segoe UI', 9, 'bold')).pack(anchor="w", padx=10, pady=(8, 5))
        
        self.editor_current_meta = tk.Text(current_meta_frame, height=4, wrap='word',
                                          state=tk.DISABLED, font=('Segoe UI', 9),
                                          relief=tk.FLAT, bg='#F8FAFC',
                                          fg=Colors.TEXT_DARK, padx=10, pady=5)
        self.editor_current_meta.pack(fill=tk.X, padx=10, pady=(0, 8))
        
        # Edit Metadata Card
        meta_card_container, meta_content = self._create_card_frame(frame, "Editar Metadatos")
        meta_card_container.pack(fill=tk.X, pady=(0, 15), padx=20)
        
        # Metadata fields
        fields = [
            ("Título:", self.editor_title_var),
            ("Artista:", self.editor_artist_var),
            ("Álbum:", self.editor_album_var),
            ("Año:", self.editor_year_var),
            ("Género:", self.editor_genre_var)
        ]
        
        for label_text, var in fields:
            field_frame = tk.Frame(meta_content, bg=Colors.BG_CARD)
            field_frame.pack(fill=tk.X, pady=5)
            
            tk.Label(field_frame, text=label_text, bg=Colors.BG_CARD,
                    fg=Colors.TEXT_DARK, font=('Segoe UI', 10),
                    width=12, anchor="w").pack(side=tk.LEFT, padx=(0, 10))
            
            tk.Entry(field_frame, textvariable=var, font=('Segoe UI', 10),
                    relief="solid", borderwidth=1).pack(side=tk.LEFT, fill=tk.X,
                                                        expand=True, ipady=4)
        
        # Cover Art Card
        cover_edit_container, cover_edit_content = self._create_card_frame(frame, "Cambiar Carátula")
        cover_edit_container.pack(fill=tk.X, pady=(0, 15), padx=20)
        
        # Current cover preview
        preview_frame = tk.Frame(cover_edit_content, bg=Colors.BG_CARD)
        preview_frame.pack(fill=tk.X, pady=(0, 15))
        
        tk.Label(preview_frame, text="Vista previa actual:",
                bg=Colors.BG_CARD, fg=Colors.TEXT_DARK,
                font=('Segoe UI', 10, 'bold')).pack(anchor="w", pady=(0, 8))
        
        self.editor_cover_preview_frame = tk.Frame(preview_frame, bg="#F0F0F0",
                                                   width=200, height=200,
                                                   relief="solid", borderwidth=1)
        self.editor_cover_preview_frame.pack(anchor="w")
        self.editor_cover_preview_frame.pack_propagate(False)
        
        self.editor_cover_preview_label = tk.Label(self.editor_cover_preview_frame,
                                                   text="Sin carátula",
                                                   bg="#F0F0F0", fg=Colors.TEXT_LIGHT,
                                                   font=('Segoe UI', 10))
        self.editor_cover_preview_label.pack(expand=True)
        
        # New cover selection
        new_cover_frame = tk.Frame(cover_edit_content, bg=Colors.BG_CARD)
        new_cover_frame.pack(fill=tk.X, pady=(15, 0))
        
        tk.Label(new_cover_frame, text="Nueva carátula:",
                bg=Colors.BG_CARD, fg=Colors.TEXT_DARK,
                font=('Segoe UI', 10, 'bold')).pack(anchor="w", pady=(0, 8))
        
        cover_select_frame = tk.Frame(new_cover_frame, bg=Colors.BG_CARD)
        cover_select_frame.pack(fill=tk.X)
        
        self.editor_new_cover_label = tk.Label(cover_select_frame,
                                               text="Ninguna imagen seleccionada",
                                               bg=Colors.BG_CARD, fg=Colors.TEXT_LIGHT,
                                               font=('Segoe UI', 10), anchor="w")
        self.editor_new_cover_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        ModernButton(cover_select_frame, "Seleccionar",
                    self._select_editor_cover, width=120, height=32).pack(side=tk.RIGHT, padx=(10, 5))
        
        ModernButton(cover_select_frame, "Limpiar",
                    self._clear_editor_cover, bg_color=Colors.SECONDARY,
                    width=100, height=32).pack(side=tk.RIGHT)
        
        # Actions Card
        actions_card_container, actions_content = self._create_card_frame(frame, "Acciones")
        actions_card_container.pack(fill=tk.X, pady=(0, 15), padx=20)
        
        actions_frame = tk.Frame(actions_content, bg=Colors.BG_CARD)
        actions_frame.pack(fill=tk.X)
        
        self.btn_apply_metadata = ModernButton(actions_frame, "Aplicar Cambios",
                                              self._apply_metadata_changes,
                                              width=160, height=42)
        self.btn_apply_metadata.pack(side=tk.LEFT, padx=(0, 10))
        self.btn_apply_metadata.configure_state("disabled")
        
        ModernButton(actions_frame, "Limpiar Todo",
                    self._clear_editor_form, bg_color=Colors.SECONDARY,
                    width=160, height=42).pack(side=tk.LEFT)
        
        # Status
        self.editor_status_label = tk.Label(actions_content, text="Selecciona un archivo para comenzar",
                                           font=('Segoe UI', 10), anchor="w",
                                           bg=Colors.BG_CARD, fg=Colors.TEXT_LIGHT)
        self.editor_status_label.pack(fill=tk.X, pady=(15, 0))

    def _select_audio_file(self):
        """Select audio file to edit"""
        filepath = filedialog.askopenfilename(
            title="Seleccionar archivo de audio",
            filetypes=[
                ("Archivos de Audio", "*.mp3 *.m4a *.flac *.wav *.ogg *.opus"),
                ("MP3", "*.mp3"),
                ("M4A/AAC", "*.m4a"),
                ("FLAC", "*.flac"),
                ("WAV", "*.wav"),
                ("Todos los archivos", "*.*")
            ],
            initialdir=self.outdir_var.get()
        )
        
        if filepath:
            self.editor_file_path = filepath
            filename = Path(filepath).name
            self.editor_file_label.config(text=filename, foreground=Colors.TEXT_DARK)
            self.btn_apply_metadata.configure_state("normal")
            self._load_audio_metadata(filepath)
            self.editor_status_label.config(text=f"Archivo cargado: {filename}",
                                           fg=Colors.SUCCESS)

    def _load_audio_metadata(self, filepath):
        """Load and display current metadata"""
        try:
            from mutagen import File
            
            audio = File(filepath)
            
            if audio is None:
                self.editor_status_label.config(text="Error: No se pudo leer el archivo",
                                               fg=Colors.ERROR)
                return
            
            # Display current metadata
            current_meta = ""
            
            if hasattr(audio, 'tags') and audio.tags:
                title = audio.tags.get('TIT2', audio.tags.get('title', ['N/A']))[0] if hasattr(audio.tags.get('TIT2', audio.tags.get('title', None)), '__getitem__') else str(audio.tags.get('TIT2', audio.tags.get('title', 'N/A')))
                artist = audio.tags.get('TPE1', audio.tags.get('artist', ['N/A']))[0] if hasattr(audio.tags.get('TPE1', audio.tags.get('artist', None)), '__getitem__') else str(audio.tags.get('TPE1', audio.tags.get('artist', 'N/A')))
                album = audio.tags.get('TALB', audio.tags.get('album', ['N/A']))[0] if hasattr(audio.tags.get('TALB', audio.tags.get('album', None)), '__getitem__') else str(audio.tags.get('TALB', audio.tags.get('album', 'N/A')))
                year = audio.tags.get('TDRC', audio.tags.get('date', ['N/A']))[0] if hasattr(audio.tags.get('TDRC', audio.tags.get('date', None)), '__getitem__') else str(audio.tags.get('TDRC', audio.tags.get('date', 'N/A')))
                genre = audio.tags.get('TCON', audio.tags.get('genre', ['N/A']))[0] if hasattr(audio.tags.get('TCON', audio.tags.get('genre', None)), '__getitem__') else str(audio.tags.get('TCON', audio.tags.get('genre', 'N/A')))
                
                current_meta = f"Título: {title}\nArtista: {artist}\nÁlbum: {album}\nAño: {year}\nGénero: {genre}"
                
                # Load into edit fields
                self.editor_title_var.set(str(title))
                self.editor_artist_var.set(str(artist))
                self.editor_album_var.set(str(album))
                self.editor_year_var.set(str(year))
                self.editor_genre_var.set(str(genre))
            else:
                current_meta = "Sin metadatos"
            
            self.editor_current_meta.config(state=tk.NORMAL)
            self.editor_current_meta.delete("1.0", tk.END)
            self.editor_current_meta.insert("1.0", current_meta)
            self.editor_current_meta.config(state=tk.DISABLED)
            
            # Try to extract cover art
            self._extract_current_cover(audio, filepath)
            
        except ImportError:
            messagebox.showwarning("Dependencia Faltante",
                                 "Se requiere 'mutagen' para editar metadatos.\n\nInstala con: pip install mutagen")
            self.editor_status_label.config(text="Error: mutagen no está instalado",
                                           fg=Colors.ERROR)
        except Exception as e:
            self.logger.error(f"Error loading metadata: {e}")
            self.editor_status_label.config(text=f"Error al cargar metadatos: {str(e)}",
                                           fg=Colors.ERROR)

    def _extract_current_cover(self, audio, filepath):
        """Extract and display current cover art"""
        try:
            from mutagen.id3 import ID3, APIC
            from mutagen.mp4 import MP4
            from mutagen.flac import FLAC, Picture
            from PIL import Image
            import io
            
            cover_data = None
            file_ext = Path(filepath).suffix.lower()
            
            if file_ext == '.mp3':
                try:
                    tags = ID3(filepath)
                    for tag in tags.getall('APIC'):
                        cover_data = tag.data
                        break
                except:
                    pass
            elif file_ext == '.m4a':
                try:
                    tags = MP4(filepath)
                    if 'covr' in tags:
                        cover_data = bytes(tags['covr'][0])
                except:
                    pass
            elif file_ext == '.flac':
                try:
                    flac = FLAC(filepath)
                    if flac.pictures:
                        cover_data = flac.pictures[0].data
                except:
                    pass
            
            if cover_data:
                # Display cover preview
                image = Image.open(io.BytesIO(cover_data))
                image.thumbnail((200, 200), Image.Resampling.LANCZOS)
                
                # Convert to PhotoImage
                from PIL import ImageTk
                photo = ImageTk.PhotoImage(image)
                
                self.editor_cover_preview_label.config(image=photo, text="")
                self.editor_cover_preview_label.image = photo  # Keep reference
            else:
                self.editor_cover_preview_label.config(image="", text="Sin carátula")
                
        except ImportError:
            messagebox.showinfo("Información",
                               "Se requiere 'Pillow' para ver carátulas.\n\nInstala con: pip install Pillow")
        except Exception as e:
            self.logger.error(f"Error extracting cover: {e}")
            self.editor_cover_preview_label.config(image="", text="Error al cargar")

    def _select_editor_cover(self):
        """Select new cover for editor"""
        filepath = filedialog.askopenfilename(
            title="Seleccionar nueva carátula",
            filetypes=Config.SUPPORTED_IMAGE_FORMATS,
            initialdir=str(Path.home())
        )
        if filepath:
            self.editor_cover_path = filepath
            filename = Path(filepath).name
            self.editor_new_cover_label.config(text=filename, foreground=Colors.TEXT_DARK)

    def _clear_editor_cover(self):
        """Clear new cover selection"""
        self.editor_cover_path = None
        self.editor_new_cover_label.config(text="Ninguna imagen seleccionada",
                                          foreground=Colors.TEXT_LIGHT)

    def _clear_editor_form(self):
        """Clear all editor fields"""
        self.editor_file_path = None
        self.editor_cover_path = None
        self.editor_file_label.config(text="Ningún archivo seleccionado",
                                     foreground=Colors.TEXT_LIGHT)
        self.editor_new_cover_label.config(text="Ninguna imagen seleccionada",
                                          foreground=Colors.TEXT_LIGHT)
        self.editor_cover_preview_label.config(image="", text="Sin carátula")
        
        self.editor_title_var.set("")
        self.editor_artist_var.set("")
        self.editor_album_var.set("")
        self.editor_year_var.set("")
        self.editor_genre_var.set("")
        
        self.editor_current_meta.config(state=tk.NORMAL)
        self.editor_current_meta.delete("1.0", tk.END)
        self.editor_current_meta.config(state=tk.DISABLED)
        
        self.btn_apply_metadata.configure_state("disabled")
        self.editor_status_label.config(text="Selecciona un archivo para comenzar",
                                       fg=Colors.TEXT_LIGHT)

    def _apply_metadata_changes(self):
        """Apply metadata and cover changes to audio file"""
        if not self.editor_file_path or not os.path.exists(self.editor_file_path):
            messagebox.showwarning("Error", "No hay archivo seleccionado")
            return
        
        try:
            from mutagen import File
            from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TCON, APIC
            from mutagen.mp4 import MP4, MP4Cover
            from mutagen.flac import FLAC, Picture
            
            filepath = self.editor_file_path
            file_ext = Path(filepath).suffix.lower()
            
            # Update metadata
            if file_ext == '.mp3':
                try:
                    audio = ID3(filepath)
                except:
                    audio = ID3()
                
                if self.editor_title_var.get():
                    audio['TIT2'] = TIT2(encoding=3, text=self.editor_title_var.get())
                if self.editor_artist_var.get():
                    audio['TPE1'] = TPE1(encoding=3, text=self.editor_artist_var.get())
                if self.editor_album_var.get():
                    audio['TALB'] = TALB(encoding=3, text=self.editor_album_var.get())
                if self.editor_year_var.get():
                    audio['TDRC'] = TDRC(encoding=3, text=self.editor_year_var.get())
                if self.editor_genre_var.get():
                    audio['TCON'] = TCON(encoding=3, text=self.editor_genre_var.get())
                
                # Add cover
                if self.editor_cover_path and os.path.exists(self.editor_cover_path):
                    with open(self.editor_cover_path, 'rb') as f:
                        cover_data = f.data()
                    
                    # Determine MIME type
                    mime = 'image/jpeg'
                    if self.editor_cover_path.lower().endswith('.png'):
                        mime = 'image/png'
                    
                    audio['APIC'] = APIC(
                        encoding=3,
                        mime=mime,
                        type=3,
                        desc='Cover',
                        data=cover_data
                    )
                
                audio.save(filepath, v2_version=3)
                
            elif file_ext == '.m4a':
                audio = MP4(filepath)
                
                if self.editor_title_var.get():
                    audio['\xa9nam'] = self.editor_title_var.get()
                if self.editor_artist_var.get():
                    audio['\xa9ART'] = self.editor_artist_var.get()
                if self.editor_album_var.get():
                    audio['\xa9alb'] = self.editor_album_var.get()
                if self.editor_year_var.get():
                    audio['\xa9day'] = self.editor_year_var.get()
                if self.editor_genre_var.get():
                    audio['\xa9gen'] = self.editor_genre_var.get()
                
                # Add cover
                if self.editor_cover_path and os.path.exists(self.editor_cover_path):
                    with open(self.editor_cover_path, 'rb') as f:
                        cover_data = f.read()
                    
                    imageformat = MP4Cover.FORMAT_JPEG
                    if self.editor_cover_path.lower().endswith('.png'):
                        imageformat = MP4Cover.FORMAT_PNG
                    
                    audio['covr'] = [MP4Cover(cover_data, imageformat=imageformat)]
                
                audio.save()
                
            elif file_ext == '.flac':
                audio = FLAC(filepath)
                
                if self.editor_title_var.get():
                    audio['title'] = self.editor_title_var.get()
                if self.editor_artist_var.get():
                    audio['artist'] = self.editor_artist_var.get()
                if self.editor_album_var.get():
                    audio['album'] = self.editor_album_var.get()
                if self.editor_year_var.get():
                    audio['date'] = self.editor_year_var.get()
                if self.editor_genre_var.get():
                    audio['genre'] = self.editor_genre_var.get()
                
                # Add cover
                if self.editor_cover_path and os.path.exists(self.editor_cover_path):
                    image = Picture()
                    image.type = 3  # Cover (front)
                    
                    mime = 'image/jpeg'
                    if self.editor_cover_path.lower().endswith('.png'):
                        mime = 'image/png'
                    image.mime = mime
                    
                    with open(self.editor_cover_path, 'rb') as f:
                        image.data = f.read()
                    
                    audio.clear_pictures()
                    audio.add_picture(image)
                
                audio.save()
            
            else:
                messagebox.showwarning("Formato no soportado",
                                     f"El formato {file_ext} no está completamente soportado para edición")
                return
            
            messagebox.showinfo("Éxito", "Metadatos actualizados correctamente")
            self.editor_status_label.config(text="✅ Cambios aplicados exitosamente",
                                           fg=Colors.SUCCESS)
            
            # Reload metadata to show changes
            self._load_audio_metadata(filepath)
            
        except ImportError:
            messagebox.showerror("Dependencia Faltante",
                               "Se requiere 'mutagen' para editar metadatos.\n\nInstala con: pip install mutagen")
        except Exception as e:
            self.logger.error(f"Error applying metadata: {e}")
            messagebox.showerror("Error", f"Error al aplicar cambios:\n\n{str(e)}")
            self.editor_status_label.config(text=f"❌ Error: {str(e)}",
                                           fg=Colors.ERROR)

    def _toggle_custom_cover(self):
        """Enable/disable custom cover controls"""
        if self.use_custom_cover_var.get():
            self.browse_cover_button.configure_state("normal")
            if self.custom_cover_path:
                self.clear_cover_button.configure_state("normal")
        else:
            self.browse_cover_button.configure_state("disabled")
            self.clear_cover_button.configure_state("disabled")

    def _choose_custom_cover(self):
        """Select custom cover image"""
        filepath = filedialog.askopenfilename(
            title="Seleccionar portada personalizada",
            filetypes=Config.SUPPORTED_IMAGE_FORMATS,
            initialdir=str(Path.home())
        )
        if filepath:
            self.custom_cover_path = filepath
            filename = Path(filepath).name
            self.cover_path_label.config(text=filename, foreground=Colors.TEXT_DARK)
            self.clear_cover_button.configure_state("normal")
            self._append_log(f"Portada personalizada seleccionada: {filename}")

    def _clear_custom_cover(self):
        """Clear custom cover selection"""
        self.custom_cover_path = None
        self.cover_path_label.config(text="Ninguna seleccionada", foreground=Colors.TEXT_LIGHT)
        self.clear_cover_button.configure_state("disabled")
        self._append_log("Portada personalizada eliminada")

    def _paste_from_clipboard(self):
        try:
            clipboard_content = self.root.clipboard_get()
            if clipboard_content and ('http' in clipboard_content.lower()):
                # Limpiar placeholder si existe
                if self.url_entry.get() == "Ej: https://youtube.com/watch?v=... o https://soundcloud.com/...":
                    self.url_entry.delete(0, tk.END)
                    self.url_entry.config(fg=Colors.TEXT_DARK)
                self.url_var.set(clipboard_content.strip())
        except Exception:
            pass

    def _choose_outdir(self):
        directory = filedialog.askdirectory(title="Seleccionar carpeta de salida", 
                                          initialdir=self.outdir_var.get())
        if directory:
            self.outdir_var.set(directory)

    def _save_settings(self):
        self.config.update({
            'output_dir': self.outdir_var.get(),
            'bitrate': self.bitrate_var.get(),
            'format': self.format_var.get(),
            'create_artist_folders': self.artist_folder_var.get(),
            'skip_existing': self.skip_existing_var.get(),
            'save_cover_art': self.save_cover_var.get(),
            'cover_format': self.cover_format_var.get()
        })
        self.config_manager.save_config(self.config)
        messagebox.showinfo("Configuración", "Configuración guardada correctamente")

    def _reset_settings(self):
        if messagebox.askyesno("Restaurar configuración", "¿Restaurar todos los valores por defecto?"):
            defaults = self.config_manager.default_config
            self.outdir_var.set(defaults['output_dir'])
            self.bitrate_var.set(defaults['bitrate'])
            self.format_var.set(defaults['format'])
            self.artist_folder_var.set(defaults['create_artist_folders'])
            self.skip_existing_var.set(defaults['skip_existing'])
            self.save_cover_var.set(defaults['save_cover_art'])
            self.cover_format_var.set(defaults['cover_format'])
            messagebox.showinfo("Configuración", "Configuración restaurada")

    def _open_output_folder(self):
        output_dir = self.outdir_var.get()
        if os.path.exists(output_dir):
            try:
                if os.name == 'nt':
                    os.startfile(output_dir)
                elif os.name == 'posix':
                    os.system(f'open "{output_dir}"' if sys.platform == 'darwin' else f'xdg-open "{output_dir}"')
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo abrir la carpeta: {e}")
        else:
            messagebox.showwarning("Carpeta no encontrada", "La carpeta de salida no existe")

    def _open_config_folder(self):
        config_dir = Path(Config.CONFIG_FILE).parent.absolute()
        try:
            if os.name == 'nt':
                os.startfile(str(config_dir))
            elif os.name == 'posix':
                os.system(f'open "{config_dir}"' if sys.platform == 'darwin' else f'xdg-open "{config_dir}"')
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo abrir la carpeta de configuración: {e}")

    def _on_download(self):
        url = self.url_var.get().strip()
        
        # Remover placeholder text si existe
        if url == "Ej: https://youtube.com/watch?v=... o https://soundcloud.com/...":
            url = ""
        
        if not url:
            messagebox.showwarning("URL vacía", "Ingresa una URL válida de YouTube, SoundCloud u otra plataforma")
            return
        
        output_dir = self.outdir_var.get()
        if not os.path.isdir(output_dir):
            messagebox.showwarning("Directorio inválido", "Selecciona un directorio válido")
            return
        
        custom_cover = None
        if self.use_custom_cover_var.get():
            if self.custom_cover_path and os.path.exists(self.custom_cover_path):
                custom_cover = self.custom_cover_path
                self._append_log(f"Usando portada personalizada: {Path(custom_cover).name}")
            else:
                messagebox.showwarning("Portada no válida", 
                                     "La portada personalizada seleccionada no existe. Se usará la portada automática.")
                self.use_custom_cover_var.set(False)
                self._clear_custom_cover()
        
        self.config.update({
            'output_dir': output_dir,
            'bitrate': self.bitrate_var.get(),
            'format': self.format_var.get(),
            'create_artist_folders': self.artist_folder_var.get(),
            'skip_existing': self.skip_existing_var.get(),
            'save_cover_art': self.save_cover_var.get(),
            'cover_format': self.cover_format_var.get()
        })
        
        self.stop_event.clear()
        self.progress['value'] = 0
        self.progress_label.config(text="0%")
        self.progress.config(mode='determinate')
        self._clear_log()
        self._update_info("")
        self.lbl_status.config(text="Preparando descarga...")
        
        self.btn_download.configure_state("disabled")
        self.btn_cancel.configure_state("normal")
        self.browse_cover_button.configure_state("disabled")
        self.clear_cover_button.configure_state("disabled")
        self.use_custom_cover_check.config(state=tk.DISABLED)
        
        self.worker = DownloaderThread(
            url=url, 
            config=self.config, 
            progress_queue=self.progress_queue,
            stop_event=self.stop_event, 
            logger=self.logger,
            custom_cover=custom_cover
        )
        self.worker.start()

    def _on_cancel(self):
        if messagebox.askyesno("Cancelar", "¿Cancelar la descarga actual?"):
            self.stop_event.set()
            self.lbl_status.config(text="Cancelando...")

    def _periodic_check(self):
        try:
            while True:
                msg_type, payload = self.progress_queue.get_nowait()
                self._handle_progress_message(msg_type, payload)
        except queue.Empty:
            pass
        
        if self.worker and not self.worker.is_alive():
            if self.btn_cancel.enabled:
                self._finish_download()
        
        self.root.after(200, self._periodic_check)

    def _handle_progress_message(self, msg_type: str, payload: Any):
        if msg_type == "progress": 
            self._update_progress(payload)
        elif msg_type == "status":
            self._append_log(payload)
            self.lbl_status.config(text=payload)
        elif msg_type == "info": 
            self._update_info_display(payload)
        elif msg_type == "complete":
            self._append_log(f"✅ {payload}")
            self.lbl_status.config(text=f"✅ {payload}", fg=Colors.SUCCESS)
            self.progress['value'] = 100
            self.progress_label.config(text="100%")
            self._finish_download(success=True)
        elif msg_type == "error":
            self._append_log(f"❌ {payload}")
            self.lbl_status.config(text=f"❌ {payload}", fg=Colors.ERROR)
            self._finish_download(success=False)
        elif msg_type == "canceled":
            self._append_log(f"⚠️ {payload}")
            self.lbl_status.config(text=f"⚠️ {payload}", fg=Colors.WARNING)
            self._finish_download(success=False)

    def _update_progress(self, info: Dict[str, Any]):
        percent = info.get('percent')
        if percent is not None:
            progress_val = max(0, min(100, percent))
            self.progress['value'] = progress_val
            self.progress_label.config(text=f"{progress_val:.0f}%")
            
            downloaded = self._format_bytes(info.get('downloaded', 0))
            total = self._format_bytes(info.get('total', 0))
            speed = self._format_speed(info.get('speed', 0))
            eta = info.get('eta', 0)
            
            status = f"{progress_val:.1f}% - {downloaded}"
            if info.get('total'): status += f" / {total}"
            if speed: status += f" - {speed}"
            if eta and eta > 0: status += f" - ETA: {eta}s"
            self.lbl_status.config(text=status, fg=Colors.TEXT_DARK)
        else:
            if self.progress['mode'] != 'indeterminate':
                self.progress.config(mode='indeterminate')
                self.progress.start(10)
            self.progress_label.config(text="...")
            downloaded = self._format_bytes(info.get('downloaded', 0))
            self.lbl_status.config(text=f"Descargando... {downloaded}", fg=Colors.TEXT_DARK)

    def _update_info_display(self, info: Dict[str, Any]):
        self.download_info = info
        info_text = f"Título: {info.get('title', 'N/A')}\n"
        info_text += f"Artista: {info.get('artist', 'N/A')}\n"
        if info.get('duration'):
            duration = time.strftime('%M:%S', time.gmtime(info['duration']))
            info_text += f"Duración: {duration}"
        self._update_info(info_text)

    def _update_info(self, text: str):
        self.info_text.config(state=tk.NORMAL)
        self.info_text.delete("1.0", tk.END)
        self.info_text.insert("1.0", text)
        self.info_text.config(state=tk.DISABLED)

    def _append_log(self, text: str):
        timestamp = time.strftime("%H:%M:%S")
        self.txt_log.config(state=tk.NORMAL)
        self.txt_log.insert(tk.END, f"[{timestamp}] {text}\n")
        self.txt_log.see(tk.END)
        self.txt_log.config(state=tk.DISABLED)

    def _clear_log(self):
        self.txt_log.config(state=tk.NORMAL)
        self.txt_log.delete("1.0", tk.END)
        self.txt_log.config(state=tk.DISABLED)

    def _finish_download(self, success: bool = False):
        if self.progress['mode'] == 'indeterminate':
            self.progress.stop()
            self.progress.config(mode='determinate')
        
        if not success:
            self.progress['value'] = 0
            self.progress_label.config(text="0%")
        
        self.btn_download.configure_state("normal")
        self.btn_cancel.configure_state("disabled")
        self.use_custom_cover_check.config(state=tk.NORMAL)
        
        if self.use_custom_cover_var.get():
            self.browse_cover_button.configure_state("normal")
            if self.custom_cover_path:
                self.clear_cover_button.configure_state("normal")
        
        if success:
            if self.download_info:
                title = self.download_info.get('title', 'Audio')
                artist = self.download_info.get('artist', 'Artista desconocido')
                cover_msg = ""
                if self.custom_cover_path:
                    cover_msg = "\n\n✨ Con portada personalizada"
                messagebox.showinfo("Descarga Completada",
                                  f"'{title}' de {artist}{cover_msg}\n\n¡Descarga exitosa!")
            self.lbl_status.config(text="Descarga completada. ¡Listo para la siguiente!",
                                 fg=Colors.SUCCESS)

    def _format_bytes(self, bytes_val: int) -> str:
        if not bytes_val: return "0 B"
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_val < 1024.0: return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024.0
        return f"{bytes_val:.1f} TB"

    def _format_speed(self, speed: float) -> str:
        if not speed: return ""
        return f"{self._format_bytes(speed)}/s"

    def _on_closing(self):
        if self.worker and self.worker.is_alive():
            if messagebox.askyesno("Salir", "¿Cancelar descarga y salir?"):
                self.stop_event.set()
                self.root.after(100, self._force_close)
            return
        self.root.destroy()

    def _force_close(self):
        try:
            if self.worker and self.worker.is_alive():
                self.worker.join(timeout=1.0)
        except: 
            pass
        self.root.destroy()

# ---------------------------
# Main Entry Point
# ---------------------------
def main():
    """Main application entry point"""
    try:
        import yt_dlp
    except ImportError:
        print("Error: yt-dlp no está instalado. Instala con: pip install yt-dlp")
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Dependencia Faltante", 
                               "Error: yt-dlp no está instalado.\n\nPor favor, instálalo ejecutando:\npip install yt-dlp")
        except:
            pass
        sys.exit(1)
    
    root = tk.Tk()
    app = EnhancedApp(root)
    
    try:
        root.mainloop()
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        messagebox.showerror("Error Inesperado", f"Ocurrió un error inesperado:\n\n{e}")

if __name__ == "__main__":
    main()