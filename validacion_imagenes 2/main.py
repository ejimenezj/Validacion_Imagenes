import threading
import vertexai
import traceback
import json
from google.cloud import bigquery
from fastapi import FastAPI, HTTPException, Body

from vertexai.preview.generative_models import GenerativeModel, Part
from fastapi.responses import JSONResponse

import promptGallery

from response_processing import parse_json

from classes import ImageRequest

from gcs_utils import load_image_from_url

import pandas as pd
from google.cloud.bigquery import Client

import logging

from datetime import datetime

import pytz

import time

logging.basicConfig(level=logging.INFO)


app = FastAPI()

vertexai.init(project="crp-dev-dig-mlcatalog", location="us-central1")



def load_valid_attributes(filename: str) -> (set, dict):
    with open(filename, 'r') as file:
        data = json.load(file)
    return set(data.keys()), data


def is_valid_attributes(atributos: dict, valid_attributos: set) -> bool:
    return set(atributos.keys()).issubset(valid_attributos)


def normalize_tipo(tipo: str) -> str:
    return tipo.lower()

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
    for i, fila in enumerate(df_dict):
        json_datos[fila["atributo"]] = fila['descripcion']
        json_resultado = json.dumps(json_datos, indent=3, ensure_ascii=False)
    with open(json_path, 'w', encoding='utf-8') as file:
        file.write(json_resultado)

# Función para subir una imagen en bytes a un bucket de gcs
def upload_blob(bucket_name, source_file_name, destination_blob_name):
    """Uploads a file to the bucket."""
    from google.cloud import storage
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(source_file_name)


from google.cloud import storage

def upload_file(image_file, public):
    bucket_name = 'your_bucket_name'
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(image_file.filename)
    blob.upload_from_string(
        image_file.read(),
        content_type=image_file.content_type
    )
    if public:
        blob.make_public()
    return blob.public_url

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


def generate_images(request: ImageRequest) -> list:
    start_time = time.time()
    multimodal_model = GenerativeModel("gemini-pro-vision")
    imagenes = []

    def generate_prompt(img, request):
        tipo = normalize_tipo(img.Tipo)
        prompt_generators = {
            'isométrico': promptGallery.setIsometrico,
            'isometrico': promptGallery.setIsometrico,
            'principal': promptGallery.setPrincipalDetalle,
            'detalle': promptGallery.setPrincipalDetalle,
            'smoosh': promptGallery.setSmoosh,
        }

        prompt_generator = prompt_generators.get(tipo)
        if not prompt_generator:
            raise HTTPException(status_code=400, detail=f"Tipo de imagen no válido: {img.Tipo}")

        if tipo == 'smoosh':
            prompt = prompt_generator(request.Atributos)
        else:
            prompt = prompt_generator(request.Plantilla, request.Medidas, request.Atributos)

        return prompt

    def generate_single_image(img, request, multimodal_model):
        logging.info(f"Generando imagen {img.ID}...")
        prompt = generate_prompt(img, request)

        if img.URI.startswith("gs://"):
            response = multimodal_model.generate_content([prompt, Part.from_uri(img.URI, mime_type="image/jpeg")])
        else:
            response = multimodal_model.generate_content([prompt, load_image_from_url(img.URL)])

        response_object = {
            "Tipo": img.Tipo,
            "ID": img.ID,
            "Status": {
                "Validaciones": parse_json(response.text),
                "Codigo": "Exito" if all(value for value in parse_json(response.text).values()) else "Error",
            },
        }

        imagenes.append(response_object)

    # Se utilizan threads para generar las imágenes en paralelo
    # esto quiere decir que cada imagen se genera en un thread diferente
    threads = [] 
    for img in request.Imagenes:
        thread = threading.Thread(target=generate_single_image, args=(img, request, multimodal_model))
        threads.append(thread)
        thread.start() # Se ejecuta la función para cada imagen en un thread diferente

    for thread in threads:
        thread.join() # Esperamos a que todos los threads terminen

    validation_time = time.time() - start_time
    logging.info(f"Tiempo de validación: {validation_time} segundos")
    
    
    images_part = []
    for num, img in enumerate(request.Imagenes):
        if num>=9: # Max 10 images
            break
        if img.URI.startswith("gs://"):
            images_part.append(Part.from_uri(img.URI, mime_type="image/jpeg"))
        else:
            images_part.append(load_image_from_url(img.URL))
    
    start_time = time.time()

    # Parte de Enriquecimiento y Comparación
    enriquecimiento_dict = {}
    comparacion_dict = {}
    threads = []

    def enrich_and_compare_single_image(img):
        images_part = []
        if img.URI.startswith("gs://"):
            images_part.append(Part.from_uri(img.URI, mime_type="image/jpeg"))
        else:
            images_part.append(load_image_from_url(img.URL))

        # Parte de Enriquecimiento
        atributos_de_interes = set(request.Atributos.keys()).intersection(attributes_descriptions.keys())
        atributos_detalle = {atributo: attributes_descriptions[atributo] for atributo in list(atributos_de_interes)}
        prompt_enriquecimiento = promptGallery.Enriquecimiento_imagenes(atributos_detalle)
        enriquecimiento_response = multimodal_model.generate_content([prompt_enriquecimiento, *images_part])

        # Parte de Comparación
        prompt_comparacion = promptGallery.comparacion(enriquecimiento_response.text, request.Atributos)
        response_comparacion = multimodal_model.generate_content([prompt_comparacion, *images_part])

        enriquecimiento_dict[img.ID], comparacion_dict[img.ID] = parse_json(enriquecimiento_response.text), parse_json(response_comparacion.text)

    # Aquí se utilizan threads para enriquecer y comparar las imágenes en paralelo
    for num, img in enumerate(request.Imagenes):
        thread = threading.Thread(target=enrich_and_compare_single_image, args=(img,))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    enrichment_comparison_time = time.time() - start_time
    logging.info(f"Tiempo de enriquecimiento/comparación: {enrichment_comparison_time} segundos")

    atributos = []
    for atributo in request.Atributos:
        atributo_dict = {}
        atributo_dict["Atributo"] = atributo
        atributo_dict["Status"] = comparacion_dict[img.ID] if img.ID in comparacion_dict else True
        atributo_dict["Predicciones"] = [{
            "Valor": enriquecimiento_dict[img.ID] if img.ID in enriquecimiento_dict else request.Atributos[atributo],
            "Confianza": 1,
            "Match": comparacion_dict[img.ID]
        }]
        atributos.append(atributo_dict)

    return {"Imagenes": imagenes, "Atributos": atributos}

# Cargamos la tabla de bigquery con los atributos y descripciones
atributos = cargar_tabla_atributos()
# Convertimos la tabla a un json
NAME_JSON = 'atributos_descripcion1.json'
df_to_json(atributos, NAME_JSON)

valid_attributes, attributes_descriptions = load_valid_attributes(NAME_JSON)

@app.post("/imgs")
def generate_text_endpoint(request: ImageRequest = Body(...)):
    try:
        if not is_valid_attributes(request.Atributos, valid_attributes):
            raise HTTPException(status_code=400, detail=f"Descripción del error: Atributos no válidos.")

        results = generate_images(request)
        response = successful_response(results)

        # insertamos los resultados en bigquery
        insert_into_bigquery(response)

        return response

    except HTTPException as he:
        return handle_error(he)

    except Exception as e:
        logging.error(f"Error: {e}")
        traceback.print_exc()  # Print traceback
        return handle_error(e)


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
        "Atributos": results["Atributos"],
        "date": datetime.now(pytz.timezone('America/Mexico_City')).strftime("%Y-%m-%d")
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
