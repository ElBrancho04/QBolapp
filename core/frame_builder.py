from core.frame import Frame


class FrameFactory:
    def __init__(self,mac_src:str,nombre_de_usuario:str):
        self.mi_mac=mac_src
        self.broadcast="FF:FF:FF:FF:FF:FF"
        self.nombre_de_usuario=nombre_de_usuario
        
    
    def build_broadcast_online(self,id_mensaje)->Frame:
        msg=self.nombre_de_usuario+"|"+"online"
        frame=Frame(self.broadcast,self.mi_mac,"BROADCAST",id_mensaje,1,1,msg.encode("utf-8"))
        return frame
    def build_broadcast_offline(self,id_mensaje)->Frame:
        msg="0"
        frame=Frame(self.broadcast,self.mi_mac,"BROADCAST",id_mensaje,1,1,msg.encode("utf-8"))
        return frame
    def build_hello(self,id_mensaje,mac_dst)->Frame:
        mensaje="hello"  
        frame=Frame(mac_dst,self.mi_mac,"HELLO",id_mensaje,1,1,mensaje.encode("utf-8"))
        return frame
    def build_ack(self,id_mensaje,id_mensaje_a_confirmar:str,mac_dst)->Frame:
        msg="ack"+"|"+id_mensaje_a_confirmar
        frame=Frame(mac_dst,self.mi_mac,"CTRL",id_mensaje,1,1,msg.encode("utf-8"))
        return frame
    def build_nack(self,id_mensaje,id_mensaje_a_confirmar:str,mac_dst)->Frame:
            msg="nack"+"|"+id_mensaje_a_confirmar
            frame=Frame(mac_dst,self.mi_mac,"CTRL",id_mensaje,1,1,msg.encode("utf-8"))
            return frame
    def build_msg(self,id_mensaje,mensaje:str,mac_dst:str)->Frame: 
            frame=Frame(mac_dst,self.mi_mac,"MSG",id_mensaje,1,1,mensaje.encode("utf-8"))
            return frame
                