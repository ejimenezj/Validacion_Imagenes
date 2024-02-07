import urllib
import typing
import http
import json
import logging
import pandas as pd
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from google.cloud import bigquery
from google.cloud.bigquery import Client
from vertexai.preview.generative_models import Image
from functools import lru_cache

def get_image_bytes_from_url(image_url: str) -> bytes:
    with urllib.request.urlopen(image_url) as response:
        response = typing.cast(http.client.HTTPResponse, response)
        image_bytes = response.read()
    return image_bytes

def load_image_from_url(image_url: str) -> Image:
    image_bytes = get_image_bytes_from_url(image_url)
    return Image.from_bytes(image_bytes)

def load_valid_attributes(filename: str) -> (set, dict):
    with open(filename, 'r') as file:
        data = json.load(file)
    return set(data.keys()), data

def is_valid_attributes(atributos: dict, valid_attributos: set) -> bool:
    return set(atributos.keys()).issubset(valid_attributos)

def normalize_tipo(tipo: str) -> str:
    return tipo.lower()

@lru_cache(maxsize=1)
def cargar_tabla_atributos() -> pd.DataFrame:
    """Carga la tabla de atributos y descripciones de bigquery
    
    Returns:
        pd.DataFrame: Dataframe de atributos y descripciones
    """
    client = Client()
    query = """SELECT * FROM `crp-dev-dig-mlcatalog.us_east_4.atributos_descripcion`"""
    job = client.query(query)
    atributos = job.to_dataframe()
    return atributos

def df_to_json(df: pd.DataFrame, json_path: str):
    """Convierte un dataframe a un json

    Args:
        df (pd.DataFrame): Dataframe a convertir
        json_path (str): Path del json a guardar
    """
    df_dict = df.to_dict(orient='records')
    json_datos = {}
    for fila in df_dict:
        json_datos[fila["atributo"]] = fila['descripcion']
    json_resultado = json.dumps(json_datos, indent=3, ensure_ascii=False)
    with open(json_path, 'w', encoding='utf-8') as file:
        file.write(json_resultado)

def table_to_json(name_json: str):
    """Carga la tabla de atributos y descripciones de bigquery y la convierte a un json
    """
    atributos = cargar_tabla_atributos()
    df_to_json(atributos, name_json)

def insert_into_bigquery(response):
    table_id = "validacion_imagenes.historical_predictions"
    rows = []
    atributos = response["Atributos"]
    enriquecimiento_dict = {item['Atributo']: item['Predicciones'][0]['Valor'] for item in atributos}
    enriquecimiento_output = str(enriquecimiento_dict) 
    match_dict = {item['Atributo']: item['Predicciones'][0]['Match'] for item in atributos}
    match_output = str(match_dict) 
    fecha = response["date"]
    for result in response["Imagenes"]:
        tipo_imagen = result["Tipo"]
        img_id = result["ID"]
        validacion_imgs_output = str(result["Status"]["Validaciones"])

        rows.append({"img_id": img_id, 
                 "validacion_imgs_output": validacion_imgs_output, 
                 "enriquecimiento_output": enriquecimiento_output, 
                 "match_output": match_output,
                 "date": fecha,
                 "tipo_imagen": tipo_imagen
                 })

    client = bigquery.Client(project="crp-dev-dig-mlcatalog")
    errors = client.insert_rows_json(table_id, rows)
    if errors:
        logging.error(f"Error al insertar filas: {errors}")

def successful_response(results):
    return {
        "Status": {
            "General": "Success",
            "Details": {
                "Images": {
                    "Code": "00",
                    "Message": "Generado exitosamente."
                }
            }
        },
        "Imagenes": results["Imagenes"],
        "Atributos": results["Atributos"]
    }

def handle_error(error):
    code = "01"
    message = "Servicio no disponible."

    if isinstance(error, HTTPException):
        message = str(error.detail)
        code = "01" if error.status_code != 500 else "02"
    else:
        logging.error(f"Error no esperado: {error}")

    return JSONResponse(content={
        "Status": {
            "General": "Error",
            "Details": {
                "Images": {
                    "Code": code,
                    "Message": message
                }
            }
        }
    }, status_code=getattr(error, 'status_code', 500))
