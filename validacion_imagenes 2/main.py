import threading
import vertexai
import traceback
import json
from google.cloud import bigquery
from fastapi import FastAPI, HTTPException, Body
from vertexai.preview.generative_models import GenerativeModel, Part, Image
from fastapi.responses import JSONResponse
import promptGallery
from response_processing import parse_json
from classes import ImageRequest
from gcs_utils import load_image_from_url
import pandas as pd
from google.cloud.bigquery import Client
import logging
import time

logging.basicConfig(level=logging.INFO)


app = FastAPI()

vertexai.init(project="crp-dev-dig-mlcatalog", location="us-east4") # us-central1



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

imagenes = []
def generate_single_image(img, request: ImageRequest, multimodal_model):
    logging.info(f"Generando imagen {img.ID}...")
    tipo = normalize_tipo(img.Tipo)
    global imagenes
    if tipo in ['isométrico', 'isometrico']:
        prompt = promptGallery.setIsometrico(request.Plantilla, request.Medidas, request.Atributos)
    elif tipo in ['principal', 'detalle']:
        prompt = promptGallery.setPrincipalDetalle(request.Plantilla, request.Medidas, request.Atributos)
    elif tipo == 'smoosh':
        prompt = promptGallery.setSmoosh(request.Atributos)
    else:
        raise HTTPException(status_code=400, detail=f"Tipo de imagen no válido: {img.Tipo}")
    
    if img.URI.startswith("gs://"):
        response = multimodal_model.generate_content([prompt, Part.from_uri(img.URI, mime_type="image/jpeg")])
    else:
        response = multimodal_model.generate_content([prompt, load_image_from_url(img.URL)])    
        
    response_object = {}
    response_object["ID"] = img.ID
    response_object_status = {}
    validaciones_response = parse_json(response.text)
    response_object_status["Validaciones"] = validaciones_response
    if all(value == True for value in validaciones_response.values()):
        response_object_status["Codigo"] = "Exito"
    else:
        response_object_status["Codigo"] = "Error"
    response_object["Status"] = response_object_status
    imagenes.append(response_object)

def generate_images(request: ImageRequest) -> list:
    start_time = time.time()
    multimodal_model = GenerativeModel("gemini-pro-vision")
    hilos = []
    for img in request.Imagenes:
        t = threading.Thread(target=generate_single_image, args=(img, request, multimodal_model))
        hilos.append(t)
        t.start() # Iniciamos el hilo
    for hilo in hilos:
        hilo.join() # Esperamos a que todos los hilos terminen
    
    validation_time = time.time() - start_time
    logging.info(f"Tiempo de validación: {validation_time}")

    images_part = []
    for num, img in enumerate(request.Imagenes):
        if num>=9: # Max 10 images
            break
        if img.URI.startswith("gs://"):
            images_part.append(Part.from_uri(img.URI, mime_type="image/jpeg"))
        else:
            images_part.append(load_image_from_url(img.URL))
    
        # Enriquecimiento
        start_time = time.time()
        atributos_de_interes = set(request.Atributos.keys()).intersection(attributes_descriptions.keys())
        atributos_detalle = {atributo: attributes_descriptions[atributo] for atributo in list(atributos_de_interes)}
        prompt_enriquecimiento = promptGallery.Enriquecimiento_imagenes(atributos_detalle)
        enriquecimiento_response = multimodal_model.generate_content([prompt_enriquecimiento, *images_part])
        
        # print(enriquecimiento_response.text)
        # Comparacion
        prompt_comparacion = promptGallery.comparacion(enriquecimiento_response.text, request.Atributos)
        response_comparacion = multimodal_model.generate_content([prompt_comparacion, *images_part])
        enriquecimiento_dict = parse_json(enriquecimiento_response.text)
        comparacion_dict = parse_json(response_comparacion.text)
    
    print("comparacion_dict:", comparacion_dict)
    comparacion_time = time.time() - start_time
    logging.info(f"Tiempo de enriq/comparación: {comparacion_time}")

    atributos = []
    for atributo in request.Atributos:
        atributo_dict = {}
        atributo_dict["Atributo"] = atributo
        atributo_dict["Status"] = comparacion_dict[atributo] if atributo in comparacion_dict else True
        atributo_dict["Predicciones"] = [ {"Valor": enriquecimiento_dict[atributo] if atributo in enriquecimiento_dict else request.Atributos[atributo],
                                           "Confianza":1,
                                           "Match": comparacion_dict[atributo]} ]
        atributos.append(atributo_dict)
    return {"Imagenes": imagenes, 
            "Atributos": atributos}

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
        #insert_into_bigquery(response)

        return response

    except HTTPException as he:
        return handle_error(he)

    except Exception as e:
        logging.error(f"Error: {e}")
        traceback.print_exc()  
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)