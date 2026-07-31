
# SubtitleTranslator

## Configuración privada en este Mac

Agregue sus credenciales de API a macOS Keychain y elija cualquier carpeta de medios. Entonces confirma las herramientas de los medios. La aplicación no tiene cuenta, telemetría o servidor operado por el desarrollador.

1. Inicio de la configuración
2. Instalar Homebrew
3. Instalar herramientas faltantes
4. Guarde las claves de la API en Keychain
5. Seleccione un archivo de medios
6. Preparar los subtítulos
7. Abierto en mpv

```bash
brew install ffmpeg mkvtoolnix mpv
```

Los cambios de idioma se aplican después de reiniciar la aplicación.

Las credenciales de la API permanecen en macOS Keychain . El procesamiento de subtítulos y archivos multimedia permanecen en este Mac. OpenAI sólo recibe texto de subtítulos cuando traduce. OpenSubtitles sólo recibe metadatos de búsqueda cuando usted hace una búsqueda. Las solicitudes van directamente a esos proveedores.

[OpenAI](https://platform.openai.com/api-keys) | [OpenSubtitles](https://www.opensubtitles.com/en/consumers) | [mpv](https://mpv.io/installation/)
