# Dependencias
import vertexai
import traceback
import logging
from fastapi import FastAPI, HTTPException
from vertexai.preview.generative_models import GenerativeModel, Part
import promptGallery
from response_processing import parse_json
from classes import ImageRequest
from funciones_auxiliares import (load_image_from_url, 
                                  load_valid_attributes, 
                                  normalize_tipo, 
                                  insert_into_bigquery, 
                                  table_to_json, 
                                  successful_response, 
                                  handle_error)
# Inicializamos el logger para mostrar los mensajes de información
logging.basicConfig(level=logging.INFO)

# Inicializamos la aplicación
app = FastAPI()

# Inicializamos la API de Vertex AI
vertexai.init(project="crp-dev-dig-mlcatalog", location="us-east4")

# Cargamos la tabla de atributos y descripciones de bigquery y la pasamos a un json
NAME_JSON = 'atributos_descripcion.json'
table_to_json(NAME_JSON)

# Cargamos los atributos válidos y sus descripciones
_, attributes_descriptions = load_valid_attributes(NAME_JSON)

def generate_images(request: ImageRequest) -> dict:
    multimodal_model = GenerativeModel("gemini-pro-vision")
    global attributes_descriptions
    # Validaciones
    imagenes = []
    for img in request.Imagenes:
        logging.info(f"Generando imagen {img.ID}...")
        tipo = normalize_tipo(img.Tipo)
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
        print("response.text:", response.text)
        validaciones_response = parse_json(response.text)
        response_object_status["Validaciones"] = validaciones_response
        if all(value == True for value in validaciones_response.values()):
            response_object_status["Codigo"] = "Exito"
        else:
            response_object_status["Codigo"] = "Error"
        response_object["Status"] = response_object_status
        imagenes.append(response_object)

    # Enriquecimiento
    images_part = []
    for num, img in enumerate(request.Imagenes):
        if num>=9: # Max 10 images
            break
        if img.URI.startswith("gs://"):
            images_part.append(Part.from_uri(img.URI, mime_type="image/jpeg"))
        else:
            images_part.append(load_image_from_url(img.URL))
    
    atributos_de_interes = set(request.Atributos.keys()).intersection(attributes_descriptions.keys())
    atributos_detalle = {}
    for atributo in request.Atributos.keys():
        if atributo in atributos_de_interes:
            atributos_detalle[atributo] = attributes_descriptions[atributo]
        else:
            atributos_detalle[atributo] = ""
    print("0. atributos_detalle:", atributos_detalle)
    prompt_enriquecimiento = promptGallery.Enriquecimiento_imagenes(atributos_detalle)
    enriquecimiento_response = multimodal_model.generate_content([prompt_enriquecimiento]+images_part)
    print("1. enriquecimiento_response:", enriquecimiento_response.text)
    
    # Comparacion
    print(type(enriquecimiento_response.text))
    prompt_comparacion = promptGallery.comparacion(enriquecimiento_response.text, request.Atributos)
    print(type(prompt_comparacion))
    print([type(x) for x in images_part])
    response_comparacion = multimodal_model.generate_content([prompt_comparacion]+images_part)
    print("2. response_comparacion:", response_comparacion.text)
        
    enriquecimiento_dict = parse_json(enriquecimiento_response.text)
    print("3. enriquecimiento_dict:", enriquecimiento_dict)
    comparacion_dict = parse_json(response_comparacion.text)
    print("4. comparacion_dict:", comparacion_dict)

    atributos = []
    for atributo in request.Atributos:
        atributo_dict = {}
        atributo_dict["Atributo"] = atributo
        atributo_dict["Status"] = comparacion_dict[atributo] if atributo in comparacion_dict else True
        if atributo_dict["Status"] == True:
            atributo_dict["Predicciones"] = [ {"Valor": enriquecimiento_dict[atributo] if atributo in enriquecimiento_dict else "", 
                                            "Confianza":1,
                                            "Match": comparacion_dict[atributo]} ]
        else:
            atributo_dict["Predicciones"] = ""
        atributos.append(atributo_dict)
    return {"Imagenes": imagenes, 
            "Atributos": atributos}

@app.post("/imgs")
def generate_text_endpoint(request: ImageRequest): 
    try:
        results = generate_images(request)
        response = successful_response(results)

        # Insertamos los resultados en bigquery
        # insert_into_bigquery(response)

        return response

    except HTTPException as he:
        return handle_error(he)

    except Exception as e:
        logging.error(f"Error: {e}")
        traceback.print_exc()  
        return handle_error(e)

# Iniciamos el servidor web con uvicorn para ejecutar la aplicación
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

