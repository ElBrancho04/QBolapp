#!/usr/bin/env python3
"""
main.py - Entry point para Proyecto de Redes (mensajería)
"""
import argparse
import sys
import os
import threading
import time
import queue
import random
import signal
import logging
from typing import Dict, Any, Optional

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Asegurar que el directorio del proyecto esté en sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from core.socket import MySocket
    from core.frame import Frame
    from core.frame_builder import FrameFactory
    from core.messaging import (
        HearingThread, SendingThread, AckManagerThread, 
        OnlineManager, FileAssemblerManagerThread, RouterThread, FileSender
    )
except ImportError as e:
    logger.error(f"Error importando módulos: {e}")
    sys.exit(1)

class App:
    def __init__(self, interface: str, username: str):
        self.interface = interface
        self.username = username
        self.running = False
        
        # Colas
        self.cola_entrante = queue.Queue()
        self.cola_saliente = queue.Queue()
        self.cola_notificaciones = queue.Queue()
        self.fragment_queue = queue.Queue()
        self.app_msg_queue = queue.Queue()
        
        # Estado de la aplicación
        self.peers: Dict[str, Dict[str, Any]] = {}
        self.peers_lock = threading.Lock()
        
        # Inicializar socket
        self.sock = MySocket(interface=self.interface, create=True, timeout=1.0)
        
        # Obtener MAC propia
        try:
            self.my_mac = self.sock.get_mac_address()
            logger.info(f"MAC propia: {self.my_mac}")
        except Exception as e:
            logger.error(f"No se pudo obtener MAC: {e}")
            self.my_mac = "00:00:00:00:00:00"
        
        # Factory
        self.factory = FrameFactory(self.my_mac, self.username)
        
        # Managers y Threads
        self.online_manager = OnlineManager(
            self.peers, self.peers_lock, self.cola_saliente, self.factory
        )
        
        self.ack_manager = AckManagerThread(self.cola_saliente, self.cola_notificaciones)
        self.file_assembler = FileAssemblerManagerThread(self.fragment_queue, "downloads")
        self.file_sender = FileSender(self.factory, self.cola_saliente, self.ack_manager)
        
        # Threads de red
        self.hearing_thread = HearingThread(self.sock, self.cola_entrante)
        self.sending_thread = SendingThread(self.sock, self.cola_saliente)
        self.router_thread = RouterThread(
            self.cola_entrante,
            self.fragment_queue,
            self.online_manager,
            self.ack_manager,
            self.app_msg_queue,
            self.my_mac,
            self.factory  
        )
        
        # Threads de aplicación
        self.notif_consumer_thread = None
        self.msg_consumer_thread = None

    def start(self):
        """Inicia todos los hilos y servicios"""
        if self.running:
            return
            
        logger.info("Iniciando aplicación...")
        self.running = True
        
        # Iniciar hilos del sistema
        self.hearing_thread.start()
        self.sending_thread.start()
        self.ack_manager.start()
        self.online_manager.start()
        self.file_assembler.start()
        self.router_thread.start()
        
        # Iniciar consumidores de aplicación
        self.notif_consumer_thread = threading.Thread(
            target=self._consume_notifications, daemon=True
        )
        self.notif_consumer_thread.start()
        
        self.msg_consumer_thread = threading.Thread(
            target=self._consume_messages, daemon=True
        )
        self.msg_consumer_thread.start()
        
        logger.info(f"Aplicación iniciada. Usuario: {self.username}, MAC: {self.my_mac}")

    def _consume_notifications(self):
        """Consume notificaciones del sistema"""
        while self.running:
            try:
                msg = self.cola_notificaciones.get(timeout=1.0)
                print(f"\n[NOTIFICACIÓN] {msg}")
                print("> ", end="", flush=True)
            except queue.Empty:
                continue

    def _consume_messages(self):
        """Consume mensajes de aplicación"""
        while self.running:
            try:
                frame: Frame = self.app_msg_queue.get(timeout=1.0)
                self._handle_app_message(frame)
            except queue.Empty:
                continue

    def _handle_app_message(self, frame: Frame):
        """Procesa mensajes de aplicación"""
        try:
            if frame.msg_type == "MSG":
                text = frame.data.decode("utf-8", errors="replace")
                peer_name = self._get_peer_name(frame.mac_src)
                print(f"\n[MENSAJE] {peer_name} ({frame.mac_src}): {text}")
                
                # Enviar ACK para mensajes confiables
                if frame.mac_dst == self.my_mac:
                    ack_frame = self.factory.build_ack(
                        id_mensaje_a_confirmar=frame.transfer_id,
                        mac_dst=frame.mac_src
                    )
                    self.cola_saliente.put(ack_frame)
                    
            elif frame.msg_type == "HELLO":
                text = frame.data.decode("utf-8", errors="replace")
                peer_name = self._get_peer_name(frame.mac_src)
                print(f"\n[SALUDO] {peer_name} ({frame.mac_src}): {text}")
                
            else:
                logger.warning(f"Mensaje no manejado: {frame}")
                
            print("> ", end="", flush=True)
            
        except Exception as e:
            logger.error(f"Error manejando mensaje: {e}")

    def _get_peer_name(self, mac: str) -> str:
        """Obtiene el nombre del peer por su MAC"""
        with self.peers_lock:
            return self.peers.get(mac, {}).get('username', 'Desconocido')

    def send_reliable_msg(self, mac_dst: str, text: str):
        """Envía mensaje confiable con ACK"""
        if not text.strip():
            print("Error: Mensaje vacío")
            return
            
        frame = self.factory.build_msg(mensaje=text, mac_dst=mac_dst)
        if self.ack_manager.registrar_mensaje(frame):
            print(f"Mensaje confiable enviado a {mac_dst} (ID: {frame.transfer_id})")
        else:
            print("Error: No se pudo enviar el mensaje")

    def send_unreliable_msg(self, mac_dst: str, text: str):
        """Envía mensaje no confiable"""
        if not text.strip():
            print("Error: Mensaje vacío")
            return
            
        frame = self.factory.build_msg(mensaje=text, mac_dst=mac_dst)
        self.cola_saliente.put(frame)
        print(f"Mensaje no confiable enviado a {mac_dst}")

    def broadcast_msg(self, text: str):
        """Envía mensaje broadcast"""
        if not text.strip():
            print("Error: Mensaje vacío")
            return
            
        frame = self.factory.build_msg(mensaje=text, mac_dst="FF:FF:FF:FF:FF:FF")
        self.cola_saliente.put(frame)
        print(f"Broadcast enviado: {text}")

    def send_file(self, filepath: str, mac_dst: str, reliable: bool = False):
        """Envía archivo o carpeta a un destino"""
        if not os.path.exists(filepath):
            print(f"Error: La ruta no existe: {filepath}")
            return
            
        try:
            transfer_id = self.file_sender.start_transfer(filepath, mac_dst, reliable)
            if reliable:
                print(f"✓ Transferencia confiable {transfer_id} iniciada")
                print("  El sistema notificará cuando se complete o falle")
            else:
                print(f"✓ Transferencia no confiable {transfer_id} completada")
                
            return transfer_id
            
        except Exception as e:
            print(f"✗ Error enviando: {e}")
            return None

    def list_peers(self):
        """Lista peers conectados"""
        with self.peers_lock:
            if not self.peers:
                print("No hay peers conectados")
                return
                
            print("\nPeers conectados:")
            print("-" * 50)
            for mac, info in self.peers.items():
                last_seen = time.strftime("%H:%M:%S", time.localtime(info['last_seen']))
                status = info.get('status', 'desconocido')
                print(f" {info['username']:15} {mac:17} {status:8} visto {last_seen}")
            print()

    def stop(self):
        """Detiene la aplicación limpiamente"""
        if not self.running:
            return
            
        logger.info("Deteniendo aplicación...")
        self.running = False
        
        # Enviar mensaje de offline
        try:
            offline_frame = self.factory.build_broadcast_offline()
            self.cola_saliente.put(offline_frame)
            time.sleep(0.5)  # Dar tiempo para enviar
        except Exception as e:
            logger.error(f"Error enviando offline: {e}")
        
        # Detener threads en orden
        threads = [
            self.hearing_thread,
            self.sending_thread, 
            self.ack_manager,
            self.online_manager,
            self.file_assembler,
            self.router_thread
        ]
        
        for thread in threads:
            try:
                if hasattr(thread, 'stop'):
                    thread.stop()
            except Exception as e:
                logger.error(f"Error deteniendo thread: {e}")
        
        # Esperar a que terminen
        for thread in threads:
            try:
                if hasattr(thread, 'join'):
                    thread.join(timeout=2.0)
            except Exception as e:
                logger.error(f"Error en join: {e}")
        
        # Cerrar socket
        try:
            self.sock.close()
        except Exception as e:
            logger.error(f"Error cerrando socket: {e}")
            
        logger.info("Aplicación detenida")

def repl_loop(app: App):
    """Loop principal de la interfaz de usuario"""
    print("\n" + "="*50)
    print("    SISTEMA DE MENSAJERÍA P2P")
    print("="*50)
    print_help()
    
    try:
        while app.running:
            try:
                command = input("> ").strip()
                if not command:
                    continue
                    
                parts = command.split()
                cmd = parts[0].lower()
                
                if cmd in ("exit", "quit"):
                    break
                elif cmd == "help":
                    print_help()
                elif cmd == "peers":
                    app.list_peers()
                elif cmd == "msg" and len(parts) >= 3:
                    mac_dst = parts[1].upper()
                    text = " ".join(parts[2:])
                    app.send_reliable_msg(mac_dst, text)
                elif cmd == "send" and len(parts) >= 3:
                    mac_dst = parts[1].upper()
                    text = " ".join(parts[2:])
                    app.send_unreliable_msg(mac_dst, text)
                elif cmd == "bc" and len(parts) >= 2:
                    text = " ".join(parts[1:])
                    app.broadcast_msg(text)
                elif cmd == "file" and len(parts) >= 3:
                    filepath = parts[1]
                    mac_dst = parts[2].upper()
                    reliable = len(parts) > 3 and parts[3].lower() == "reliable"
                    
                    # Verificar que la ruta existe (archivo o carpeta)
                    if not os.path.exists(filepath):
                        print(f"Error: La ruta '{filepath}' no existe")
                    else:
                        # Llamar al método corregido
                        app.send_file(filepath, mac_dst, reliable)
                elif cmd == "hello":
                    frame = app.factory.build_hello()
                    app.cola_saliente.put(frame)
                    print("Saludo enviado")
                else:
                    print("Comando desconocido. Escribe 'help' para ayuda.")
                    
            except KeyboardInterrupt:
                print("\nUsa 'exit' para salir")
            except Exception as e:
                print(f"Error ejecutando comando: {e}")
                
    except (KeyboardInterrupt, EOFError):
        print("\nSaliendo...")

def print_help():
    """Muestra la ayuda de comandos"""
    print("\nComandos disponibles:")
    print("  peers                    - Lista peers conectados")
    print("  msg <MAC> <texto>        - Envía mensaje confiable")
    print("  send <MAC> <texto>       - Envía mensaje no confiable") 
    print("  bc <texto>               - Broadcast de mensaje")
    print("  file <ruta> <MAC> [reliable] - Envía archivo")
    print("  hello                    - Envía saludo")
    print("  help                     - Muestra esta ayuda")
    print("  exit                     - Sale de la aplicación")
    print()

def signal_handler(app: App, signum, frame):
    """Maneja señales de sistema para apagado limpio"""
    print(f"\nRecibida señal {signum}, cerrando...")
    app.stop()
    sys.exit(0)

def main():
    parser = argparse.ArgumentParser(description="Sistema de mensajería P2P")
    parser.add_argument("--interface", "-i", default="wlan0", 
                       help="Interfaz de red (por defecto: wlan0)")
    parser.add_argument("--user", "-u", required=True,
                       help="Nombre de usuario")
    parser.add_argument("--debug", action="store_true",
                       help="Habilita modo debug")
    
    args = parser.parse_args()
    
    # Configurar nivel de logging
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    app = None
    try:
        app = App(args.interface, args.user)
        
        # Configurar manejador de señales
        signal.signal(signal.SIGINT, lambda s, f: signal_handler(app, s, f))
        signal.signal(signal.SIGTERM, lambda s, f: signal_handler(app, s, f))
        
        app.start()
        repl_loop(app)
        
    except Exception as e:
        logger.error(f"Error fatal: {e}")
        sys.exit(1)
    finally:
        if app:
            app.stop()

if __name__ == "__main__":
    main()