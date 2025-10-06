import socket
import threading
import logging

logger = logging.getLogger(__name__)

class MySocket:
    ETHERTYPE = 0x88B5  # nuestro protocolo

    def __init__(self, interface: str = "eth0", create: bool = True, timeout: float = 1.0):
        self.INTERFACE = interface
        self.my_socket = None
        self.mac = None
        self.timeout = timeout
        self._sock_lock = threading.Lock()  # lock para acceder a self.my_socket de forma segura

        if create:
            self.create_socket()

    def create_socket(self):
        """Crea y bindea el socket si no existe aún."""
        with self._sock_lock:
            if self.my_socket is not None:
                return
            s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(self.ETHERTYPE))
            s.bind((self.INTERFACE, 0))
            s.settimeout(self.timeout)
            self.my_socket = s
            logger.info("Socket creado en interfaz %s", self.INTERFACE)

    def close(self):
        """Cierra el socket si está abierto (idempotente)."""
        with self._sock_lock:
            s = self.my_socket
            if s is None:
                return
            try:
                s.close()
                logger.info("Socket cerrado en interfaz %s", self.INTERFACE)
            except Exception as e:
                logger.debug("Error cerrando socket: %s", e)
            finally:
                self.my_socket = None

    # Context manager
    def __enter__(self):
        if self.my_socket is None:
            self.create_socket()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        # No suprimir excepciones: devolver False (o no devolver nada)
        self.close()
        return False

    def __del__(self):
        # Best-effort cleanup
        try:
            self.close()
        except Exception:
            pass

    # helpers
    def _get_socket_ref(self):
        """Devuelve la referencia actual del socket (puede ser None)."""
        with self._sock_lock:
            return self.my_socket

    def check_socket_open(self):
        s = self._get_socket_ref()
        if not s or s.fileno() == -1:
            raise ConnectionError("El socket no está abierto. Use 'with MySocket() as s:' o llame a create_socket().")

    def get_mac_address(self) -> str:
        s = self._get_socket_ref()
        if s is None:
            raise ConnectionError("Socket cerrado. Create o usar context manager.")
        if self.mac:
            return self.mac
        sockname = s.getsockname()
        hwaddr = sockname[4]
        self.mac = ":".join(f"{b:02X}" for b in hwaddr[:6])
        return self.mac

    def send_frame(self, frame: bytes):
        s = self._get_socket_ref()
        if s is None:
            raise ConnectionError("Socket no disponible para enviar.")
        try:
            s.send(frame)
        except OSError as e:
            logger.debug("send_frame error: %s", e)
            raise ConnectionError("Error enviando trama") from e

    def receive_frame(self) -> bytes:
        s = self._get_socket_ref()
        if s is None:
            raise ConnectionError("Socket no disponible para recibir.")
        try:
            return s.recv(65535)
        except socket.timeout:
            # subir excepción para que el hilo la vuelva a interpretar si quiere
            raise
        except OSError as e:
            # Si otro hilo cerró el socket, recv suele levantar OSError
            raise ConnectionError("Error en receive_frame (socket cerrado?)") from e
