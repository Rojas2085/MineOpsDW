# MineOps DW — Telemetría de Hardware, Data Warehouse Local y Monitorización Experimental

Aplicación local en Python + SQLite (WAL) con API REST documentada en OpenAPI 3.1, dashboard web responsive, exportación analítica a Excel/Power BI e informe ejecutivo imprimible en PDF.

> **Auto-adaptación multi-equipo:** Al iniciar en cualquier PC Windows (AMD, Intel, NVIDIA), MineOps DW detecta automáticamente el modelo de CPU, núcleos físicos/hilos lógicos, memoria RAM total, GPU/iGPU disponible y TDP estimado para ajustar la telemetría, los perfiles de carga (`Bajo`, `Normal`, `Rápido`) y la configuración del minero sin intervención manual.

---

## Instalación rápida para revisión en otra PC (Windows 10/11)

### Requisitos previos
- **Python 3.12+** instalado en el `PATH` (`python --version`).
- *(Opcional)* **Libre Hardware Monitor** ejecutándose con su servidor web en `127.0.0.1:8085` si deseas medir temperaturas (`°C`) y consumo real (`W`); si no está abierto, el sistema marca esas métricas como `unavailable` y estima TDP según la CPU detectada.

### Opción recomendada (1 clic)
1. Clona o descarga este repositorio y entra en la carpeta.
2. Haz doble clic en **`Iniciar_MineOps.bat`**.
   - Crea automáticamente el entorno virtual `.venv` e instala las dependencias de `pyproject.toml` si faltan.
   - Copia `.env.example` a `.env` en modo **`simulated`** seguro (sin binarios externos ni claves reales) y abre el Dashboard en `http://127.0.0.1:8765/`.
3. Para detener todos los procesos y liberar los puertos (`8765` y `18080`), haz doble clic en **`Detener_MineOps.bat`**.

### Probar minería CPU real con XMRig (Opcional y con confirmación explícita)
El repositorio **no incluye binarios ejecutables ni configuraciones con billeteras personales**. Si deseas probar el modo real adaptado a tu propia CPU:
1. Haz doble clic en **`Configurar_XMRig_Real.bat`** (o ejecuta `python scripts/setup_xmrig.py`).
2. El asistente detectará tu CPU/RAM, pedirá **autorización explícita (`s/N`)**, descargará el paquete oficial de `xmrig/xmrig` desde GitHub Releases verificando su **SHA-256**, ajustará `config.json` solo en loopback (`127.0.0.1:18080`) y actualizará tu `.env` local.
3. Vuelve a ejecutar `Iniciar_MineOps.bat`.

---

## Funcionalidades principales y rutas locales

Una vez iniciado el servidor (`http://127.0.0.1:8765/`):
- **Dashboard Web Responsive:** `http://127.0.0.1:8765/`
- **Estado de Salud y Hardware Detectado:** `http://127.0.0.1:8765/health`
- **Supervisor Térmico y Conector:** `http://127.0.0.1:8765/api/v1/supervisor/status`
- **Perfiles Adaptativos (`Bajo`, `Normal`, `Rápido 10s`):** `GET/POST /api/v1/performance`
- **Exportación ETL Excel (.xlsx — 5 hojas para Power BI):** `http://127.0.0.1:8765/api/v1/exports/excel` *(incluye scripts Power Query `M` y `DAX` en `/api/v1/exports/bi-summary`)*
- **Informe Ejecutivo Gerencial (PDF / Imprimir):** `http://127.0.0.1:8765/api/v1/exports/executive-report`
- **Conciliación Pool ↔ Binance (Read-Only):** `http://127.0.0.1:8765/api/v1/reconciliation`
- **Especificación OpenAPI 3.1:** `http://127.0.0.1:8765/openapi.json`

---

## Arranque manual desde PowerShell y pruebas automatizadas

```powershell
# 1. Crear entorno e instalar (primera vez)
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"

# 2. Validar compilación y suite completa de pruebas
$env:PYTHONPATH = "src"
python -m compileall -q src tests scripts
python -m pytest -v

# 3. Iniciar servicio manualmente en loopback
python -m mineops_dw
```

---

## Principios de seguridad y arquitectura
- **Solo loopback por defecto (`127.0.0.1`):** ni la API REST ni XMRig se exponen a Internet.
- **Sin datos falsos:** toda métrica lleva etiqueta `measured`, `estimated`, `unavailable` o `simulated`.
- **Binance solo lectura:** sin trading, retiros ni transferencias automáticas; `.env`, bases SQLite y `data/` quedan excluidos de Git (`.gitignore`).
- **Documentación detallada:** consulta `docs/PROJECT_PLAN.md`, `docs/ARCHITECTURE.md`, `docs/DATA_DICTIONARY.md` y `docs/OPERATIONS.md`.
