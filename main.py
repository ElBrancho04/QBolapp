#!/usr/bin/env python3
"""
main.py - Entry point para Proyecto de Redes (mensajería)
Funcionalidades:
- Crea socket en interfaz dada
- Lanza hilos: escucha, envío, ack manager
- Mantiene tabla de peers por broadcasts "online"
- Permite enviar mensajes confiables (esperan ACK) y broadcasts
- Apagado limpio (broadcast offline, detener hilos, cerrar socket)
"""

import argparse
import sys
import os
import threading
import time
import queue
import itertools
import signal

# Asegurar que el directorio del proyecto esté en sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Importar módulos del proyecto
from core.socket import MySocket
from core.frame import Frame
from core.frame_builder import FrameFactory
from core.messaging import HearingThread, SendingThread, AckManagerThread

# ---------- Utilidades ----------
transfer_id_counter = itertools.count(1)

def next_transfer_id() -> int:
    return next(transfer_id_counter) & 0xFFFF

# ---------- Aplicación principal ----------
class App:
    def __init__(self, interface: str, username: str):
        self.interface = interface
        self.username = username
        self.cola_entrante = queue.Queue()
        self.cola_saliente = queue.Queue()
        self.cola_notificaciones = queue.Queue()
        self.peers = {}  # mac -> {"user": nombre, "last_seen": ts}

        # Crear socket (se bindea en la interfaz)
        self.sock = MySocket(interface=self.interface, create=True, timeout=1.0)

        # Obtener MAC propia para builders
        try:
            self.my_mac = self.sock.get_mac_address()
        except Exception:
            # si falla, usar una MAC placeholder (no ideal)
            self.my_mac = "00:00:00:00:00:00"

        self.factory = FrameFactory(self.my_mac, self.username)

        # Hilos
        self.hearing = HearingThread(self.sock, self.cola_entrante)
        self.sending = SendingThread(self.sock, self.cola_saliente)
        self.ack_manager = AckManagerThread(self.cola_saliente, self.cola_notificaciones)

        # Control de vida
        self._running = False
        self._consumer_thread = None

    def start(self):
        self._running = True
        # arrancar hilos
        self.hearing.start()
        self.sending.start()
        self.ack_manager.start()

        # anunciar online
        tid = next_transfer_id()
        online_frame = self.factory.build_broadcast_online(tid)
        # broadcast de presencia lo tratamos como no confiable (no registramos en ack_manager)
        self.cola_saliente.put(online_frame)

        # consumer que procesa cola_entrante y notificaciones
        self._consumer_thread = threading.Thread(target=self._consume_incoming_loop, daemon=True)
        self._consumer_thread.start()

        # thread para procesar notificaciones (errores del ack manager)
        self._notif_thread = threading.Thread(target=self._consume_notifications_loop, daemon=True)
        self._notif_thread.start()

        print(f"[Main] Inicio completado. Mi MAC: {self.my_mac}. Usuario: {self.username}")
        print("Escribe 'help' para ver comandos.")

    def _consume_notifications_loop(self):
        while self._running:
            try:
                msg = self.cola_notificaciones.get(timeout=1.0)
                print(f"[NOTIF] {msg}")
            except queue.Empty:
                continue

    def _consume_incoming_loop(self):
        while self._running:
            try:
                frame: Frame = self.cola_entrante.get(timeout=1.0)
            except queue.Empty:
                continue

            # Procesar frame según tipo
            try:
                if frame.msg_type == "BROADCAST":
                    # payload: "username|online" o "0" (offline)
                    payload = frame.data.decode("utf-8", errors="ignore")
                    if payload == "0":
                        # offline message: remover peer si existe
                        mac = frame.mac_src
                        if mac in self.peers:
                            print(f"[Peer] {self.peers[mac]['user']} ({mac}) se ha desconectado.")
                            del self.peers[mac]
                    else:
                        # "username|online"
                        parts = payload.split("|", 1)
                        if len(parts) >= 1:
                            username = parts[0]
                            mac = frame.mac_src
                            self.peers[mac] = {"user": username, "last_seen": time.time()}
                            # responder hello (opcional) - no lo hacemos por defecto
                            print(f"[Peer] {username} ({mac}) ONLINE (broadcast).")
                elif frame.msg_type == "MSG":
                    text = frame.data.decode("utf-8", errors="ignore")
                    print(f"[MSG] {frame.mac_src} -> {frame.mac_dst} : {text} (id={frame.transfer_id})")
                    # enviar ACK automático si destinatario soy yo y es un mensaje confiable?
                    # Suponemos que todo MSG puede necesitar ack: mandamos CTRL ack
                    if frame.mac_dst.upper() == self.my_mac.upper() or frame.mac_dst == "FF:FF:FF:FF:FF:FF":
                        # construir ack hacia el emisor
                        ack_tid = next_transfer_id()
                        ack_frame = self.factory.build_ack(ack_tid, str(frame.transfer_id), frame.mac_src)
                        # ack no registrado en ack_manager (no esperamos ack de ack)
                        self.cola_saliente.put(ack_frame)
                elif frame.msg_type == "CTRL":
                    payload = frame.data.decode("utf-8", errors="ignore")
                    if payload.startswith("ack|"):
                        # formato ack|<id_confirmado>
                        _, acked = payload.split("|", 1)
                        try:
                            acked_id = int(acked)
                            self.ack_manager.handle_ack(acked_id)
                        except Exception:
                            print(f"[CTRL] ACK malformado: {payload}")
                    elif payload.startswith("nack|"):
                        _, nackid = payload.split("|", 1)
                        print(f"[CTRL] NACK recibido para {nackid} desde {frame.mac_src}")
                elif frame.msg_type == "HELLO":
                    # podrías responder o registrar
                    print(f"[HELLO] {frame.mac_src}: {frame.data.decode('utf-8',errors='ignore')}")
                else:
                    print(f"[UNKNOWN] {frame}")
            except Exception as e:
                print(f"[Main] Error procesando incoming frame: {e}")

    def send_reliable_msg(self, mac_dst: str, text: str):
        tid = next_transfer_id()
        # crear frame
        frame = self.factory.build_msg(tid, text, mac_dst)
        # registrar en ack manager (éste pondrá el frame en cola_saliente)
        self.ack_manager.registrar_mensaje(frame)
        print(f"[Envio] Mensaje confiable id={tid} enviado a {mac_dst}")

    def send_unreliable_msg(self, mac_dst: str, text: str):
        tid = next_transfer_id()
        frame = self.factory.build_msg(tid, text, mac_dst)
        self.cola_saliente.put(frame)
        print(f"[Envio] Mensaje no fiable id={tid} en cola a {mac_dst}")

    def broadcast(self, text: str):
        tid = next_transfer_id()
        frame = self.factory.build_msg(tid, text, "FF:FF:FF:FF:FF:FF")
        self.cola_saliente.put(frame)
        print(f"[Broadcast] '{text}' enviado (id={tid})")

    def list_peers(self):
        if not self.peers:
            print("No peers conocidos.")
            return
        print("Peers conocidos:")
        for mac, info in self.peers.items():
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(info["last_seen"]))
            print(f" - {info['user']} @ {mac} (last seen: {ts})")

    def stop(self):
        print("[Main] Apagando... enviando broadcast offline y cerrando hilos.")
        self._running = False
        # broadcast offline
        tid = next_transfer_id()
        off = self.factory.build_broadcast_offline(tid)
        self.cola_saliente.put(off)

        # Dar tiempo a que salga
        time.sleep(0.5)

        # Parar hilos
        try:
            self.hearing.stop()
        except Exception:
            pass
        try:
            self.ack_manager.stop()
        except Exception:
            pass
        try:
            self.sending.stop()
        except Exception:
            pass

        # join hilos con timeout para no bloquear eternamente
        for t in (self.hearing, self.ack_manager, self.sending, self._consumer_thread):
            try:
                if t and hasattr(t, "join"):
                    t.join(timeout=1.0)
            except Exception:
                pass

        # cerrar socket
        try:
            self.sock.close()
        except Exception:
            pass
        print("[Main] Parada completa.")

# --------- CLI y loop principal ---------
def repl_loop(app: App):
    try:
        while True:
            line = input("> ").strip()
            if not line:
                continue
            parts = line.split(" ", 2)
            cmd = parts[0].lower()

            if cmd in ("exit", "quit"):
                break
            elif cmd == "help":
                print("Comandos:")
                print("  msg <MAC> <texto>     - enviar mensaje confiable a MAC")
                print("  send <MAC> <texto>    - enviar mensaje no fiable a MAC")
                print("  bc <texto>            - broadcast texto")
                print("  peers                 - listar peers")
                print("  help                  - mostrar esta ayuda")
                print("  exit                  - salir")
            elif cmd == "msg" and len(parts) >= 3:
                mac = parts[1].upper()
                text = parts[2]
                app.send_reliable_msg(mac, text)
            elif cmd == "send" and len(parts) >= 3:
                mac = parts[1].upper()
                text = parts[2]
                app.send_unreliable_msg(mac, text)
            elif cmd == "bc" and len(parts) >= 2:
                text = line.split(" ", 1)[1]
                app.broadcast(text)
            elif cmd == "peers":
                app.list_peers()
            else:
                print("Comando desconocido. Escribe 'help'.")
    except (KeyboardInterrupt, EOFError):
        print("\n[Main] Entrada interrumpida, saliendo...")

# --------- Señales para apagado limpio ----------
def install_signal_handlers(app: App):
    def handler(signum, frame):
        print(f"\n[Signal] Se recibió señal {signum}, apagando...")
        app.stop()
        sys.exit(0)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

# --------- Entrypoint ----------
def main():
    parser = argparse.ArgumentParser(description="Main Proyecto Redes - mensajería")
    parser.add_argument("--interface", "-i", default="wlan0", help="Interfaz de red (ej: wlan0)")
    parser.add_argument("--user", "-u", required=True, help="Nombre de usuario para broadcast")
    args = parser.parse_args()

    app = App(args.interface, args.user)
    install_signal_handlers(app)
    app.start()

    repl_loop(app)

    # salida normal
    app.stop()


if __name__ == "__main__":
    main()
