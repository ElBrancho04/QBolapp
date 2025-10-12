# Dockerfile

# 1. Usar una imagen base de Python completa que incluya las herramientas de construcción.
FROM python:3.9

# 2. Instalar las dependencias del sistema operativo para Tkinter.
#    -y actualiza sin pedir confirmación.
RUN apt-get update && apt-get install -y tk

# 3. Establecer el directorio de trabajo.
WORKDIR /app

# 4. Copiar todos los archivos del proyecto al contenedor.
COPY . .

# 5. Definir el comando por defecto (será sobreescrito, pero es una buena práctica).
#    Asumo que tu archivo principal se llama 'gui_main.py'.
CMD ["python", "gui_main.py"]
