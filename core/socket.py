import socket
import threading
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class MySocket:
    ETHERTYPE = 0x88B5

    def __init__(self, interface: str = "wlan0", create: bool = True, timeout: float = 1.0):
        self.INTERFACE = interface
        self.my_socket: Optional[socket.socket] = None
        self.mac: Optional[str] = None
        self.timeout = timeout
        self._sock_lock = threading.RLock()  # RLock para permitir llamadas anidadas
        if create:
            self.create_socket()

    def create_socket(self) -> None:
        with self._sock_lock:
            if self.my_socket is not None:
                return
            try:
                s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(self.ETHERTYPE))
                s.bind((self.INTERFACE, 0))
                s.settimeout(self.timeout)
                self.my_socket = s
                logger.info("Socket creado en interfaz %s", self.INTERFACE)
            except PermissionError as e:
                raise PermissionError("Se requieren privilegios (root) para crear un socket RAW en la interfaz.") from e
            except Exception as e:
                raise RuntimeError(f"No se pudo crear socket en {self.INTERFACE}: {e}") from e

    def close(self) -> None:
        with self._sock_lock:
            s = self.my_socket
            if s is None:
                return
            try:
                s.close()
            except Exception as e:
                logger.warning("Error cerrando socket: %s", e)
            finally:
                self.my_socket = None

    def __enter__(self):
        if self.my_socket is None:
            self.create_socket()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

    def _get_socket_ref(self) -> socket.socket:
        with self._sock_lock:
            if self.my_socket is None:
                raise ConnectionError("Socket no está creado")
            return self.my_socket

    def check_socket_open(self) -> None:
        s = self._get_socket_ref()
        if s.fileno() == -1:
            raise ConnectionError("El socket no está abierto")

    def get_mac_address(self) -> str:
        if self.mac:
            return self.mac
            
        s = self._get_socket_ref()
        try:
            # Obtener la dirección MAC de la interfaz
            import fcntl
            import struct
            SIOCGIFHWADDR = 0x8927
            ifname = self.INTERFACE.encode('utf-8')
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            info = fcntl.ioctl(s.fileno(), SIOCGIFHWADDR, ifname + b'\x00' * 32)
            hwaddr = info[18:24]
            self.mac = ":".join(f"{b:02X}" for b in hwaddr)
            return self.mac
        except (ImportError, OSError, IOError):
            # Fallback: usar getsockname (puede no funcionar en todas las interfaces)
            try:
                sockname = s.getsockname()
                hwaddr = sockname[4]
                self.mac = ":".join(f"{b:02X}" for b in hwaddr[:6])
                return self.mac
            except Exception as e:
                logger.warning("No se pudo obtener MAC, usando placeholder: %s", e)
                self.mac = "00:00:00:00:00:00"
                return self.mac

    def send_frame(self, frame: bytes) -> None:
        s = self._get_socket_ref()
        try:
            sent = s.send(frame)
            if sent != len(frame):
                raise ConnectionError(f"Solo se enviaron {sent} de {len(frame)} bytes")
        except OSError as e:
            raise ConnectionError(f"Error enviando trama: {e}") from e

    def receive_frame(self) -> bytes:
        s = self._get_socket_ref()
        try:
            return s.recv(65535)
        except socket.timeout:
            raise
        except OSError as e:
            raise ConnectionError(f"Error en receive_frame: {e}") from e