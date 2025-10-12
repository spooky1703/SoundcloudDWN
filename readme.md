# Audio Downloader 

> **Propósito de este README:** documentación técnica exhaustiva y lista para subir a GitHub. Explica la arquitectura, el flujo, las clases principales, opciones de configuración, dependencias, instalación, uso, y notas para desarrollo/depuración. Está pensada para que cualquier desarrollador pueda leerla, ejecutar el proyecto y entender el diseño interno.

---

## Tabla de contenido

1. [Resumen del proyecto](#resumen-del-proyecto)
2. [Características principales](#características-principales)
3. [Estructura del código y componentes](#estructura-del-código-y-componentes)
4. [Detalles por componente / Clase (explicación línea a línea importante)](#detalles-por-componente--clase-explicación-línea-a-línea-importante)

   * `Config`
   * `Colors`
   * `ScrollableFrame`
   * `ConfigManager`
   * `DownloaderThread`
   * `ModernButton`
   * `EnhancedApp` (UI y lógica)
5. [Instalación y dependencias](#instalación-y-dependencias)
6. [Ejecución (uso)](#ejecución-uso)
7. [Formato de configuración y persistencia](#formato-de-configuración-y-persistencia)
8. [Formato de salida y plantillas](#formato-de-salida-y-plantillas)
9. [Manejo de portadas (cover art)](#manejo-de-portadas-cover-art)
10. [Hilos, colas y señales (concurrency)](#hilos-colas-y-señales-concurrency)
11. [Registro (logging) y archivos de log](#registro-logging-y-archivos-de-log)
12. [Errores comunes y cómo depurarlos](#errores-comunes-y-cómo-depurarlos)
13. [Extensiones, mejoras sugeridas y TODOs](#extensiones-mejoras-sugeridas-y-todos)
14. [Contribución, licencia y contacto](#contribución-licencia-y-contacto)

---

## Resumen del proyecto

**Audio Downloader Pro** es una aplicación GUI de escritorio (Tkinter) que utiliza `yt-dlp` para extraer y convertir audio de múltiples plataformas (YouTube, SoundCloud, Bandcamp, etc.). Provee interfaz moderna, progreso en tiempo real, edición de metadatos y soporte para inyectar portadas personalizadas. Toda la lógica principal se encuentra en `soundcloud_downloader_improved.py`. 

---

## Características principales

* Interfaz moderna con pestañas y scrollbars personalizadas. 
* Descarga de audio en formatos: `mp3`, `m4a`, `flac`, `wav`. (Soporte configurable). 
* Conversión y postprocesado con FFmpeg (extract + metadata + embed thumbnail). 
* Soporte para portada automática o portada personalizada incrustada con FFmpeg (o mutagen para edición posterior).  
* Editor de metadatos (usa `mutagen`) con vista previa de portada (usa `Pillow`). 
* Persistencia de configuración en `downloader_config.json`. 
* Registro (log) en `downloader.log`. 

---

## Estructura del código y componentes

Resumen de los bloques principales dentro del archivo:

* **Constantes y clases de configuración:** `Config`, `Colors`. 
* **Widgets personalizados:** `ScrollableFrame`, `ModernButton`. (Mejoran UX del Tkinter estándar). 
* **Gestión de configuración:** `ConfigManager` — carga/guarda JSON. 
* **Hilo descargador:** `DownloaderThread` — encapsula la ejecución de `yt_dlp` y postprocesos (FFmpeg, incrustado de portada). Es un `threading.Thread` que envía mensajes a la UI a través de una `queue.Queue`.  
* **Aplicación GUI:** `EnhancedApp` — maneja la UI, variables Tkinter, arranque del hilo, mensajería entre hilo y UI, editor de metadatos, etc. 

---

## Detalles por componente / Clase (explicación importante)

> A continuación explico a detalle el propósito y comportamiento interno de las partes más importantes. Donde sea relevante incluyo *por qué* se hace así y recomendaciones de mantenimiento.

### `Config`

* Contiene constantes por defecto: bitrate, formatos soportados, plantilla de salida, nombre de archivo de configuración y log, y formatos de imagen permitidos.
* Uso: centralizar valores por defecto para que sean fáciles de cambiar. 

### `Colors`

* Paleta de colores usada por la UI. Mantener aquí si quieres cambiar temas de la aplicación sin modificar widgets. 

### `ScrollableFrame`

* Widget personalizado que envuelve un `tk.Canvas` con un `ttk.Frame` interior y un scrollbar vertical.
* Observaciones técnicas:

  * Se usa `create_window` para introducir el frame dentro del canvas y se sincroniza `scrollregion` en `<Configure>`.
  * Manejo cross-platform del mouse wheel: `sys.platform == 'darwin'` (mac), `'win32'` (Windows), else (Linux). Esto previene problemas de scroll en diferentes OS. 
* Recomendación: si agregas muchos widgets, vigila el consumo de memoria; el frame mantiene referencias de elementos.

### `ConfigManager`

* `load_config()` lee `downloader_config.json` y devuelve un dict combinado con `default_config`. Si falla, retorna `default_config`.
* `save_config(config)` escribe JSON con `ensure_ascii=False` e indentado para legibilidad. 

### `DownloaderThread` (núcleo de descarga)

> **Descripción general:** es un hilo daemon que configura `yt_dlp.YoutubeDL` con opciones, maneja hooks de progreso y, tras la descarga, puede incrustar una portada personalizada usando FFmpeg. También gestiona limpieza de archivos temporales.

Puntos importantes (resumidos por responsabilidad):

1. **Inicialización**: recibe `url`, `config` (dict), `progress_queue` (para reportar mensajes a la UI), `stop_event` (para cancelar) y `logger`. También puede recibir `custom_cover` (ruta a imagen). 

2. **_prepare_custom_cover(output_dir)**:

   * Si el usuario eligió portada personalizada, la copia a un archivo temporal dentro del `output_dir` para evitar manipular directamente la original y para tener ruta accesible por FFmpeg. Maneja excepciones y registra errores. 

3. **Configuración `ydl_opts`**:

   * `format`: `'bestaudio/best'`.
   * `outtmpl`: plantilla personalizada con `template` configurada.
   * `progress_hooks`: apunta a `self._progress_hook`.
   * Opciones de postprocesamiento: `FFmpegExtractAudio` (convierte a formato elegido), `FFmpegMetadata` (agrega metadatos) y opcionalmente `EmbedThumbnail` si no se usa portada personalizada. 

4. **Uso de FFmpeg / Embedding cover**:

   * Si el usuario provee `custom_cover`, tras la descarga se ejecuta `_embed_custom_cover` que construye un comando FFmpeg distinto según el `audio_format` (mp3, m4a, flac, otros). Se ejecuta mediante `subprocess.run` y se maneja la salida y errores (reemplaza archivo si éxito, borra temp si falla). 

5. **Progreso & hooks**:

   * `_progress_hook(d)` — recibe dicts de `yt-dlp` con estados `downloading`, `finished`, `error`. Si `downloading`, delega a `_handle_download_progress`. Si `finished`, notifica y cambia estado.
   * `_handle_download_progress` extrae `downloaded_bytes`, `total_bytes` (o `total_bytes_estimate`), `speed`, `eta`, calcula `percent` y empuja `("progress", progress_info)` a la cola. Esto permite que la UI actualice barra y texto de progreso. 

6. **Cancelación**:

   * Si `stop_event` está seteado, `_progress_hook` lanza `yt_dlp.DownloadError("User cancelled")` para abortar la descarga; el `run()` captura la excepción y envía un mensaje de cancelado a la UI. 

7. **Sanitización de nombres**:

   * `_sanitize_filename` quita caracteres inválidos para evitar problemas de FS. 

> **Notas de seguridad y rendimiento:** Ejecutar FFmpeg vía `subprocess` requiere validar que la ruta es segura si el proyecto acepta entradas externas en entornos multiusuario. Además, para descargas concurrentes se podría extender el diseño agregando un pool de threads con límite `max_concurrent` (en config existe `max_concurrent` aunque el hilo actual arranca una descarga por vez). 

### `ModernButton`

* Botón custom dibujado en `tk.Canvas` con bordes redondeados y efectos hover. Útil para estética, pero si buscas accesibilidad/teclado, hay que añadir bindings para `Return` / `Space`. 

### `EnhancedApp`

* **Responsabilidades:**

  * Construcción de la UI (pestañas: Descarga, Configuración, Acerca, Editor de Metadatos).
  * Variables Tkinter que reflejan `config`.
  * Inicio y control del `DownloaderThread`.
  * Recepción de mensajes desde `progress_queue` en `_periodic_check()` y actualización de la UI en `_handle_progress_message()`.
  * Editor de metadatos con `mutagen` y vista previa de carátula con `Pillow`.  
* **Flujo de descarga:**

  1. Usuario ingresa URL y configura opciones.
  2. `_on_download` valida y actualiza `self.config`, limpia log y crea `DownloaderThread`.
  3. `DownloaderThread` envía mensajes a `progress_queue`.
  4. `_periodic_check` (scheduled every 200ms) procesa la cola y actualiza barra y logs. 

---

## Instalación y dependencias

### Dependencias (pip)

* Python 3.7+
* Recomendado crear entorno virtual: `python -m venv .venv && source .venv/bin/activate` (mac/linux) o `.venv\Scripts\activate` (Windows).

Instalar paquetes Python:

```bash
pip install -r requirements.txt
```

Si no tienes `requirements.txt`, instala manualmente:

```bash
pip install yt-dlp mutagen Pillow
```

### Dependencias externas

* **FFmpeg**: imprescindible para transcodificación e incrustado de portadas.

  * macOS: `brew install ffmpeg`
  * Ubuntu/Debian: `sudo apt install ffmpeg`
  * Windows: descargar binarios y añadir `ffmpeg` al PATH.

### Archivos generados

* `downloader_config.json` — archivo de configuración persistente (creado por `ConfigManager`). 
* `downloader.log` — archivo de log. 

---

## Ejecución (uso)

1. Clona el repo:

```bash
git clone <tu-repositorio>
cd <tu-repositorio>
```

2. Crea e instala dependencias:

```bash
python -m venv .venv
# mac/linux
source .venv/bin/activate
# windows
# .venv\Scripts\activate

pip install yt-dlp mutagen Pillow
```

3. Asegúrate de tener `ffmpeg` en el PATH. Prueba:

```bash
ffmpeg -version
```

4. Ejecuta la aplicación:

```bash
python soundcloud_downloader_improved.py
```

5. Uso básico:

* Pegar una URL (YouTube, SoundCloud, etc).
* Configurar salida, formato y bitrate.
* Opcional: seleccionar portada personalizada (checkbox + seleccionar imagen).
* Click en **Descargar**. La app mostrará progreso y registro.

---

## Formato de configuración y persistencia

`downloader_config.json` se crea/lee por `ConfigManager`. Estructura ejemplo:

```json
{
  "output_dir": "/home/usuario/Downloads",
  "bitrate": "192",
  "format": "mp3",
  "template": "%(artist)s - %(title).200s.%(ext)s",
  "create_artist_folders": false,
  "skip_existing": true,
  "max_concurrent": 3,
  "save_cover_art": true,
  "cover_format": "jpg",
  "cover_size": "original"
}
```

`ConfigManager.load_config()` mezcla este JSON con `default_config`. 

---

## Formato de salida y plantillas

* `DEFAULT_OUT_TEMPLATE = "%(artist)s - %(title).200s.%(ext)s"`
* `FALLBACK_TEMPLATE = "%(uploader)s - %(title).200s.%(ext)s"`
  Estos template utilizan tokens de `yt-dlp`. Asegúrate de que `%(artist)s` o `%(uploader)s` estén presentes según la plataforma. 

---

## Manejo de portadas (cover art)

### Portada automática

* `yt-dlp` puede descargar thumbnail y el postprocessor `EmbedThumbnail` lo incrusta si `save_cover_art` está `True` y no se usa portada personalizada. 

### Portada personalizada

* Si el usuario selecciona una portada personalizada:

  1. `DownloaderThread._prepare_custom_cover` copia la imagen a un temp dentro del `output_dir`. 
  2. Tras descargarse el audio, `_embed_custom_cover` ejecuta FFmpeg con parámetros distintos según el formato (`mp3/m4a/flac/...`) para incrustar la imagen como `attached_pic`. Maneja errores del proceso y reemplaza el archivo original por la versión con portada en caso de éxito. 

### Editor de metadatos

* El tab Editor usa `mutagen` para editar tags y extraer/carátula. Para vista previa de carátula utiliza `Pillow` (`ImageTk`). 

---

## Hilos, colas y señales (concurrency)

* Diseño sencillo: un `DownloaderThread` por descarga (daemon thread) que reporta eventos a la UI vía `queue.Queue`.
* Interface UI ejecuta `_periodic_check()` cada 200ms con `root.after(200, ...)` para vaciar la cola y actualizar estado. Esto evita bloquear el hilo principal del UI. 
* Cancelación: se usa un `threading.Event` (`stop_event`) que cuando se setea, provocará que `_progress_hook` lance una excepción para detener `yt_dlp`. 

**Recomendación si quieres concurrencia real**: implementar un `ThreadPoolExecutor` o control explícito de `max_concurrent` con semáforos y una cola de trabajos para descargas múltiples simultáneas.

---

## Registro (logging)

* `setup_logging()` configura `logging.basicConfig` con `FileHandler(Config.LOG_FILE)` y `StreamHandler(sys.stdout)`. El formato incluye timestamp y nivel. 

---

## Errores comunes y cómo depurarlos

1. **FFmpeg no encontrado**

   * Síntoma: fallo al convertir o incrustar portada (error desde `subprocess.run` y mensaje en log).
   * Solución: Instalar FFmpeg y asegurar que `ffmpeg` está en PATH. En builds congelados (`PyInstaller`) puede buscar `ffmpeg` en `sys._MEIPASS`. 

2. **Mutagen o Pillow faltantes**

   * Síntoma: el editor muestra advertencia o falla al cargar/guardar metadatos.
   * Solución: `pip install mutagen Pillow`. El programa muestra mensajes que indican instalación necesaria. 

3. **Permisos de carpeta de salida**

   * Verifica permisos del `output_dir`. Si no existe, la app crea la carpeta (`mkdir(parents=True, exist_ok=True)`) pero si la ruta es protegida, puede fallar. 

4. **Nombre de archivo inválido / caracteres**

   * El método `_sanitize_filename` elimina `<>:"/\\|?*`. Si necesitas compatibilidad para otros FS, extiéndelo. 

5. **Descargas canceladas por `yt-dlp` u errores de red**

   * `ydl_opts` incluye `retries` y `fragment_retries`. Revisa logs para `socket_timeout`. 

---

## Extensiones, mejoras sugeridas y TODOs

* Soporte de descargas en lote con gestión de cola y límite `max_concurrent` efectivo (actual `max_concurrent` en config no es usado para limitar threads). 
* Añadir comprobación y fallback para `ffmpeg` (ruta configurable en UI). 
* Mejorar accesibilidad de `ModernButton` para teclado y lectura de pantalla. 
* Agregar tests unitarios para `DownloaderThread` (mockear `yt_dlp` y `subprocess`) y para `ConfigManager`.
* Añadir CI (GitHub Actions) que valide linting y pruebas.
* Soporte para proxies y autenticación en `yt-dlp` (si el usuario descarga contenido que requiera cookies).

---

## Contribución, licencia y contacto

* **Contribuir:** abrir *issues* o *pull requests* en el repositorio. Incluye una descripción del cambio, pruebas y si aplica, screenshots.
* **Licencia:** (añade la licencia que prefieras, p.ej. MIT).
* **Contacto del autor:** `Alonso` (aparece en About). Revisa el archivo `soundcloud_downloader_improved.py` para la etiqueta `author`. 

---

## Apéndice: fragmentos clave (extractos explicativos)

> Incluyo aquí fragmentos importantes y su explicación corta.

**Configuración de `yt-dlp` y postprocesadores**

```python
ydl_opts = {
  'format': 'bestaudio/best',
  'outtmpl': outtmpl,
  'noplaylist': True,
  'progress_hooks': [self._progress_hook],
  'writethumbnail': not custom_cover_path,
  'postprocessors': postprocessors,
  # ...
}
```

Explicación: `FFmpegExtractAudio` convierte el audio al codec elegido; `FFmpegMetadata` añade tags; `EmbedThumbnail` lo incrusta si corresponde. 

**Hook de progreso**

```python
def _progress_hook(self, d):
    if self.stop_event.is_set():
        raise yt_dlp.DownloadError("User cancelled")
    status = d.get('status')
    if status == 'downloading':
        self._handle_download_progress(d)
    elif status == 'finished':
        self.progress_queue.put(("status", f"Descarga finalizada: {filename}"))
```

Explicación: mecanismo para informar a la UI del progreso y permitir cancelación inmediata. 

---

## Cómo subir a Git (sugerencia de estructura)

```
/repo-root
  ├─ soundcloud_downloader_improved.py
  ├─ README.md          <-- ESTE archivo
  ├─ requirements.txt
  ├─ downloader_config.json (opcional, .gitignore si contiene rutas personales)
  ├─ downloader.log      (agregar a .gitignore)
  └─ LICENSE
```

**.gitignore** sugerido:

```
/downloader.log
/downloader_config.json
/.venv
__pycache__/
*.pyc
```

---

## Cierre — Resumen rápido

* `soundcloud_downloader_improved.py` combina `yt-dlp`, FFmpeg y una GUI moderna hecha en Tkinter para ofrecer descargas y edición de metadatos con soporte de portadas personalizadas. La pieza central es `DownloaderThread` (descarga y postprocesos) y `EnhancedApp` (UI + gestión de hilos/colas). Revisa `ConfigManager` para persistencia y `mutagen`/`Pillow` para edición y vista previa.  


