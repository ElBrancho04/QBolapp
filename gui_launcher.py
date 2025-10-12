#!/usr/bin/env python3
"""
gui_launcher.py - Lanzador con selección de interfaz
"""
import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import sys
import netifaces

class LauncherGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("QBolapp - Configuración")
        self.root.geometry("500x300")
        self.setup_gui()

    def get_available_interfaces(self):
        """Obtiene las interfaces de red disponibles"""
        try:
            interfaces = netifaces.interfaces()
            # Filtrar interfaces comunes (opcional, podríamos mostrar todas)
            common_interfaces = [iface for iface in interfaces 
                               if iface.startswith(('eth', 'wlan', 'en', 'wl', 'veth')) 
                               or iface in ['lo', 'docker0', 'br-']]
            return sorted(common_interfaces) if common_interfaces else interfaces
        except:
            # Fallback si netifaces no está disponible
            return ["wlan0", "eth0", "lo", "docker0"]

    def setup_gui(self):
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Configuración de Conexión", 
                 font=('Arial', 14, 'bold')).pack(pady=10)

        # Campo de usuario
        user_frame = ttk.Frame(main_frame)
        user_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(user_frame, text="Nombre de usuario:").pack(side=tk.LEFT)
        self.user_var = tk.StringVar()
        user_entry = ttk.Entry(user_frame, textvariable=self.user_var, width=25)
        user_entry.pack(side=tk.LEFT, padx=5)
        user_entry.focus()

        # Selección de interfaz - Ahora con combo editable
        interface_frame = ttk.Frame(main_frame)
        interface_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(interface_frame, text="Interfaz de red:").pack(side=tk.LEFT)
        
        available_interfaces = self.get_available_interfaces()
        self.interface_var = tk.StringVar(value=available_interfaces[0] if available_interfaces else "wlan0")
        
        # ComboBox editable para permitir cualquier interfaz
        interface_combo = ttk.Combobox(interface_frame, 
                                      textvariable=self.interface_var,
                                      values=available_interfaces,
                                      state="normal")  # "normal" permite escribir
        interface_combo.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        # Botón para refrescar interfaces
        ttk.Button(interface_frame, text="Refrescar", 
                  command=self.refresh_interfaces).pack(side=tk.RIGHT, padx=5)

        # Frame para información de interfaces
        info_frame = ttk.LabelFrame(main_frame, text="Interfaces Disponibles")
        info_frame.pack(fill=tk.X, pady=5)
        
        info_text = tk.Text(info_frame, height=4, width=50, wrap=tk.WORD)
        info_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        interfaces_list = ", ".join(available_interfaces) if available_interfaces else "No se pudieron detectar interfaces"
        info_text.insert(tk.END, f"Interfaces detectadas: {interfaces_list}\n\n")
        info_text.insert(tk.END, "Puede escribir cualquier interfaz manualmente (ej: veth0, veth1, eth1, etc.)")
        info_text.config(state=tk.DISABLED)

        # Checkbox para debug
        self.debug_var = tk.BooleanVar()
        ttk.Checkbutton(main_frame, text="Modo Debug", 
                       variable=self.debug_var).pack(pady=5)

        # Botones
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(pady=10)
        
        ttk.Button(btn_frame, text="Iniciar Chat", 
                  command=self.launch_chat).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Salir", 
                  command=self.root.quit).pack(side=tk.LEFT, padx=5)

    def refresh_interfaces(self):
        """Actualiza la lista de interfaces disponibles"""
        available_interfaces = self.get_available_interfaces()
        # Podríamos actualizar el combobox aquí si quisiéramos

    def launch_chat(self):
        username = self.user_var.get().strip()
        interface = self.interface_var.get().strip()
        
        if not username:
            messagebox.showerror("Error", "Debe ingresar un nombre de usuario")
            return
            
        if not interface:
            messagebox.showerror("Error", "Debe ingresar una interfaz de red")
            return

        # Construir comando
        cmd = [sys.executable, "gui_main.py", "-u", username, "-i", interface]
        
        if self.debug_var.get():
            cmd.append("--debug")

        try:
            # Cerrar lanzador
            self.root.destroy()
            
            # Ejecutar chat
            subprocess.run(cmd)
            
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo iniciar la aplicación: {e}")

    def start(self):
        self.root.mainloop()

if __name__ == "__main__":
    launcher = LauncherGUI()
    launcher.start()