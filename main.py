# Librerías
from fastapi import FastAPI, Body, HTTPException
from classes import ImageRequest
from Validacion_Imagenes.funciones_auxiliares import predict_image_classification_sample, successful_response, handle_error
import logging
import traceback
import time
# Inicialización de la API
app = FastAPI()

def generate_images(request:ImageRequest):
    # Definimos los parámetros para la predicción
    project = "209565165407"
    endpoint_id = "1630331652410441728"
    location = "us-central1"
    
    imagenes = []
    for num, img in enumerate(request.Imagenes):
        start = time.time()
        predicciones = predict_image_classification_sample(project, endpoint_id, img.URL, location)
        response = dict(predicciones[0])
        validaciones_response = {}

        for name in response['displayNames']:
            validaciones_response[name] = True 
        validaciones_response["atemporal"] = True
        validaciones_response["sin referencias"] = True
        validaciones_response["sin cruce de marcas"] = True
        validaciones_response["legible"] = True
        validaciones_response["medidas"] = True
        validaciones_response["medidas de la imagen"] = True

        response_object = {}
        response_object["ID"] = img.ID
        response_object_status = {}
        if all(value == True for value in validaciones_response.values()):
            response_object_status["Codigo"] = "Exito"
        else:
            response_object_status["Codigo"] = "Error"
        response_object["Status"] = response_object_status
        response_object_status["Validaciones"] = validaciones_response
        imagenes.append(response_object)
        end = time.time()   
        print(f"Imagen_{num}: {end - start}")
    return {"Imagenes":imagenes}

@app.post("/imgs")
async def generate_text_endpoint(request:ImageRequest=Body(...)):
    try:
        results = generate_images(request)
        response = successful_response(results)
        return response
    except HTTPException as he:
        return handle_error(he)
    
    except Exception as e:
        logging.error(f"Error: {e}")
        traceback.print_exc()  
        return handle_error(e)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)      