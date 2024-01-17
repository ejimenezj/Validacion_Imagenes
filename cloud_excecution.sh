#!/bin/bash


SERVICE_ACCOUNT_KEY_FILE="keys.json"
AUDIENCE='https://validacion-enriquecimiento-g7sc5y2jfa-uc.a.run.app'
API_URL='https://validacion-enriquecimiento-g7sc5y2jfa-uc.a.run.app'

gcloud auth activate-service-account --key-file="${SERVICE_ACCOUNT_KEY_FILE}"
ID_TOKEN=$(gcloud auth print-identity-token --audiences="$AUDIENCE")
ID_TOKEN='eyJhbGciOiJSUzI1NiIsImtpZCI6IjkxNDEzY2Y0ZmEwY2I5MmEzYzNmNWEwNTQ1MDkxMzJjNDc2NjA5MzciLCJ0eXAiOiJKV1QifQ.eyJhdWQiOiJodHRwczovL3ZhbGlkYWNpb24tZW5yaXF1ZWNpbWllbnRvLWc3c2M1eTJqZmEtdWMuYS5ydW4uYXBwIiwiYXpwIjoiY3JwLWRldi1kaWctbWxjYXRhbG9nLWFycXVpdGVjQGNycC1kZXYtZGlnLW1sY2F0YWxvZy5pYW0uZ3NlcnZpY2VhY2NvdW50LmNvbSIsImVtYWlsIjoiY3JwLWRldi1kaWctbWxjYXRhbG9nLWFycXVpdGVjQGNycC1kZXYtZGlnLW1sY2F0YWxvZy5pYW0uZ3NlcnZpY2VhY2NvdW50LmNvbSIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJleHAiOjE3MDQ3Nzc5MTgsImlhdCI6MTcwNDc3NDMxOCwiaXNzIjoiaHR0cHM6Ly9hY2NvdW50cy5nb29nbGUuY29tIiwic3ViIjoiMTE2MzAyOTk1MTE0MTk1MTQxODEwIn0.gcaLTdIp5HUb6FZbtiOW_9hPPA-bik5bxXtmH1SDCnQ_N_YiHzlr403SUYHLRoYpMb7YyNQZrcBOdNe3AIuCUzqV45mVajtVohHcln0YbG4OWZ8NXIcWBnJ-XZRScO8gQj_cZlV82ZhN6dPapD-uXhK4VIk_xwYQpRH4ls4VD4Ni-chOABvSMwn3EUm2EwRmv6uCX4resQ5FSrZTQxn_eVRe_6RbMcWOVsJ2pKeR7_-45WPvzlCzcVufeeKiNUtxb6CcgEZ_jyYmFVvNn5wua-jhwctVFiWk99jXRhvloH3Ln34807SNuRg8BBbCNXWC5IV8TEs7xQHHQDiyduIwCQ'
echo "ID_TOKEN: ${ID_TOKEN}"

JSON_PAYLOAD='{
        "Plantilla": "11221134 - Camas",
        "Medidas": {
            "Producto1": [
                {
                    "valor": 20,
                    "unidad": "cm"
                },
                {
                    "valor": 50,
                    "unidad": "cm"
                },
                {
                    "valor": 223,
                    "unidad": "cm"
                }
            ]
        },
        "Atributos": {
            "StorageVaD": "",
            "ColourLiverpoolVaD": "",
            "Fit": ""
        },
        "Imagenes": [
            {
                "Tipo": "isometrico",
                "ID": "123213.jpg",
                "URL": "gs://crp-dev-dig-mlcatalog/0001.JPG"
            }
        ]
     }'

curl -X POST -H "Authorization: Bearer ${ID_TOKEN}" -H "Content-Type: application/json" -d "$JSON_PAYLOAD" "${API_URL}/imgs"




# Expiración del token


PAYLOAD=$(echo $ID_TOKEN | cut -d "." -f 2)

REM=$((${#PAYLOAD} % 4))
if [ $REM -eq 2 ]; then PAYLOAD="${PAYLOAD}=="
elif [ $REM -eq 3 ]; then PAYLOAD="${PAYLOAD}="
fi

PAYLOAD=$(echo $PAYLOAD | tr '_-' '/+' | base64 -d 2> /dev/null)

if [ -z "$PAYLOAD" ]; then
    echo "Error in decoding payload."
    exit 1
fi

EXP=$(echo $PAYLOAD | jq -r '.exp')

if [ -z "$EXP" ]; then
    echo "Expiration time not found in token."
    exit 1
fi

case "$(uname)" in
    Linux*)     EXPIRY_DATE=$(date -d @$EXP);;
    Darwin*)    EXPIRY_DATE=$(date -r $EXP);;
    *)          EXPIRY_DATE="Date conversion not supported on this OS";;
esac

echo "Token expires at: $EXPIRY_DATE"
