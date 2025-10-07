import threading
import socket
import queue
from core.frame import Frame
from core.socket import MySocket
from  core.frame_builder import  FrameFactory
import time
#hay que obligar a los usuarios a mandar su nombre de usuario en los broatcast

# --- HILOS CON RESPONSABILIDADES CORREGIDAS ---

class HearingThread(threading.Thread):
    """
    RESPONSABILIDAD ÚNICA: Escuchar en el socket, parsear tramas y ponerlas
    en una cola para que el resto de la aplicación las procese. ¡No toma decisiones!
    """
    def __init__(self, _socket: MySocket, cola_entrante: queue.Queue):
        super().__init__()
        self._socket = _socket
        self.cola_entrante = cola_entrante
        self._running = True
        self._socket.my_socket.settimeout(1.0)

    def run(self):
        while self._running:
            try:
                bites = self._socket.receive_frame()
                try:
                    frame = Frame.from_bytes(bites)
                    if frame.mac_dst in (self._socket.mac,"FF:FF:FF:FF:FF:FF"):
                        self.cola_entrante.put(frame)
                except Exception as e:
                    print(f"[Listener] Error parseando el frame: {e}")
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[Listener] Error crítico en el socket: {e}")
                self.stop()

    def stop(self):
        self._running = False

class SendingThread(threading.Thread):
    """
    RESPONSABILIDAD ÚNICA: Sacar tramas de la cola de salida y ponerlas en el socket.
    Es un "trabajador tonto" y eficiente.
    """
    def __init__(self, _socket: MySocket, cola_saliente: queue.Queue):
        super().__init__()
        self._socket = _socket
        self.cola_saliente = cola_saliente
        self._running = True
        self.asignador_id=0

    def run(self):
        while self._running:
            try:
                frame:Frame = self.cola_saliente.get(timeout=1.0)
                if frame is None: # Centinela para parar
                    break
                if frame.INV_TYPE_MAP!="FILE":
                    frame.transfer_id=self.asignador_id
                    self.asignador_id+=1
                self._socket.send_frame(Frame.to_bytes(frame))

            except queue.Empty:
                continue
            except Exception as e:
                print(f"[Sender] Ha ocurrido un error enviando la trama: {e}")

    def stop(self):
        self._running = False
        self.cola_saliente.put(None) # Poner centinela para desbloquear el get()

class AckManagerThread(threading.Thread):
    """
    RESPONSABILIDAD ÚNICA: Gestionar los mensajes que esperan ACK,
    manejar los timeouts y las retransmisiones.
    """
    TIMEOUT = 2.0
    MAX_RETRIES = 5
    CHECK_INTERVAL = 1.0

    def __init__(self, cola_saliente: queue.Queue, cola_notificaciones: queue.Queue):
        super().__init__()
        self.cola_saliente = cola_saliente
        self.cola_notificaciones = cola_notificaciones # Cola para notificar a la UI si un mensaje falla
        self._esperando_ack = {} # {msg_id: (timestamp, reintentos, frame)}
        self._lock = threading.Lock()
        self._running = True

    def registrar_mensaje(self, frame: Frame):
        """El hilo principal llama a este método ANTES de enviar un mensaje confiable."""
        with self._lock:
            self._esperando_ack[frame.transfer_id] = (time.time(), 0, frame)
        self.cola_saliente.put(frame)

    def handle_ack(self, ack_id: int):
        """El hilo principal llama a este método cuando recibe un ACK."""
        with self._lock:
            if ack_id in self._esperando_ack:
                del self._esperando_ack[ack_id]
                print(f"[AckManager] ACK para {ack_id} confirmado.")

    def run(self):
        while self._running:
            time.sleep(self.CHECK_INTERVAL)
            
            # Copiar claves para poder modificar el diccionario mientras se itera
            with self._lock:
                ids_a_revisar = list(self._esperando_ack.keys())
            
            current_time = time.time()
            for msg_id in ids_a_revisar:
                with self._lock:
                    if msg_id in self._esperando_ack:
                        timestamp, retries, frame = self._esperando_ack[msg_id]
                        
                        if (current_time - timestamp) > self.TIMEOUT:
                            if retries < self.MAX_RETRIES:
                                # Reintentar
                                print(f"[AckManager] Timeout para {msg_id}. Reenviando...")
                                self._esperando_ack[msg_id] = (current_time, retries + 1, frame)
                                self.cola_saliente.put(frame)
                            else:
                                # Darse por vencido
                                print(f"[AckManager] MENSAJE {msg_id} FALLÓ después de {self.MAX_RETRIES} reintentos.")
                                self.cola_notificaciones.put(f"Error: No se pudo entregar el mensaje a {frame.mac_dst}")
                                del self._esperando_ack[msg_id]

    def stop(self):
        self._running = False


class OnlineManager(threading.Thread):
    HELLO_INTERVAL = 30.0  # Enviar un HELLO cada 30 segundos
    PEER_TIMEOUT = 95.0 
    def __init__(self,diccionario_usuarios:dict,usuarios_lock:threading.Lock,mensages_a_enviar_:queue.Queue,builder:FrameFactory):
        super().__init__()
        self.diccionario_usuarios=diccionario_usuarios
        self.usuarios_lock=usuarios_lock
        self.mensajes_a_enviar=mensages_a_enviar_
        self.builder=builder
        self.running=True

    def ManageBroadcast(self,frame:Frame):
        data=frame.data.decode("utf-8").split("|")
        if len(data==2):
            if data[0]=="online":
                with self.usuarios_lock:
                        _time=time.time()
                        self.diccionario_usuarios[frame.mac_src]=(data[1],_time)
                    
            elif  data[0]=="offline":
                with self.usuarios_lock:
                    if frame.mac_src  in self.diccionario_usuarios:
                        del self.diccionario_usuarios[frame.mac_src]
        else:
            print("[Warning] Broadcast inválido recibido.")
    def ManagePeers(self):
        _time=time.time()
        usuarios_a_borrar=[]
        with self.usuarios_lock:
            for key,value in self.diccionario_usuarios.items():
                if (_time-value[1])>self.PEER_TIMEOUT:
                    usuarios_a_borrar.append(key)
            for  key in usuarios_a_borrar:
                del self.diccionario_usuarios[key]
    def run(self):
        while self.running:
            new_broadcast=self.builder.build_broadcast_online()
            self.mensajes_a_enviar.put(new_broadcast)
            self.ManagePeers()
            time.sleep(self.HELLO_INTERVAL)
                    
    