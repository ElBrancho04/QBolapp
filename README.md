# QBolapp — Aplicación de Mensajería en Capa 2 (Proyecto de Redes de Computadoras)

**Autores:** Abraham Rey Sánchez Amador y Ronald Alfonso Pérez\
**Materia:** Redes de las Computadoras\
**Tipo de Proyecto:** Aplicación escolar con fines académicos

---

## Descripción general

**QBolapp** es una aplicación de mensajería en red local que opera directamente sobre la **capa de enlace de datos (capa 2 del modelo OSI)**, utilizando tramas Ethernet personalizadas y un *EtherType* propio (`0x88B5`).

El objetivo principal del proyecto es comprender el funcionamiento de las redes a bajo nivel: cómo se construyen las tramas, cómo se identifican los equipos mediante direcciones MAC y cómo se pueden enviar datos sin depender de protocolos de capa superior (como IP o TCP).

El resultado es un sistema de mensajería P2P con envío de texto, detección de usuarios conectados y transferencia de archivos o carpetas en una red LAN.

---

## Principales funcionalidades

- Comunicación directa entre equipos en la misma red local (sin IP, solo MAC).
- Envío y recepción de mensajes entre usuarios.
- Transferencia de **archivos y carpetas (convertidas automáticamente en .zip)**.
- Sistema de **confirmaciones (ACKs)** para mensajes confiables.
- Detección automática de usuarios conectados (“online” / “offline”).
- Interfaz gráfica desarrollada con **Tkinter**, intuitiva y funcional.
- Interfaz de consola (CLI) con comandos interactivos.

---

## Estructura del proyecto

El código está dividido en varios módulos dentro de la carpeta `core/`, más interfaces de usuario en modo texto y gráfico.

```
├── core/
│   ├── frame.py             # Definición de la estructura de las tramas Ethernet personalizadas
│   ├── frame_builder.py     # Creador de tramas (mensajes, ACKs, archivos, broadcast, etc.)
│   ├── socket.py            # Capa de enlace: socket RAW y obtención de MAC
│   ├── messaging.py         # Lógica de envío, recepción, ACKs, control de peers y transferencias
├── gui_main.py              # Interfaz gráfica principal (Tkinter)
├── gui_launcher.py          # Lanzador con selección de interfaz y modo debug
├── main.py                  # Interfaz de línea de comandos (CLI) y punto de entrada
└── README.md                # Este archivo
```

---

## Componentes y lógica general

### 1. **frame.py**

Define la estructura de una trama personalizada con:

- Dirección MAC origen y destino.
- EtherType (`0x88B5`).
- Tipo de mensaje (`MSG`, `FILE`, `CTRL`, `HELLO`, `BROADCAST`).
- Campos para fragmentación de archivos.
- CRC de verificación.
- Pequeña capa de seguridad con encriptado del payload mediante XOR con clave secreta.

### 2. **frame\_builder.py**

Proporciona métodos para construir fácilmente distintos tipos de tramas:

- Mensajes (`build_msg`)
- Acks (`build_ack`, `build_nack`, `build_file_ack`)
- Broadcast de presencia (`build_broadcast_online`, `build_broadcast_offline`)
- Fragmentos de archivos (`build_file`)

### 3. **socket.py**

Implementa una clase `MySocket` que maneja sockets RAW sobre una interfaz específica (por ejemplo `wlan0`, `eth0` o `veth0`). Permite enviar y recibir tramas directamente, además de obtener la dirección MAC del dispositivo.

### 4. **messaging.py**

Contiene los hilos principales de la aplicación:

- **HearingThread:** escucha tramas entrantes.
- **SendingThread:** envía tramas de la cola de salida.
- **AckManagerThread:** gestiona los ACKs y retransmisiones.
- **OnlineManager:** mantiene la lista de usuarios conectados.
- **FileAssemblerManagerThread:** reconstruye archivos fragmentados.
- **RouterThread:** distribuye las tramas entrantes.
- **FileSender:** gestiona el envío de archivos o carpetas (zip).

### 5. **main.py (CLI)**

Es la versión de consola de LinkChat. Permite usar el sistema desde terminal con comandos simples.

**Características principales:**

- Control completo de la aplicación mediante comandos (`msg`, `file`, `bc`, `hello`, etc.).
- Permite enviar mensajes confiables o no confiables.
- Muestra en consola los peers conectados y notificaciones del sistema.
- Soporta envío de archivos y carpetas.
- Manejo de señales (`SIGINT`, `SIGTERM`) para cierre limpio.

**Ejemplo de uso:**

```bash
sudo python3 main.py -i wlan0 -u Abraham
```

**Comandos disponibles:**

```
peers                     - Lista los peers conectados
msg <MAC> <texto>         - Envía mensaje confiable
send <MAC> <texto>        - Envía mensaje no confiable
bc <texto>                - Envía broadcast de mensaje
file <ruta> <MAC> [reliable] - Envía archivo o carpeta
hello                     - Envía saludo
help                      - Muestra la ayuda
exit                      - Sale de la aplicación
```

### 6. **gui\_main.py**

Interfaz gráfica desarrollada en **Tkinter**, permite:

- Chatear con otros usuarios de la red local.
- Enviar mensajes confiables o no confiables.
- Ver peers conectados.
- Enviar archivos o carpetas.
- Visualizar logs y notificaciones.

### 7. **gui\_launcher.py**

Proporciona un lanzador gráfico simple para iniciar el chat sin usar la terminal.

- Detecta interfaces de red disponibles con `netifaces`.
- Permite escribir cualquier interfaz manualmente (ej: `veth0`, `eth0`, `wlan0`).
- Incluye campo de usuario, modo debug y botón para iniciar el chat.
- Ejecuta `gui_main.py` con los parámetros seleccionados.

Ejemplo de ejecución:

```bash
sudo python3 gui_launcher.py
```

---

## Ejecución del programa

> ⚠️ **Nota:** Este programa utiliza *raw sockets*, por lo que normalmente requiere permisos de **administrador (root)**.

### Opción 1 — Modo gráfico:

```bash
sudo python3 gui_launcher.py
```

Selecciona la interfaz, nombre de usuario y presiona “Iniciar Chat”.

### Opción 2 — Modo consola:

```bash
sudo python3 main.py -i <interfaz> -u <nombre_usuario>
```

Ejemplo:

```bash
sudo python3 main.py -i wlan0 -u Ronald
```

---

## Conceptos de redes aplicados

- **EtherType personalizado:** `0x88B5` permite identificar las tramas propias de la aplicación.
- **Tramas Ethernet personalizadas:** construidas manualmente usando `struct.pack`.
- **Capa de enlace (OSI):** comunicación directa mediante direcciones MAC.
- **ACKs y retransmisión:** sistema de fiabilidad propio.
- **Fragmentación:** envío de archivos grandes divididos en tramas.
- **Multithreading:** uso de múltiples hilos para gestionar tráfico, archivos y control de usuarios.

---

## Conclusión

Este proyecto permitió aplicar conceptos prácticos de redes de computadoras desde la capa física hasta la de enlace, profundizando en el manejo de tramas, control de errores y diseño de protocolos personalizados.

Además, integra elementos modernos como concurrencia, GUI con Tkinter y compresión de archivos, resultando en una aplicación didáctica, funcional y completa.

