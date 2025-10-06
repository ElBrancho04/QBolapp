# Dockerfile

# 1. Usar una imagen base oficial de Python. 'slim' es una versión ligera.
FROM python:3.9-slim

# 2. Establecer el directorio de trabajo dentro del contenedor.
WORKDIR /app

# 3. Copiar todos los archivos de tu proyecto (tu .py, etc.) al directorio /app del contenedor.
COPY . .

# 4. (Opcional) Si tuvieras dependencias en un requirements.txt, las instalarías aquí.
# RUN pip install -r requirements.txt

# 5. El comando que se ejecutará cuando el contenedor se inicie.
#    Asumo que tu archivo principal se llama 'main.py' (cámbialo si es necesario).
CMD ["python", "main.py"]
