# Dockerfile for running tuning.py on port 5001

# Use the official Python base image
FROM python:3.10-slim
RUN apt-get update && apt-get install -y gcc python3-dev
# Set the working directory inside the container
WORKDIR /app

# Copy the tuning.py file into the container
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

ENV GOOGLE_APPLICATION_CREDENTIALS=keys.json
ENV GOOGLE_CLOUD_PROJECT=crp-dev-dig-mlcatalog

# Expose port
EXPOSE 8080

# Set the command to run the tuning.py script
CMD ["python", "main.py"]