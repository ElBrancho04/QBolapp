import struct
import zlib
from typing import Dict, Any

# ==============================
# Constantes
# ==============================
ETHERTYPE = 0x88B5
HEADER_FMT = "!6s6sHBHHHH"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
CRC_SIZE = 4

class Frame:
    """
    Representa una trama de nuestro protocolo.
    """
    TYPE_MAP = {
        "MSG": 1,
        "FILE": 2,
        "CTRL": 3,
        "HELLO": 4,
        "BROADCAST": 5
    }
    INV_TYPE_MAP = {v: k for k, v in TYPE_MAP.items()}

    def __init__(
        self,
        mac_dst: str,
        mac_src: str,
        msg_type: str,
        transfer_id: int,
        fragment_no: int,
        total_frags: int,
        data: bytes,
    ):
        if msg_type not in Frame.TYPE_MAP:
            raise ValueError(f"msg_type desconocido: {msg_type}")
        if not (0 <= transfer_id <= 0xFFFF):
            raise ValueError("transfer_id debe caber en uint16")
        if not (0 <= fragment_no <= 0xFFFF) or not (1 <= total_frags <= 0xFFFF):
            raise ValueError("fragment_no o total_frags fuera de rango")
        if fragment_no > total_frags:
            raise ValueError("fragment_no no puede ser mayor que total_frags")
        
        self.mac_dst = mac_dst.upper()
        self.mac_src = mac_src.upper()
        self.msg_type = msg_type
        self.transfer_id = transfer_id
        self.fragment_no = fragment_no
        self.total_frags = total_frags
        self.data = data or b""

    def to_bytes(self) -> bytes:
        mac_dst_b = encode_mac(self.mac_dst)
        mac_src_b = encode_mac(self.mac_src)
        type_b = Frame.TYPE_MAP[self.msg_type]
        payload_len = len(self.data)
        
        if payload_len > 0xFFFF:
            raise ValueError("Payload demasiado grande")
            
        header = struct.pack(
            HEADER_FMT,
            mac_dst_b,
            mac_src_b,
            ETHERTYPE,
            type_b,
            self.transfer_id,
            self.fragment_no,
            self.total_frags,
            payload_len
        )
        content = header + self.data
        crc = zlib.crc32(content) & 0xFFFFFFFF
        crc_bytes = struct.pack("!I", crc)
        return content + crc_bytes

    @staticmethod
    def from_bytes(raw: bytes) -> "Frame":
        if len(raw) < HEADER_SIZE + CRC_SIZE:
            raise ValueError("Trama demasiado corta")
            
        header = raw[:HEADER_SIZE]
        try:
            mac_dst_b, mac_src_b, ethertype, type_b, transfer_id, fragment_no, total_frags, payload_len = struct.unpack(HEADER_FMT, header)
        except struct.error as e:
            raise ValueError(f"Error deserializando header: {e}")
            
        if ethertype != ETHERTYPE:
            raise ValueError(f"Ethertype inesperado: {ethertype:#04X}")
            
        expected_len = HEADER_SIZE + payload_len + CRC_SIZE
        if len(raw) < expected_len:
            raise ValueError(f"Trama incompleta: esperado {expected_len}, recibido {len(raw)}")
            
        payload = raw[HEADER_SIZE:HEADER_SIZE + payload_len]
        crc_recv = struct.unpack("!I", raw[HEADER_SIZE + payload_len:expected_len])[0]
        
        calculated_crc = zlib.crc32(raw[:HEADER_SIZE + payload_len]) & 0xFFFFFFFF
        if calculated_crc != crc_recv:
            raise ValueError(f"CRC inválido: esperado {crc_recv:#010x}, calculado {calculated_crc:#010x}")
            
        try:
            msg_type = Frame.INV_TYPE_MAP[type_b]
        except KeyError:
            raise ValueError(f"Tipo de mensaje desconocido: {type_b}")
            
        mac_dst = decode_mac(mac_dst_b)
        mac_src = decode_mac(mac_src_b)
        
        return Frame(mac_dst, mac_src, msg_type, transfer_id, fragment_no, total_frags, payload)

    def __repr__(self):
        return (f"<Frame {self.msg_type} {self.mac_src} -> {self.mac_dst} | "
                f"transfer {self.transfer_id} frag {self.fragment_no}/{self.total_frags} | "
                f"len={len(self.data)}>")

    def to_dict(self) -> Dict[str, Any]:
        """Convierte el frame a diccionario para debug"""
        return {
            'mac_dst': self.mac_dst,
            'mac_src': self.mac_src,
            'msg_type': self.msg_type,
            'transfer_id': self.transfer_id,
            'fragment_no': self.fragment_no,
            'total_frags': self.total_frags,
            'data_length': len(self.data)
        }


def encode_mac(mac_str: str) -> bytes:
    """Convierte string MAC a bytes"""
    mac_str = mac_str.upper().replace('-', ':')
    parts = mac_str.split(":")
    if len(parts) != 6:
        raise ValueError(f"MAC inválida: {mac_str}")
    
    result = bytes()
    for part in parts:
        if len(part) != 2:
            raise ValueError(f"MAC inválida: {mac_str}")
        try:
            result += bytes([int(part, 16)])
        except ValueError:
            raise ValueError(f"MAC inválida: {mac_str}")
    
    return result


def decode_mac(mac_bytes: bytes) -> str:
    """Convierte bytes MAC a string"""
    return ":".join(f"{b:02X}" for b in mac_bytes[:6])