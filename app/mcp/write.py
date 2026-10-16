import sys
import os
import warnings
from datetime import datetime
from fastmcp import FastMCP

from maikol_utils.file_utils import make_dirs

# Suppress async generator cleanup warnings
warnings.filterwarnings("ignore", category=RuntimeWarning)

# Crea el servidor MCP para gestión de archivos
mcp = FastMCP("file_manager")

def log(msg: str):
    """Imprime logs en STDERR para que ADK no se confunda con los datos de STDOUT."""
    print(f"[FILE-MCP] {msg}", file=sys.stderr, flush=True)

@mcp.tool(name="escribir_archivo")
def escribir_archivo(nombre_archivo: str, contenido: str):
    """
    Escribe el contenido proporcionado en un archivo físico.
    
    Parámetros:
        nombre_archivo: El nombre del fichero (ej. 'debate_final.md').
        contenido: El texto completo a guardar.
    """
    
    # Variables pasadas por el proceso MCP según configuración
    log_path = os.environ.get("LOGS_PATH", "logs")
    log(f"Usando directorio de salida: {log_path} para guardar {nombre_archivo}")

    try:
        make_dirs(log_path)
        
        # Fecha y hora para evitar sobreescrituras
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = nombre_archivo.replace(".md", "")
        nombre_archivo_con_fecha = f"{base_name}_{timestamp}.md"

        file_path = os.path.join(log_path, nombre_archivo_con_fecha)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(contenido)
        
        log(f"Archivo '{file_path}' guardado exitosamente.")
        return f"Éxito: El documento se ha guardado en {file_path}"

    except Exception as e:
        log(f"Error al guardar el archivo: {str(e)}")
        return f"Error: No se pudo guardar el archivo debido a: {str(e)}"

if __name__ == "__main__":
    log("Iniciando MCP File Server...")
    mcp.run()