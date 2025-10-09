import random
from typing import Optional
from core.frame import Frame

class FrameFactory:
    def __init__(self, mac_src: str, nombre_de_usuario: str):
        self.mi_mac = mac_src.upper()
        self.broadcast = "FF:FF:FF:FF:FF:FF"
        self.nombre_de_usuario = nombre_de_usuario

    def _gen_id(self) -> int:
        return random.randint(0, 0xFFFF)

    def build_broadcast_online(self, id_mensaje: Optional[int] = None) -> Frame:
        if id_mensaje is None:
            id_mensaje = self._gen_id()
        msg = f"{self.nombre_de_usuario}|online"
        return Frame(self.broadcast, self.mi_mac, "BROADCAST", id_mensaje, 1, 1, msg.encode("utf-8"))

    def build_broadcast_offline(self, id_mensaje: Optional[int] = None) -> Frame:
        if id_mensaje is None:
            id_mensaje = self._gen_id()
        msg = f"{self.nombre_de_usuario}|offline"
        return Frame(self.broadcast, self.mi_mac, "BROADCAST", id_mensaje, 1, 1, msg.encode("utf-8"))

    def build_hello(self, id_mensaje: Optional[int] = None, mac_dst: Optional[str] = None) -> Frame:
        if id_mensaje is None:
            id_mensaje = self._gen_id()
        if mac_dst is None:
            mac_dst = self.broadcast
        mensaje = "hello"
        return Frame(mac_dst, self.mi_mac, "HELLO", id_mensaje, 1, 1, mensaje.encode("utf-8"))

    def build_ack(self, id_mensaje: Optional[int] = None, id_mensaje_a_confirmar: Optional[int] = None, mac_dst: Optional[str] = None) -> Frame:
        if id_mensaje is None:
            id_mensaje = self._gen_id()
        if mac_dst is None:
            raise ValueError("mac_dst es requerido para ACK")
        if id_mensaje_a_confirmar is None:
            raise ValueError("id_mensaje_a_confirmar es requerido")
            
        msg = f"ack|{id_mensaje_a_confirmar}"
        return Frame(mac_dst, self.mi_mac, "CTRL", id_mensaje, 1, 1, msg.encode("utf-8"))

    def build_nack(self, id_mensaje: Optional[int] = None, id_mensaje_a_confirmar: Optional[int] = None, mac_dst: Optional[str] = None) -> Frame:
        if id_mensaje is None:
            id_mensaje = self._gen_id()
        if mac_dst is None:
            mac_dst = self.broadcast
        if id_mensaje_a_confirmar is None:
            raise ValueError("id_mensaje_a_confirmar es requerido")
        msg = f"nack|{id_mensaje_a_confirmar}"
        return Frame(mac_dst, self.mi_mac, "CTRL", id_mensaje, 1, 1, msg.encode("utf-8"))

    def build_msg(self, id_mensaje: Optional[int] = None, mensaje: str = "", mac_dst: Optional[str] = None) -> Frame:
        if id_mensaje is None:
            id_mensaje = self._gen_id()
        if mac_dst is None:
            mac_dst = self.broadcast
        return Frame(mac_dst, self.mi_mac, "MSG", id_mensaje, 1, 1, mensaje.encode("utf-8"))

    def build_file(self, id_mensaje: int, chunk: bytes, fragment_no: int, mac_dst: str, total_fragments: int) -> Frame:
        if not (1 <= fragment_no <= total_fragments):
            raise ValueError(f"fragment_no {fragment_no} fuera de rango [1, {total_fragments}]")
        if len(chunk) == 0:
            raise ValueError("Chunk de datos no puede estar vacío")
            
        return Frame(
            mac_dst=mac_dst,
            mac_src=self.mi_mac,
            msg_type="FILE",
            transfer_id=id_mensaje,
            fragment_no=fragment_no,
            total_frags=total_fragments,
            data=chunk
        )
    
    def build_file_ack(self, id_mensaje: int, fragment_no: int, mac_dst: str) -> Frame:
        """ACK específico para fragmentos de archivo"""
        if mac_dst is None:
            raise ValueError("mac_dst es requerido para FILE_ACK")
        
        msg = f"file_ack|{id_mensaje}|{fragment_no}"
        return Frame(mac_dst, self.mi_mac, "CTRL", self._gen_id(), 1, 1, msg.encode("utf-8"))