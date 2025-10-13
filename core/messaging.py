import threading
import socket
import queue
import time
import os
import random
import logging
import shutil
from typing import Optional, Dict, Tuple, Any
from core.frame import Frame
from core.frame_builder import FrameFactory

# Configuración unificada de logging - ELIMINAR la configuración duplicada al final del archivo
# Y mover esta línea al principio después de los imports
logger = logging.getLogger(__name__)

class HearingThread(threading.Thread):
    def __init__(self, _socket, cola_entrante: queue.Queue):
        super().__init__(daemon=True)
        self._socket = _socket
        self.cola_entrante = cola_entrante
        self._running = True
        self.logger = logging.getLogger("HearingThread")  # Logger específico

    def run(self):
        self.logger.info("Iniciado")
        while self._running:
            try:
                raw_data = self._socket.receive_frame()
                if not raw_data:
                    continue
                    
                try:
                    frame = Frame.from_bytes(raw_data)
                    # Filtrar por MAC destino (nuestra MAC o broadcast)
                    if frame.mac_dst in (self._socket.mac, "FF:FF:FF:FF:FF:FF"):
                        self.cola_entrante.put(frame)
                    else:
                        self.logger.debug(f"Frame ignorado - no es para nosotros: {frame.mac_dst}")
                except ValueError as e:
                    self.logger.warning(f"Frame corrupto: {e}")
                except Exception as e:
                    self.logger.error(f"Error procesando frame: {e}")
                    
            except socket.timeout:
                continue
            except ConnectionError as e:
                self.logger.error(f"Error de conexión: {e}")
                self.stop()
            except Exception as e:
                self.logger.error(f"Error inesperado: {e}")
                self.stop()

    def stop(self):
        self._running = False

class SendingThread(threading.Thread):
    def __init__(self, _socket, cola_saliente: queue.Queue):
        super().__init__(daemon=True)
        self._socket = _socket
        self.cola_saliente = cola_saliente
        self._running = True
        self.logger = logging.getLogger("SendingThread")  # Logger específico

    def run(self):
        self.logger.info("Iniciado")
        while self._running:
            try:
                frame: Optional[Frame] = self.cola_saliente.get(timeout=1.0)
                if frame is None:
                    break
                    
                self._socket.send_frame(frame.to_bytes())
                
            except queue.Empty:
                continue
            except ConnectionError as e:
                self.logger.error(f"Error enviando: {e}")
            except Exception as e:
                self.logger.error(f"Error inesperado: {e}")

    def stop(self):
        self._running = False
        try:
            self.cola_saliente.put(None, timeout=1.0)
        except:
            pass

class AckManagerThread(threading.Thread):
    TIMEOUT = 15.0
    MAX_RETRIES = 3
    CHECK_INTERVAL = 2.0

    def __init__(self, cola_saliente: queue.Queue, cola_notificaciones: queue.Queue):
        super().__init__(daemon=True)
        self.cola_saliente = cola_saliente
        self.cola_notificaciones = cola_notificaciones
        self._esperando_ack: Dict[tuple, Tuple[float, int, Frame, str]] = {}
        self._lock = threading.RLock()
        self._running = True
        self._next_transfer_id = random.randint(1, 1000)
        self.logger = logging.getLogger("AckManager")  # Logger específico

    def get_next_transfer_id(self) -> int:
        with self._lock:
            self._next_transfer_id = (self._next_transfer_id + 1) & 0xFFFF
            return self._next_transfer_id

    def registrar_mensaje(self, frame: Frame, descripcion: str = "") -> bool:
        with self._lock:
            if frame.msg_type == "FILE":
                clave = (frame.transfer_id, frame.fragment_no)
            else:
                clave = (frame.transfer_id, 0)
                
            if clave in self._esperando_ack:
                self.logger.warning(f"ID {clave} ya está pendiente - {descripcion}")
                return False
                
            self._esperando_ack[clave] = (time.time(), 0, frame, descripcion)
            self.cola_saliente.put(frame)
            self.logger.debug(f"Mensaje {clave} registrado - Tipo: {frame.msg_type} - {descripcion}")
            return True

    def handle_ack(self, ack_id: int, fragment_no: int = 0) -> bool:
        with self._lock:
            clave = (ack_id, fragment_no)
            if clave in self._esperando_ack:
                _, _, frame, descripcion = self._esperando_ack[clave]
                del self._esperando_ack[clave]
                self.logger.info(f"ACK confirmado para {clave} - {descripcion}")
                
                if (frame.msg_type == "FILE" and 
                    fragment_no == frame.total_frags):
                    self.cola_notificaciones.put(
                        f"Transferencia {ack_id} completada: {descripcion}"
                    )
                return True
            else:
                self.logger.debug(f"ACK para {clave} no encontrado en pendientes")
                return False

    def handle_file_ack(self, transfer_id: int, fragment_no: int) -> bool:
        return self.handle_ack(transfer_id, fragment_no)

    def run(self):
        self.logger.info("Iniciado")
        while self._running:
            time.sleep(self.CHECK_INTERVAL)
            current_time = time.time()
            
            with self._lock:
                expired_claves = []
                for clave, (timestamp, retries, frame, descripcion) in self._esperando_ack.items():
                    if (current_time - timestamp) > self.TIMEOUT:
                        if retries < self.MAX_RETRIES:
                            self.logger.warning(
                                f"Timeout para {clave} - Reintento {retries + 1}/{self.MAX_RETRIES} - {descripcion}"
                            )
                            self._esperando_ack[clave] = (current_time, retries + 1, frame, descripcion)
                            self.cola_saliente.put(frame)
                        else:
                            self.logger.error(
                                f"Mensaje {clave} falló después de {self.MAX_RETRIES} reintentos - {descripcion}"
                            )
                            expired_claves.append(clave)
                            self.cola_notificaciones.put(
                                f"Error: No se pudo entregar {descripcion} a {frame.mac_dst}"
                            )
                
                for clave in expired_claves:
                    del self._esperando_ack[clave]

    def stop(self):
        self._running = False

class OnlineManager(threading.Thread):
    HELLO_INTERVAL = 30.0
    PEER_TIMEOUT = 90.0
    CLEANUP_INTERVAL = 60.0

    def __init__(self, diccionario_usuarios: dict, usuarios_lock: threading.Lock, 
                 cola_saliente: queue.Queue, builder: FrameFactory):
        super().__init__(daemon=True)
        self.diccionario_usuarios = diccionario_usuarios
        self.usuarios_lock = usuarios_lock
        self.cola_saliente = cola_saliente
        self.builder = builder
        self.running = True
        self.last_cleanup = time.time()
        self.logger = logging.getLogger("OnlineManager")  # Logger específico

    def manage_broadcast(self, frame: Frame) -> bool:
        try:
            data = frame.data.decode("utf-8").split("|")
            if len(data) == 2:
                username, status = data[0], data[1]
                with self.usuarios_lock:
                    if status == "online":
                        self.diccionario_usuarios[frame.mac_src] = {
                            'username': username, 
                            'last_seen': time.time(),
                            'status': 'online'
                        }
                        self.logger.info(f"Usuario {username} ({frame.mac_src}) en línea")
                        return True
                    elif status == "offline":
                        if frame.mac_src in self.diccionario_usuarios:
                            del self.diccionario_usuarios[frame.mac_src]
                            self.logger.info(f"Usuario {username} ({frame.mac_src}) se desconectó")
                            return True
            return False
        except Exception as e:
            self.logger.error(f"Error procesando broadcast: {e}")
            return False

    def cleanup_peers(self) -> int:
        now = time.time()
        removed_count = 0
        with self.usuarios_lock:
            expired_peers = [
                mac for mac, info in self.diccionario_usuarios.items()
                if (now - info['last_seen']) > self.PEER_TIMEOUT
            ]
            for mac in expired_peers:
                username = self.diccionario_usuarios[mac]['username']
                del self.diccionario_usuarios[mac]
                self.logger.info(f"Peer {username} ({mac}) expiró")
                removed_count += 1
        return removed_count

    def get_online_peers(self) -> Dict[str, Any]:
        with self.usuarios_lock:
            return self.diccionario_usuarios.copy()

    def run(self):
        self.logger.info("Iniciado")
        while self.running:
            try:
                online_frame = self.builder.build_broadcast_online()
                self.cola_saliente.put(online_frame)
                
                current_time = time.time()
                if (current_time - self.last_cleanup) > self.CLEANUP_INTERVAL:
                    removed = self.cleanup_peers()
                    if removed > 0:
                        self.logger.info(f"Limpiados {removed} peers expirados")
                    self.last_cleanup = current_time
                    
                time.sleep(self.HELLO_INTERVAL)
                
            except Exception as e:
                self.logger.error(f"Error: {e}")
                time.sleep(self.HELLO_INTERVAL)

    def stop(self):
        self.running = False
        try:
            offline_frame = self.builder.build_broadcast_offline()
            self.cola_saliente.put(offline_frame)
        except Exception as e:
            self.logger.error(f"Error enviando offline: {e}")

class FileAssemblerManagerThread(threading.Thread):
    TIMEOUT = 120.0
    CLEANUP_INTERVAL = 30.0

    def __init__(self, fragment_queue: queue.Queue, download_directory: str = "downloads"):
        super().__init__(daemon=True)
        self.fragment_queue = fragment_queue
        self.download_directory = download_directory
        os.makedirs(download_directory, exist_ok=True)
        self._active_transfers: Dict[int, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._running = True
        self.last_cleanup = time.time()
        self.logger = logging.getLogger("FileAssembler")  # Logger específico

    def _process_fragment(self, frame: Frame) -> bool:
        tid = frame.transfer_id
        
        with self._lock:
            if tid not in self._active_transfers:
                if frame.fragment_no != 1:
                    self.logger.warning(f"Fragmento {frame.fragment_no} recibido sin fragmento inicial para transferencia {tid}")
                    return False
                
                try:
                    if b'|' not in frame.data:
                        self.logger.error(f"Primer fragmento sin separador para transferencia {tid}")
                        return False
                        
                    header, data = frame.data.split(b'|', 1)
                    filename = header.decode('utf-8', errors='replace').strip()
                    if not filename:
                        self.logger.error(f"Nombre de archivo vacío en transferencia {tid}")
                        return False
                    
                    self._active_transfers[tid] = {
                        'filename': filename,
                        'total_frags': frame.total_frags,
                        'fragments': {1: data},
                        'last_seen': time.time(),
                        'mac_src': frame.mac_src
                    }
                    self.logger.info(f"Nueva transferencia {tid}: '{filename}' ({frame.total_frags} fragmentos) de {frame.mac_src}")
                    if self._active_transfers[tid]['total_frags']==1:
                        return self._assemble_file(tid)
                    return True
                    
                except Exception as e:
                    self.logger.error(f"Error procesando primer fragmento {tid}: {e}")
                    return False

            info = self._active_transfers[tid]
            
            if info['total_frags'] != frame.total_frags:
                self.logger.warning(f"Total de fragmentos inconsistente en transferencia {tid}")
                return False
                
            if frame.fragment_no in info['fragments']:
                self.logger.debug(f"Fragmento {frame.fragment_no} duplicado para transferencia {tid}")
                return True
                
            info['fragments'][frame.fragment_no] = frame.data
            info['last_seen'] = time.time()
            
            if len(info['fragments']) == info['total_frags']:
                return self._assemble_file(tid)
                
            return True

    def _assemble_file(self, tid: int) -> bool:
        with self._lock:
            if tid not in self._active_transfers:
                return False
                
            info = self._active_transfers[tid]
            filename = info['filename']
            
            filename = "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_', '.')).strip()
            if not filename:
                filename = f"file_{tid}"
            
            filepath = os.path.join(self.download_directory, filename)
            
            counter = 1
            original_filepath = filepath
            while os.path.exists(filepath):
                name, ext = os.path.splitext(original_filepath)
                filepath = f"{name}_{counter}{ext}"
                counter += 1

            try:
                with open(filepath, 'wb') as f:
                    for i in range(1, info['total_frags'] + 1):
                        if i not in info['fragments']:
                            self.logger.error(f"Faltante fragmento {i} para {tid}")
                            return False
                        f.write(info['fragments'][i])
                
                file_size = os.path.getsize(filepath)
                self.logger.info(f"Archivo ensamblado: {filepath} ({file_size} bytes) de {info['mac_src']}")
                del self._active_transfers[tid]
                return True
                
            except Exception as e:
                self.logger.error(f"Error escribiendo archivo {filepath}: {e}")
                try:
                    if os.path.exists(filepath):
                        os.remove(filepath)
                except:
                    pass
                return False

    def _cleanup_timed_out_transfers(self) -> int:
        now = time.time()
        removed_count = 0
        
        with self._lock:
            timed_out = [
                tid for tid, info in self._active_transfers.items()
                if (now - info['last_seen']) > self.TIMEOUT
            ]
            
            for tid in timed_out:
                filename = self._active_transfers[tid]['filename']
                self.logger.warning(f"Transferencia {tid} ('{filename}') expiró")
                del self._active_transfers[tid]
                removed_count += 1
                
        return removed_count

    def run(self):
        self.logger.info("Iniciado")
        while self._running:
            try:
                frame = self.fragment_queue.get(timeout=1.0)
                if frame is None:
                    break
                    
                self._process_fragment(frame)
                
            except queue.Empty:
                current_time = time.time()
                if (current_time - self.last_cleanup) > self.CLEANUP_INTERVAL:
                    removed = self._cleanup_timed_out_transfers()
                    if removed > 0:
                        self.logger.info(f"Limpiadas {removed} transferencias expiradas")
                    self.last_cleanup = current_time
                    
            except Exception as e:
                self.logger.error(f"Error: {e}")

    def stop(self):
        self._running = False
        try:
            self.fragment_queue.put(None, timeout=1.0)
        except:
            pass

class RouterThread(threading.Thread):
    def __init__(self, cola_entrante: queue.Queue, fragment_queue: queue.Queue, 
                 online_manager: OnlineManager, ack_manager: AckManagerThread, 
                 app_msg_queue: queue.Queue, my_mac: str, factory: FrameFactory):
        super().__init__(daemon=True)
        self.cola_entrante = cola_entrante
        self.fragment_queue = fragment_queue
        self.online_manager = online_manager
        self.ack_manager = ack_manager
        self.app_msg_queue = app_msg_queue
        self.my_mac = my_mac
        self.factory = factory
        self._running = True
        self.logger = logging.getLogger("RouterThread")  # Logger específico - ESTA ES LA LÍNEA QUE FALTABA

    def run(self):
        self.logger.info("Iniciado")
        while self._running:
            try:
                frame: Frame = self.cola_entrante.get(timeout=1.0)
                if frame is None:
                    break

                if frame.msg_type == "FILE":
                    # Si el frame va dirigido a nosotros, respondemos con ACK específico
                    if frame.mac_dst == self.my_mac:
                        self.logger.debug(f"Enviando FILE_ACK para fragmento FILE {frame.transfer_id}-{frame.fragment_no}")
                        # Enviar ACK que incluye el número de fragmento (file_ack|transfer_id|fragment_no)
                        ack_frame = self.factory.build_file_ack(
                            id_mensaje=frame.transfer_id,
                            fragment_no=frame.fragment_no,
                            mac_dst=frame.mac_src
                        )
                        # Poner el ACK en la cola saliente para que el SendingThread lo envíe
                        self.ack_manager.cola_saliente.put(ack_frame)

                    # Entregar fragmento al ensamblador (aunque no sea para nosotros, según tu diseño)
                    self.fragment_queue.put(frame)
                    
                elif frame.msg_type == "BROADCAST":
                    self.online_manager.manage_broadcast(frame)
                    
                elif frame.msg_type == "CTRL":
                    try:
                        text = frame.data.decode('utf-8')
                        parts = text.split("|")
                        if len(parts) >= 2:
                            cmd, param = parts[0], parts[1]
                            if cmd == "ack":
                                ack_id = int(param)
                                self.logger.debug(f"Procesando ACK para {ack_id}")
                                self.ack_manager.handle_ack(ack_id)
                            elif cmd == "file_ack" and len(parts) == 3:
                                transfer_id = int(parts[1])
                                fragment_no = int(parts[2])
                                self.logger.debug(f"Procesando FILE_ACK para {transfer_id}-{fragment_no}")
                                self.ack_manager.handle_file_ack(transfer_id, fragment_no)
                            elif cmd == "nack":
                                nack_id = int(param)
                                self.logger.warning(f"NACK recibido para mensaje {nack_id}")
                    except Exception as e:
                        self.logger.error(f"Error procesando CTRL: {e}")
                        
                else:
                    self.app_msg_queue.put(frame)
                    
            except queue.Empty:
                continue
            except Exception as e:
                self.logger.error(f"Error: {e}")

    def stop(self):
        self._running = False

class FileSender:
    CHUNK_SIZE = 1400

    def __init__(self, builder: FrameFactory, cola_saliente: queue.Queue, ack_manager: Optional[AckManagerThread] = None):
        self.builder = builder
        self.cola_saliente = cola_saliente
        self.ack_manager = ack_manager
        self.logger = logging.getLogger("FileSender")  # Logger específico

    def _gen_transfer_id(self) -> int:
        return random.randint(1, 0xFFFF)

    def start_transfer(self, filepath: str, mac_dst: str, reliable: bool = False) -> int:
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"La ruta '{filepath}' no existe")
            
        mac_dst = mac_dst.upper()
        
        if self.ack_manager:
            transfer_id = self.ack_manager.get_next_transfer_id()
        else:
            transfer_id = self._gen_transfer_id()

        path_to_send = filepath
        temp_archive_path = None  # Variable para guardar la ruta del archivo temporal

        # --- NUEVO: Lógica para manejar directorios ---
        if os.path.isdir(filepath):
            self.logger.info(f"Detectada carpeta: '{filepath}'. Comprimiendo...")
            
            # Crear un nombre para el archivo temporal que sea único
            archive_basename = f"temp_transfer_{transfer_id}"
            
            try:
                # shutil.make_archive crea un archivo comprimido.
                # Parámetros:
                # 1. base_name: El nombre del archivo sin extensión (ej. 'temp_transfer_123')
                # 2. format: El formato de compresión ('zip', 'tar', etc.)
                # 3. root_dir: El directorio que se va a comprimir.
                temp_archive_path = shutil.make_archive(archive_basename, 'zip', filepath)
                
                # Ahora, la ruta que realmente enviaremos es la del archivo ZIP recién creado
                path_to_send = temp_archive_path
                self.logger.info(f"Carpeta comprimida en: '{path_to_send}'")
                
            except Exception as e:
                self.logger.error(f"Error al comprimir la carpeta: {e}")
                raise # Relanzar la excepción para detener la operación
        try:
            
            filesize = os.path.getsize(path_to_send)
            total_frags = (filesize + self.CHUNK_SIZE - 1) // self.CHUNK_SIZE
            
            if total_frags == 0:
                total_frags = 1

            filename = os.path.basename(path_to_send)
            descripcion = f"'{filename}' ({filesize} bytes)"
            
            self.logger.info(f"Iniciando transferencia {transfer_id}: {descripcion} -> {mac_dst}")

            try:
                with open(path_to_send, 'rb') as f:
                    for fragment_no in range(1, total_frags + 1):
                        chunk = f.read(self.CHUNK_SIZE)
                        if not chunk:
                            break

                        if fragment_no == 1:
                            payload = f"{filename}|".encode('utf-8') + chunk
                        else:
                            payload = chunk

                        frame = self.builder.build_file(transfer_id, payload, fragment_no, mac_dst, total_frags)
                        
                        if reliable and self.ack_manager:
                            frag_desc = f"fragmento {fragment_no}/{total_frags} de {descripcion}"
                            if not self.ack_manager.registrar_mensaje(frame, frag_desc):
                                self.logger.error(f"No se pudo registrar {frag_desc}")
                                return transfer_id
                        else:
                            self.cola_saliente.put(frame)
                            
                        if fragment_no % 10 == 0:
                            time.sleep(0.01)

                if reliable:
                    self.logger.info(f"Transferencia confiable {transfer_id} iniciada: {total_frags} fragmentos")
                else:
                    self.logger.info(f"Transferencia no confiable {transfer_id} completada")
                    
                return transfer_id
                
            except Exception as e:
                self.logger.error(f"Error en transferencia {transfer_id}: {e}")
                raise
        finally:    
            if temp_archive_path:
                try:
                    self.logger.info(f"Limpiando archivo temporal: {temp_archive_path}")
                    os.remove(temp_archive_path)
                except Exception as e:
                    self.logger.error(f"No se pudo eliminar el archivo temporal '{temp_archive_path}': {e}")
# ELIMINAR la configuración de logging duplicada al final del archivo
# Esto ya se configura en main.py