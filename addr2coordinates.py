"""
Geocodificacion de EDS de SICOM (sbi_agentes) con geopy + Nominatim.

Uso:
    uv run python addr2coordinates.py                  # solo prepara -> eds_preparadas.csv
    uv run python addr2coordinates.py --geocodificar   # prepara y geocodifica (solo ACTIVO) -> eds_con_coordenadas.csv

Reglas y hallazgos en GEOCODIFICACION.md y AGENTS.md.
"""

import re
import sys
import sqlite3 as sql  # para abrir la bd
from pathlib import Path  # para manejar rutas mas facil
import pandas as pd # para manejar datos como dataframes

#
# LECTURA DE SBI AGENTES - SQLITE
#

SQLITE_FILE = Path(__file__).parent / "sbi-cubos-2026-09-08.db"

# la bd esta en UTF-8 valido: NO usar text_factory latin-1 (corrompia municipio y departamento)
conexion = sql.connect(f"file:{SQLITE_FILE.as_posix()}?mode=ro", uri=True)

#query para traer unicamente la informacion de agentes
query = """
    SELECT DISTINCT codigo_sicom_agente,
           operador_nombre_comercial,
           bandera,
           direccion_instalacion,
           municipio_instalacion,
           codigo_municipio_instalacion,
           departamento_instalacion,
           subtipo_agente,
           nuevo_estado
    FROM sbi_agentes
    WHERE subtipo_agente in ('ESTACION DE SERVICIO AUTOMOTRIZ',
                             'ESTACION DE SERVICIO MARITIMA',
                             'ESTACION DE SERVICIO FLUVIAL')
"""

df = pd.read_sql(query, conexion)
conexion.close()

# la bd trae una fila por proveedor; direccion y estado son los mismos, basta una fila por codigo
df = df.drop_duplicates(subset="codigo_sicom_agente").reset_index(drop=True)

print("Conteo de EDS unicas por estado:")
print(df["nuevo_estado"].value_counts().to_string())

#
# NORMALIZACION DE DIRECCIONES
#

# abreviaturas de tipo de via -> nombre completo, como lo guarda OSM
TIPOS_VIA = {
    r"AVENIDA\s+CARRERA|AK": "AVENIDA CARRERA",
    r"AVENIDA\s+CALLE|AC": "AVENIDA CALLE",
    r"CALLE|CALL|CLLE|CLL|CL": "CALLE",
    r"CARRERA|CARRERRA|CARREERA|CRA|KRA|KR|CR|K": "CARRERA",
    r"DIAGONAL|DIAG|DG": "DIAGONAL",
    r"TRANSVERSAL|TRANSV|TRANS|TV|TR": "TRANSVERSAL",
    r"AVENIDA|AVDA|AVE|AV": "AVENIDA",
}

# abreviaturas rurales
OTRAS_ABREVIATURAS = {
    r"KILOMETRO|KIL|KM": "KILOMETRO",
    r"VEREDA|VDA|VRD": "VEREDA",
}

VIA = r"AVENIDA CARRERA|AVENIDA CALLE|CALLE|CARRERA|DIAGONAL|TRANSVERSAL|AVENIDA"
# letras de via: 24A, 24 A, 1BN, 5E (en algunas ciudades N/E/S pegadas indican cuadrante)
LETRA = r"[A-Z]"
CARDINAL = r"SUR|ESTE|NORTE|OESTE"

# Calle 12 Bis 71G-53 Sur  /  Carrera 28 A 7 - 152  /  Calle 24 11 26  /  Carrera 55 53 Sur - 50
PATRON_URBANO = re.compile(
    rf"^(?P<via>{VIA})\s+(?P<n1>\d+)(?:\s?(?P<l1>{LETRA}{{1,2}})\b)?"
    rf"(?:\s+(?P<bis1>BIS)\b(?:\s?(?P<l1b>{LETRA})\b)?)?"
    rf"(?:\s+(?P<card1>{CARDINAL})\b)?"
    rf"\s+(?P<n2>\d+)(?:\s?(?P<l2>{LETRA}{{1,2}})\b)?(?:\s+(?P<bis2>BIS)\b)?"
    rf"(?:\s+(?P<card2>{CARDINAL})\b)?"
    rf"\s*[-.\s]\s*(?P<n3>\d+)(?P<l3>{LETRA}?)\b"
    rf"(?:\s+(?P<card3>{CARDINAL})\b)?(?P<resto>.*)$"
)

# Carrera 4 Calle 9  (cruce sin numero de placa)
PATRON_CRUCE = re.compile(
    rf"^(?P<via1>{VIA})\s+(?P<n1>\d+\s*{LETRA}?)\s+(?:CON\s+|Y\s+|X\s+|&\s+)?(?P<via2>{VIA})\s+(?P<n2>\d+\s*{LETRA}?)\b(?P<resto>.*)$"
)

SIN_DIRECCION = {"", "SIN DEFINIR", "SIN DIRECCION", "NO APLICA", "N/A", "-"}


def limpiar_texto(texto):
    if texto is None or pd.isna(texto):
        return ""
    texto = str(texto).upper().replace(" ", " ")
    return re.sub(r"\s+", " ", texto).strip()


def expandir_abreviaturas(d):
    for patron, completo in {**TIPOS_VIA, **OTRAS_ABREVIATURAS}.items():
        # la abreviatura va seguida de punto, espacio o numero (CRA.28, CL5)
        d = re.sub(rf"\b(?:{patron})\b\.?\s*(?=[\dA-Z])", completo + " ", d)
    return d


def quitar_numeral(d):
    # "No.", "NO", "N°", "Nº", "N.º", "NRO", "NUM", "NUMERO", "#" antes de un numero -> espacio
    d = re.sub(r"(?:\bN(?:RO|UMERO|UM|O|Ú)?\b\.*|\bN(?=[°º.]))[\s.°º]*(?=\d)", " ", d)
    d = d.replace("#", " ")
    return re.sub(r"\s+", " ", d).strip()


def armar_via(via, n, l1=None, bis=None, l1b=None, card=None):
    partes = [via.title(), n + (l1 or "")]
    if bis:
        partes.append("Bis" + (" " + l1b if l1b else ""))
    if card:
        partes.append(card.title())
    return " ".join(partes)


def normalizar_direccion(direccion):
    """Devuelve (direccion_norm, tipo_direccion, complemento)."""
    d = limpiar_texto(direccion)
    if d in SIN_DIRECCION:
        return "", "sin_direccion", ""

    d = expandir_abreviaturas(d)
    d = quitar_numeral(d)

    m = PATRON_URBANO.match(d)
    if m:
        calle = armar_via(m["via"], m["n1"], m["l1"], m["bis1"], m["l1b"], m["card1"])
        placa = m["n2"] + (m["l2"] or "") + (" Bis" if m["bis2"] else "") + "-" + m["n3"] + m["l3"]
        # el cardinal de la placa (Sur/Este) se escribe al final: 53-50 Sur
        card = m["card2"] or m["card3"]
        if card:
            placa += " " + card.title()
        # barrio, lote, local, segunda direccion, etc. quedan fuera de la consulta
        return f"{calle} {placa}", "urbana", m["resto"].strip(" .,-")

    m = PATRON_CRUCE.match(d)
    if m:
        via1 = armar_via(m["via1"], m["n1"].replace(" ", ""))
        via2 = armar_via(m["via2"], m["n2"].replace(" ", ""))
        return f"{via1} & {via2}", "cruce", m["resto"].strip(" .,-")

    # rural / texto libre: se conserva limpio para la cascada de respaldo
    return d.strip(" .,-"), "rural", ""


def normalizar_municipio(municipio):
    m = limpiar_texto(municipio)
    if m in SIN_DIRECCION:
        return ""
    if m.startswith("BOGOT"):
        return "Bogotá"
    return m.title()


def normalizar_departamento(departamento):
    d = limpiar_texto(departamento)
    if d in SIN_DIRECCION or d.startswith("BOGOT"):
        return ""  # Bogota D.C. no es departamento; basta con city
    if d.startswith("ARCHIPIELAGO DE SAN ANDRES"):
        return "San Andrés y Providencia"
    return d.title()


df[["direccion_norm", "tipo_direccion", "complemento"]] = pd.DataFrame(
    df["direccion_instalacion"].map(normalizar_direccion).tolist(), index=df.index
)
df["municipio_norm"] = df["municipio_instalacion"].map(normalizar_municipio)
df["departamento_norm"] = df["departamento_instalacion"].map(normalizar_departamento)

print("Tipos de direccion (todas las EDS):")
print(pd.crosstab(df["tipo_direccion"], df["nuevo_estado"], margins=True).to_string())

prep_file = Path(__file__).parent / "eds_preparadas.csv"
df.to_csv(prep_file, index=False, encoding="utf-8-sig")
print(f"Guardado en: {prep_file}")

if "--geocodificar" not in sys.argv:
    print("Solo preparacion. Para geocodificar: --geocodificar (ver reglas de uso en GEOCODIFICACION.md)")
    sys.exit(0)

#
# GEOLOCALIZACION - ITERACION
#

from geopy.geocoders import Nominatim #para pasar de direccion a coordenadas
from geopy.extra.rate_limiter import RateLimiter
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from tqdm import tqdm # para mostrar barra de progreso


def armar_consulta(fila):
    """Consulta estructurada para urbanas; texto libre para cruces y rurales."""
    if fila["tipo_direccion"] == "urbana":
        consulta = {"street": fila["direccion_norm"], "city": fila["municipio_norm"]}
        if fila["departamento_norm"]:
            consulta["state"] = fila["departamento_norm"]
        return consulta
    partes = [fila["direccion_norm"], fila["municipio_norm"], fila["departamento_norm"]]
    return ", ".join(p for p in partes if p)


# solo EDS activas y con direccion
df_geo = df[(df["nuevo_estado"] == "ACTIVO") & (df["tipo_direccion"] != "sin_direccion")].copy()
df_geo["query_geocoding"] = df_geo.apply(armar_consulta, axis=1)
# clave de texto para deduplicar (los dict no son hashables)
df_geo["query_key"] = df_geo["query_geocoding"].map(str)

geolocator = Nominatim(user_agent="bd-demo-eds-colombia (raulest50@gmail.com)")
geocode = RateLimiter(
    geolocator.geocode,
    min_delay_seconds=1.1,          # margen sobre el 1 seg mínimo
    max_retries=2,                  # reintentos automáticos
    error_wait_seconds=5.0,         # espera si falla y reintenta
    swallow_exceptions=False        # queremos ver los errores
)

df_unique = df_geo.drop_duplicates("query_key")[["query_key", "query_geocoding"]].reset_index(drop=True)
print(f"Direcciones únicas a geocodificar: {len(df_unique)}")
print(f"Tiempo estimado: ~{len(df_unique)*1.1/60:.1f} min")


def geocodificar(consulta):
    """Devuelve (lat, lon, addresstype, geo_estado); separa 'no_encontrado' de 'error'."""
    try:
        location = geocode(consulta, country_codes='co', addressdetails=True, timeout=10)
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        return (None, None, None, f"error: {type(e).__name__}")
    if location is None:
        return (None, None, None, "no_encontrado")
    return (location.latitude, location.longitude, location.raw.get("addresstype"), "ok")


tqdm.pandas(desc="Geocodificando")  # activa .progress_apply()

df_unique[["lat", "lon", "addresstype", "geo_estado"]] = pd.DataFrame(
    df_unique["query_geocoding"].progress_apply(geocodificar).tolist(), index=df_unique.index
)

# Merge de coordenadas de vuelta al dataframe completo
df_result = df_geo.merge(df_unique.drop(columns="query_geocoding"), on="query_key", how="left")

# Guardar a CSV
output_file = Path(__file__).parent / "eds_con_coordenadas.csv"
df_result.to_csv(output_file, index=False, encoding="utf-8-sig")
print(f"Guardado en: {output_file}")

# Diagnostico de exito
total = len(df_result)
con_coords = df_result['lat'].notna().sum()
print(f"Geocodificadas: {con_coords}/{total} ({100*con_coords/total:.1f}%)")
print(df_result.groupby("tipo_direccion")["geo_estado"].value_counts().to_string())
