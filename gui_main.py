#!/usr/bin/env python3
"""
gui_main.py - GUI para Proyecto de Redes (mensajería)
"""
import argparse
import sys
import os
import threading
import time
import queue
import subprocess
import signal
import logging
from typing import Dict, Any
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox

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

class ChatGUI:
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

        # Inicializar monitoreo de descargas
        self.download_dir = "downloads"
        os.makedirs(self.download_dir, exist_ok=True)
        self._known_downloads = set(os.listdir(self.download_dir))
        
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
        
        # GUI
        self.root = None
        self.setup_gui()
        
        # Threads de aplicación
        self.gui_update_thread = None

    def setup_gui(self):
        """Configura la interfaz gráfica"""
        self.root = tk.Tk()
        self.root.title(f"QBolapp - {self.username} ({self.my_mac}) - Interfaz: {self.interface}")
        self.root.geometry("900x700")
        self.root.protocol("WM_DELETE_WINDOW", self.stop)

        # Crear notebook (pestañas)
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Pestaña de Chat
        chat_frame = ttk.Frame(notebook)
        notebook.add(chat_frame, text="Chat")

        # Pestaña de Peers
        peers_frame = ttk.Frame(notebook)
        notebook.add(peers_frame, text="Peers")

        # Pestaña de Archivos
        files_frame = ttk.Frame(notebook)
        notebook.add(files_frame, text="Archivos")

        # Pestaña de Configuración
        config_frame = ttk.Frame(notebook)
        notebook.add(config_frame, text="Configuración")

        # Configurar pestañas
        self.setup_chat_tab(chat_frame)
        self.setup_peers_tab(peers_frame)
        self.setup_files_tab(files_frame)
        self.setup_config_tab(config_frame)

        # Barra de estado
        self.status_var = tk.StringVar()
        self.status_var.set(f"Conectado - Interfaz: {self.interface} - MAC: {self.my_mac}")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def setup_config_tab(self, parent):
        """Configura la pestaña de configuración"""
        main_frame = ttk.Frame(parent)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Información actual
        info_frame = ttk.LabelFrame(main_frame, text="Información Actual")
        info_frame.pack(fill=tk.X, pady=5)

        ttk.Label(info_frame, text=f"Usuario: {self.username}").pack(anchor=tk.W, pady=2)
        ttk.Label(info_frame, text=f"Interfaz: {self.interface}").pack(anchor=tk.W, pady=2)
        ttk.Label(info_frame, text=f"MAC: {self.my_mac}").pack(anchor=tk.W, pady=2)

        # Nota sobre cambio de interfaz
        note_frame = ttk.LabelFrame(main_frame, text="Nota Importante")
        note_frame.pack(fill=tk.X, pady=10)

        note_text = tk.Text(note_frame, height=4, wrap=tk.WORD)
        note_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        note_text.insert(tk.END, 
            "Para cambiar la interfaz de red, es necesario reiniciar la aplicación.\n\n"
            "Puede usar interfaces como: wlan0, eth0, veth0, veth1, etc.\n"
            "Cierre esta aplicación y ejecute el lanzador nuevamente para seleccionar una interfaz diferente.")
        note_text.config(state=tk.DISABLED)

        # Botones de utilidad
        util_frame = ttk.LabelFrame(main_frame, text="Utilidades")
        util_frame.pack(fill=tk.X, pady=5)

        ttk.Button(util_frame, text="Abrir Directorio de Descargas", 
                  command=self.open_downloads_dir).pack(pady=5)
        ttk.Button(util_frame, text="Reiniciar Lanzador", 
                  command=self.restart_launcher).pack(pady=5)

    def open_downloads_dir(self):
        """Abre el directorio de descargas"""
        downloads_path = os.path.abspath("downloads")
        if not os.path.exists(downloads_path):
            os.makedirs(downloads_path)
        
        try:
            if sys.platform == "win32":
                os.startfile(downloads_path)
            elif sys.platform == "darwin":  # macOS
                subprocess.run(["open", downloads_path])
            else:  # Linux
                subprocess.run(["xdg-open", downloads_path])
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo abrir el directorio: {e}")

    def restart_launcher(self):
        """Reinicia el lanzador"""
        try:
            self.stop()
            if self.root:
                self.root.destroy()

            subprocess.Popen([sys.executable, "gui_launcher.py"])
            os._exit(0)

        except Exception as e:
            messagebox.showerror("Error", f"No se pudo reiniciar el lanzador: {e}")

    def setup_chat_tab(self, parent):
        """Configura la pestaña de chat"""
        # Frame principal
        main_frame = ttk.Frame(parent)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Área de mensajes
        msg_frame = ttk.LabelFrame(main_frame, text="Mensajes")
        msg_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.chat_text = scrolledtext.ScrolledText(msg_frame, height=20, state=tk.DISABLED)
        self.chat_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Frame de entrada
        input_frame = ttk.Frame(main_frame)
        input_frame.pack(fill=tk.X, padx=5, pady=5)

        # Selección de destino
        dest_frame = ttk.Frame(input_frame)
        dest_frame.pack(fill=tk.X, pady=2)

        ttk.Label(dest_frame, text="Destino:").pack(side=tk.LEFT)
        self.dest_var = tk.StringVar(value="FF:FF:FF:FF:FF:FF")
        dest_entry = ttk.Entry(dest_frame, textvariable=self.dest_var, width=20)
        dest_entry.pack(side=tk.LEFT, padx=5)

        # Botones de destino rápido
        ttk.Button(dest_frame, text="Broadcast", 
                command=lambda: self.dest_var.set("FF:FF:FF:FF:FF:FF")).pack(side=tk.LEFT, padx=2)
        
        # Campo de mensaje
        msg_input_frame = ttk.Frame(input_frame)
        msg_input_frame.pack(fill=tk.X, pady=2)

        ttk.Label(msg_input_frame, text="Mensaje:").pack(side=tk.LEFT)
        self.msg_var = tk.StringVar()
        self.msg_entry = ttk.Entry(msg_input_frame, textvariable=self.msg_var, width=50)
        self.msg_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.msg_entry.bind('<Return>', self._on_enter_press)

        # Botones de envío - CON PROTECCIÓN CONTRA MÚLTIPLES CLICS
        btn_frame = ttk.Frame(input_frame)
        btn_frame.pack(fill=tk.X, pady=2)

        self.btn_reliable = ttk.Button(btn_frame, text="Enviar Confiable", 
                command=self._send_reliable)
        self.btn_reliable.pack(side=tk.LEFT, padx=2)
        
        self.btn_unreliable = ttk.Button(btn_frame, text="Enviar No Confiable", 
                command=self._send_unreliable)
        self.btn_unreliable.pack(side=tk.LEFT, padx=2)
        
        ttk.Button(btn_frame, text="Limpiar Chat", 
                command=self.clear_chat).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Enviar Saludo", 
                command=self.send_hello).pack(side=tk.LEFT, padx=2)

        # Estado de envío
        self._sending_in_progress = False

    def setup_peers_tab(self, parent):
        """Configura la pestaña de peers"""
        # Frame principal
        main_frame = ttk.Frame(parent)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Lista de peers
        peers_frame = ttk.LabelFrame(main_frame, text="Peers Conectados")
        peers_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Treeview para peers
        columns = ('Usuario', 'MAC', 'Estado', 'Última vez')
        self.peers_tree = ttk.Treeview(peers_frame, columns=columns, show='headings')
        
        # Configurar columnas
        for col in columns:
            self.peers_tree.heading(col, text=col)
            self.peers_tree.column(col, width=150)

        # Scrollbar
        scrollbar = ttk.Scrollbar(peers_frame, orient=tk.VERTICAL, command=self.peers_tree.yview)
        self.peers_tree.configure(yscrollcommand=scrollbar.set)
        
        self.peers_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Botones
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Button(btn_frame, text="Actualizar", 
                  command=self.update_peers_display).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Seleccionar para Chat", 
                  command=self.select_peer_for_chat).pack(side=tk.LEFT, padx=2)

    def setup_files_tab(self, parent):
        """Configura la pestaña de archivos"""
        # Frame principal
        main_frame = ttk.Frame(parent)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Envío de archivos
        send_frame = ttk.LabelFrame(main_frame, text="Enviar Archivo o Carpeta (las carpetas se envian como comprimido .zip)")
        send_frame.pack(fill=tk.X, padx=5, pady=5)

        # Selección de archivo
        file_frame = ttk.Frame(send_frame)
        file_frame.pack(fill=tk.X, padx=5, pady=2)

        self.file_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self.file_var, state='readonly').pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        ttk.Button(file_frame, text="Seleccionar", 
                  command=self.select_file).pack(side=tk.RIGHT, padx=2)

        # Destino y opciones
        opt_frame = ttk.Frame(send_frame)
        opt_frame.pack(fill=tk.X, padx=5, pady=2)

        ttk.Label(opt_frame, text="Destino:").pack(side=tk.LEFT)
        self.file_dest_var = tk.StringVar()
        ttk.Entry(opt_frame, textvariable=self.file_dest_var, width=20).pack(side=tk.LEFT, padx=5)

        self.reliable_var = tk.BooleanVar()
        ttk.Checkbutton(opt_frame, text="Envío Confiable", 
                       variable=self.reliable_var).pack(side=tk.LEFT, padx=5)

        ttk.Button(opt_frame, text="Enviar Archivo", 
                  command=self.send_file).pack(side=tk.RIGHT, padx=2)

        # Área de descargas
        download_frame = ttk.LabelFrame(main_frame, text="Descargas")
        download_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.download_text = scrolledtext.ScrolledText(download_frame, height=10, state=tk.DISABLED)
        self.download_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def _on_enter_press(self, event):
        """Maneja la tecla Enter en el campo de mensaje"""
        self._send_reliable()

    def _send_reliable(self):
        """Envía mensaje confiable con protección contra múltiples envíos"""
        if not self._sending_in_progress:
            self._sending_in_progress = True
            self.btn_reliable.config(state='disabled')
            self.btn_unreliable.config(state='disabled')
            self.msg_entry.config(state='disabled')
            
            try:
                self.send_message(reliable=True)
            finally:
                # Rehabilitar después de un breve delay
                self.root.after(500, self._reenable_send_buttons)

    def _send_unreliable(self):
        """Envía mensaje no confiable con protección contra múltiples envíos"""
        if not self._sending_in_progress:
            self._sending_in_progress = True
            self.btn_reliable.config(state='disabled')
            self.btn_unreliable.config(state='disabled')
            self.msg_entry.config(state='disabled')
            
            try:
                self.send_message(reliable=False)
            finally:
                # Rehabilitar después de un breve delay
                self.root.after(500, self._reenable_send_buttons)

    def _reenable_send_buttons(self):
        """Rehabilita los botones de envío"""
        self._sending_in_progress = False
        self.btn_reliable.config(state='normal')
        self.btn_unreliable.config(state='normal')
        self.msg_entry.config(state='normal')
        self.msg_entry.focus()

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
        
        # Iniciar actualizaciones de GUI
        self.gui_update_thread = threading.Thread(target=self._update_gui, daemon=True)
        self.gui_update_thread.start()
        
        # Iniciar GUI
        self.root.mainloop()

    def _update_gui(self):
        """Actualiza la GUI periódicamente"""
        while self.running:
            try:
                # Actualizar lista de peers
                self.update_peers_display()
                
                # Procesar notificaciones
                self.process_notifications()
                
                # Procesar mensajes de aplicación
                self.process_app_messages()

                self._refresh_downloads()
                
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Error actualizando GUI: {e}")

    def process_notifications(self):
        """Procesa notificaciones del sistema"""
        try:
            while True:
                msg = self.cola_notificaciones.get_nowait()
                self.add_to_chat("SISTEMA", msg, system=True)
        except queue.Empty:
            pass

    def process_app_messages(self):
        """Procesa mensajes de aplicación"""
        try:
            while True:
                frame: Frame = self.app_msg_queue.get_nowait()
                self._handle_app_message(frame)
        except queue.Empty:
            pass

    def _handle_app_message(self, frame: Frame):
        """Procesa mensajes de aplicación"""
        try:
            if frame.msg_type == "MSG":
                 # Verificar que no sea nuestro propio mensaje
                if frame.mac_src == self.my_mac:
                    return
                     
                text = frame.data.decode("utf-8", errors="replace")
                peer_name = self._get_peer_name(frame.mac_src)
                self.add_to_chat(peer_name, text)
                
                try:
                    if frame.mac_dst == self.my_mac:
                        ack_frame = self.factory.build_ack(
                            id_mensaje_a_confirmar=frame.transfer_id,
                            mac_dst=frame.mac_src
                        )
                        self.cola_saliente.put(ack_frame)
                        logger.debug(f"ACK enviado para mensaje {frame.transfer_id} -> {frame.mac_src}")
                except Exception as e:
                    logger.error(f"Error construyendo/enviando ACK: {e}")
                
            elif frame.msg_type == "HELLO":
                if frame.mac_src == self.my_mac:
                    return  # Ignorar nuestros propios saludos
                    
                text = frame.data.decode("utf-8", errors="replace")
                peer_name = self._get_peer_name(frame.mac_src)
                self.add_to_chat("SALUDO", f"{peer_name}: {text}", system=True)
                
            else:
                logger.warning(f"Mensaje no manejado: {frame}")
                
        except Exception as e:
            logger.error(f"Error manejando mensaje: {e}")

    def _get_peer_name(self, mac: str) -> str:
        """Obtiene el nombre del peer por su MAC"""
        with self.peers_lock:
            return self.peers.get(mac, {}).get('username', 'Desconocido')

    def add_to_chat(self, sender: str, message: str, system: bool = False):
        """Añade mensaje al chat"""
        self.chat_text.config(state=tk.NORMAL)
        
        if system:
            self.chat_text.insert(tk.END, f"=== {message} ===\n", "system")
        else:
            timestamp = time.strftime("%H:%M:%S")
            self.chat_text.insert(tk.END, f"[{timestamp}] {sender}: {message}\n")
        
        self.chat_text.config(state=tk.DISABLED)
        self.chat_text.see(tk.END)

    def clear_chat(self):
        """Limpia el área de chat"""
        self.chat_text.config(state=tk.NORMAL)
        self.chat_text.delete(1.0, tk.END)
        self.chat_text.config(state=tk.DISABLED)

    def send_message(self, reliable: bool = True):
        """Envía mensaje"""
        mac_dst = self.dest_var.get().strip()
        text = self.msg_var.get().strip()
        
        if not text:
            messagebox.showwarning("Advertencia", "El mensaje no puede estar vacío")
            return
            
        if not mac_dst:
            messagebox.showwarning("Advertencia", "Debe especificar un destino")
            return

        # Para broadcast, solo permitir mensajes no confiables
        if mac_dst.upper() == "FF:FF:FF:FF:FF:FF" and reliable:
            messagebox.showwarning("Advertencia", 
                                "Los mensajes broadcast deben ser no confiables. Cambiando a no confiable.")
            reliable = False

        try:
            logger.info(f"Enviando mensaje a {mac_dst}: '{text}' (confiable: {reliable})")
            
            if reliable:
                frame = self.factory.build_msg(mensaje=text, mac_dst=mac_dst)
                if self.ack_manager.registrar_mensaje(frame, f"mensaje a {mac_dst}"):
                    self.add_to_chat("TÚ", f"{text} [CONFIABLE - ID: {frame.transfer_id}]")
                    logger.debug(f"Mensaje confiable registrado con ID: {frame.transfer_id}")
                else:
                    messagebox.showerror("Error", "No se pudo enviar el mensaje confiable")
            else:
                frame = self.factory.build_msg(mensaje=text, mac_dst=mac_dst)
                self.cola_saliente.put(frame)
                self.add_to_chat("TÚ", f"{text} [NO CONFIABLE]")
                logger.debug("Mensaje no confiable enviado")
            
            # Limpiar campo de mensaje
            self.msg_var.set("")
            
        except Exception as e:
            logger.error(f"Error enviando mensaje: {e}")
            messagebox.showerror("Error", f"Error enviando mensaje: {e}")

    def send_hello(self):
        """Envía saludo"""
        try:
            frame = self.factory.build_hello()
            self.cola_saliente.put(frame)
            self.add_to_chat("SISTEMA", "Saludo enviado", system=True)
        except Exception as e:
            messagebox.showerror("Error", f"Error enviando saludo: {e}")

    def update_peers_display(self):
        """Actualiza la lista de peers en la GUI"""
        # Guardar la selección actual antes de actualizar
        selected_items = self.peers_tree.selection()
        selected_mac = None
        if selected_items:
            item = selected_items[0]
            values = self.peers_tree.item(item, 'values')
            if values and len(values) > 1:
                selected_mac = values[1]  # MAC está en la posición 1

        with self.peers_lock:
            # Limpiar treeview
            for item in self.peers_tree.get_children():
                self.peers_tree.delete(item)
            
            # Añadir peers
            for mac, info in self.peers.items():
                last_seen = time.strftime("%H:%M:%S", time.localtime(info['last_seen']))
                status = info.get('status', 'desconocido')
                username = info.get('username', 'Desconocido')
                
                item_id = self.peers_tree.insert('', tk.END, values=(
                    username, mac, status, last_seen
                ))
                
                # Restaurar selección si coincide con la MAC guardada
                if selected_mac and mac == selected_mac:
                    self.peers_tree.selection_set(item_id)

    def select_peer_for_chat(self):
        """Selecciona un peer para chat"""
        selection = self.peers_tree.selection()
        if not selection:
            messagebox.showwarning("Advertencia", "Seleccione un peer de la lista")
            return
            
        item = self.peers_tree.item(selection[0])
        mac = item['values'][1]
        self.dest_var.set(mac)
        self.status_var.set(f"Destino seleccionado: {mac}")

    def select_file(self):
        """Selecciona archivo o carpeta para enviar"""
        try:
            # Preguntar al usuario si quiere seleccionar una carpeta
            elegir_carpeta = messagebox.askyesno(
                "Seleccionar carpeta o archivo",
                "¿Desea seleccionar una CARPETA para enviar? (Si no, se seleccionará un archivo)"
            )

            if elegir_carpeta:
                # Seleccionar carpeta
                folder = filedialog.askdirectory(title="Seleccionar carpeta para enviar")
                if folder:
                    self.file_var.set(folder)
            else:
                # Seleccionar archivo
                filename = filedialog.askopenfilename(
                    title="Seleccionar archivo para enviar",
                    filetypes=[("Todos los archivos", "*.*")]
                )
                if filename:
                    self.file_var.set(filename)
        except Exception as e:
            logger.error(f"Error en selección de archivo/carpeta: {e}")
            messagebox.showerror("Error", f"No se pudo seleccionar archivo/carpeta: {e}")

    def send_file(self):
        """Envía archivo o carpeta"""
        filepath = self.file_var.get()
        mac_dst = self.file_dest_var.get().strip()
        reliable = self.reliable_var.get()

        if not filepath or not os.path.exists(filepath):
            messagebox.showwarning("Advertencia", "Seleccione una ruta válida (archivo o carpeta)")
            return
            
        if not mac_dst:
            messagebox.showwarning("Advertencia", "Debe especificar un destino")
            return

        try:
            transfer_id = self.file_sender.start_transfer(filepath, mac_dst, reliable)
            file_type = "carpeta" if os.path.isdir(filepath) else "archivo"
            
            if reliable:
                self.add_to_chat("SISTEMA", 
                    f"Transferencia confiable {transfer_id} iniciada: {os.path.basename(filepath)} ({file_type})", 
                    system=True)
            else:
                self.add_to_chat("SISTEMA", 
                    f"Transferencia no confiable {transfer_id} completada: {os.path.basename(filepath)} ({file_type})", 
                    system=True)
            
            self.file_var.set("")
            
        except Exception as e:
            messagebox.showerror("Error", f"Error enviando: {e}")

    def _refresh_downloads(self):
        """Actualiza la lista de descargas si hay nuevos archivos en el directorio."""
        try:
            current_files = set(os.listdir(self.download_dir))
            new_files = current_files - self._known_downloads
            if new_files:
                for f in new_files:
                    path = os.path.join(self.download_dir, f)
                    size = os.path.getsize(path)
                    self.add_download_notification(f"Archivo recibido: {f} ({size} bytes)")
                self._known_downloads = current_files
        except Exception as e:
            logger.debug(f"Error actualizando descargas: {e}")

    def add_download_notification(self, message: str):
        """Añade notificación de descarga"""
        self.download_text.config(state=tk.NORMAL)
        timestamp = time.strftime("%H:%M:%S")
        self.download_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.download_text.config(state=tk.DISABLED)
        self.download_text.see(tk.END)

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
            
        # Cerrar GUI
        if self.root:
            self.root.quit()
        logger.info("Aplicación detenida")

def signal_handler(app: ChatGUI, signum, frame):
    """Maneja señales de sistema para apagado limpio"""
    print(f"\nRecibida señal {signum}, cerrando...")
    app.stop()
    sys.exit(0)

def main():
    parser = argparse.ArgumentParser(description="Sistema de mensajería P2P con GUI")
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
        app = ChatGUI(args.interface, args.user)
        
        # Configurar manejador de señales
        signal.signal(signal.SIGINT, lambda s, f: signal_handler(app, s, f))
        signal.signal(signal.SIGTERM, lambda s, f: signal_handler(app, s, f))
        
        app.start()
        
    except Exception as e:
        logger.error(f"Error fatal: {e}")
        sys.exit(1)
    finally:
        if app:
            app.stop()

if __name__ == "__main__":
    main()