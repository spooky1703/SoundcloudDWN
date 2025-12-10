# Audio Downloader Pro

Descargador de audio desde **SoundCloud** y **YouTube Music** con interfaz moderna.

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0+-green.svg)

## Características

- **Búsqueda inteligente** - Busca por nombre o pega URL directa
- **Cola de descargas** - Descarga múltiples canciones a la vez
- **Preview de audio** - Escucha antes de descargar
- **Temas claro/oscuro** - Interfaz moderna estilo Spotify
- **Editor de metadatos** - Edita título, artista, álbum y carátula
- **Compatible con Apple Music** - Metadatos optimizados

## Versiones

| Versión | Archivo | Descripción |
|---------|---------|-------------|
| **Desktop** | `soundcloud_downloader_improved.py` | App de escritorio con Tkinter |
| **Web** | `web_downloader.py` | Servidor Flask con UI web moderna |

## Instalación

### Requisitos
- Python 3.8+
- FFmpeg (para conversión de audio)

### Pasos

```bash
# 1. Clonar repositorio
git clone https://github.com/spooky1703/SoundcloudDWN.git
cd SoundcloudDWN

# 2. Crear entorno virtual
python3 -m venv venv
source venv/bin/activate  # Mac/Linux
# o: venv\Scripts\activate  # Windows

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Instalar FFmpeg (si no lo tienes)
# Mac:
brew install ffmpeg
# Ubuntu:
sudo apt install ffmpeg
# Windows: descargar de https://ffmpeg.org/download.html
```

## Dependencias

```txt
yt-dlp>=2024.1.0
mutagen>=1.47.0
flask>=3.0.0
pygame>=2.5.0
```

## Uso

### Versión Web (Recomendada)

```bash
python3 web_downloader.py
```

Abrir en navegador: **http://localhost:5000**

#### Pestañas:
1. **Descarga Directa**: Pega URLs o nombres, descarga con preview
2. **Búsqueda**: Busca canciones, selecciona y descarga

### Versión Desktop

```bash
python3 soundcloud_downloader_improved.py
```

#### Pestañas:
1. **Cola de Descargas**: Interfaz principal de descarga
2. **Editor Metadatos**: Edita información de archivos MP3/M4A/FLAC

## Configuración

Los archivos se descargan en:
- **Web**: `~/Downloads/AudioDownloaderWeb/`
- **Desktop**: `~/Music/AudioDownloader/`

### Formatos soportados
- MP3 (320kbps máx)
- M4A (AAC)
- FLAC (lossless)
- WAV

### Proveedores de búsqueda
- SoundCloud (`scsearch:`)
- YouTube Music (`ytsearch:`)

## Estructura del Proyecto

```
SoundCloudApp/
├── soundcloud_downloader_improved.py  # App desktop (Tkinter)
├── web_downloader.py                  # Servidor Flask
├── templates/
│   └── index.html                     # Frontend web
├── requirements.txt                   # Dependencias
├── downloader_config.json             # Configuración (auto-generado)
└── README.md
```

## API Endpoints (Versión Web)

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/api/search` | POST | Buscar canciones |
| `/api/download` | POST | Iniciar descarga |
| `/api/queue` | GET | Estado de la cola |
| `/api/preview/<id>` | GET | Stream de preview |
| `/api/download-file/<id>` | GET | Descargar archivo |
| `/api/queue/clear` | POST | Limpiar cola |

## Notas

- La calidad de audio depende del proveedor (SoundCloud suele tener mejor calidad)
- YouTube requiere un JavaScript runtime para algunos formatos (ver advertencias)
- Los archivos se nombran automáticamente como `Artista - Título.ext`
