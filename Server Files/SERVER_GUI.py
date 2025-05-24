import socket
import json
import time
import os
from datetime import datetime
from threading import Thread, Lock
from collections import defaultdict
import tkinter as tk
from tkinter import ttk, scrolledtext
from PIL import Image, ImageTk
import pygame
import io
import queue

class UnifiedESPServer:
    def __init__(self):
        # Configuration
        self.IMAGE_DIR = "detected_images"
        os.makedirs(self.IMAGE_DIR, exist_ok=True)
        
        # UDP Server (Device Registry)
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_sock.settimeout(1.0)
        self.udp_running = True
        self.devices = []
        self.devices_lock = Lock()
        self.last_ping = defaultdict(float)
        
        # TCP Server (Image Server)
        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_running = True
        
        # GUI communication queue
        self.gui_queue = queue.Queue()
        
        # GUI variables
        self.root = None
        self.device_tree = None
        self.log_text = None
        self.current_image_label = None
        self.notification_sound = None
        self.detection_info_label = None
        self.dismiss_btn = None
        
        # Detection event tracking
        self.latest_detection = None
        self.latest_image = None

    # UDP Server Functions
    def update_device(self, device_info, registration):
        with self.devices_lock:
            existing = next((d for d in self.devices 
                           if d['userID'] == device_info['userID']), None)
            if existing:
                existing.update(device_info)
            else:
                self.devices.append(device_info)

            self.last_ping[device_info['userID']] = time.time()

            msg = f"Device {device_info['userID']} {'registered' if registration else 'updated'}"
            self.gui_queue.put(('log', msg))
            self.gui_queue.put(('update_devices', None))

    def get_active_peers(self, exclude_id=None):
        with self.devices_lock:
            active_peers = []
            current_time = time.time()

            for device in self.devices:
                if exclude_id and device['userID'] == exclude_id:
                    continue

                if (current_time - self.last_ping.get(device['userID'], 0)) <= 10:
                    active_peers.append({
                        "userID": device['userID'],
                        "ipAddress": device['ipAddress'],
                        "portNumber": device['portNumber']
                    })

            return active_peers

    def cleanup_inactive(self):
        with self.devices_lock:
            current_time = time.time()
            inactive = [id for id, last in self.last_ping.items() 
                      if (current_time - last) > 10]

            for id in inactive:
                if id in self.last_ping:
                    del self.last_ping[id]
                self.devices = [d for d in self.devices if d['userID'] != id]

            if inactive:
                self.gui_queue.put(('log', f"Cleaned up inactive devices: {inactive}"))
                self.gui_queue.put(('update_devices', None))

    def handle_udp_request(self):
        while self.udp_running:
            try:
                data, addr = self.udp_sock.recvfrom(1024)
                try:
                    message = json.loads(data.decode())
                except json.JSONDecodeError:
                    self.gui_queue.put(('log', f"Invalid JSON from {addr}"))
                    continue

                if message.get("messageType") in ["registration", "ping"]:
                    device_info = {
                        "userID": message["userID"],
                        "ipAddress": message["ipAddress"],
                        "portNumber": message["portNumber"],
                        "lastSeen": time.time(),
                        "clientAddress": addr
                    }
                    
                    self.update_device(device_info, message.get("messageType") == "registration")

                    active_peers = self.get_active_peers(exclude_id=message["userID"])
                    response = {
                        "responseType": "acknowledged",
                        "peers": active_peers
                    }

                    self.udp_sock.sendto(json.dumps(response).encode(), addr)

            except socket.timeout:
                self.cleanup_inactive()
                continue
            except Exception as e:
                self.gui_queue.put(('log', f"UDP Server error: {str(e)}"))
                if not self.udp_running:
                    break

    # TCP Server Functions
    def handle_broken_camera(self, header):
        dt_str = datetime.fromtimestamp(header["timestamp"]).strftime("%Y%m%d_%H%M%S")
        filename = f"{header['userID']}_{dt_str}_CAMERA_FAILURE.txt"
        filepath = os.path.join(self.IMAGE_DIR, filename)

        with open(filepath, 'w') as f:
            f.write(f"Camera malfunction detected\n")
            f.write(f"Device: {header['userID']}\n")
            f.write(f"Time: {datetime.fromtimestamp(header['timestamp'])}\n")
            f.write(f"Detection Type: {header.get('detectionType', 'unknown')}\n")

        self.gui_queue.put(('log', f"Logged camera failure from {header['userID']} as {filename}"))
        self._show_detection(False, filename)

    def handle_tcp_client(self, conn, addr):
        try:
            self.gui_queue.put(('log', f"Connection from {addr}"))
            
            # First read the JSON header line
            header_data = b''
            while True:
                chunk = conn.recv(1)
                if chunk == b'\n' or not chunk:
                    break
                header_data += chunk
            
            if not header_data:
                return
                
            try:
                header = json.loads(header_data.decode('utf-8'))
            except json.JSONDecodeError:
                self.gui_queue.put(('log', f"Invalid JSON header from {addr}"))
                conn.close()
                return
                
            # Handle broken camera case
            if header.get("cameraStatus") == "broken":
                self.handle_broken_camera(header)
                conn.close()
                return
                
            # Process image data
            if "imageSize" not in header:
                self.gui_queue.put(('log', f"No image size in header from {addr}"))
                conn.close()
                return
                
            # Create filename
            dt_str = datetime.fromtimestamp(header["timestamp"]).strftime("%Y%m%d_%H%M%S")
            filename = f"{header['userID']}_{dt_str}.jpg"
            filepath = os.path.join(self.IMAGE_DIR, filename)
            
            # Receive binary image data
            remaining_bytes = header["imageSize"]
            received_bytes = 0
            image_data = bytearray()
            with open(filepath, 'wb') as f:
                while remaining_bytes > 0:
                    chunk = conn.recv(min(4096, remaining_bytes))
                    if not chunk:
                        break
                    f.write(chunk)
                    image_data.extend(chunk)
                    remaining_bytes -= len(chunk)
                    received_bytes += len(chunk)
            
            self.gui_queue.put(('log', f"Received {received_bytes} bytes from {header['userID']} saved as {filename}"))
            
            # Store the latest detection and image
            self.latest_detection = {
                "userID": header["userID"],
                "timestamp": header["timestamp"],
                "filename": filename,
                "filepath": filepath
            }
            
            # Store image data for display
            self.latest_image = image_data
            
            # Trigger GUI update
            self.gui_queue.put(('show_detection', None))
            
        except Exception as e:
            self.gui_queue.put(('log', f"Error handling client: {str(e)}"))
        finally:
            conn.close()

    def start_tcp_server(self):
        self.tcp_sock.bind(('0.0.0.0', 1235))
        self.tcp_sock.listen(5)
        self.gui_queue.put(('log', "TCP Image Server listening on 0.0.0.0:1235"))
        
        while self.tcp_running:
            try:
                conn, addr = self.tcp_sock.accept()
                Thread(target=self.handle_tcp_client, args=(conn, addr), daemon=True).start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.tcp_running:
                    self.gui_queue.put(('log', f"TCP Server error: {str(e)}"))

    # GUI Functions
    def process_gui_queue(self):
        try:
            while True:
                task, data = self.gui_queue.get_nowait()
                if task == 'log':
                    self._log_message(data)
                elif task == 'update_devices':
                    self._update_gui_devices()
                elif task == 'show_detection':
                    self._show_detection(True, "")
        except queue.Empty:
            pass
        self.root.after(100, self.process_gui_queue)

    def _log_message(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"
        
        self.log_text.insert(tk.END, log_entry)
        self.log_text.see(tk.END)

    def _update_gui_devices(self):
        current_time = time.time()
        self.device_tree.delete(*self.device_tree.get_children())
        
        with self.devices_lock:
            for device in self.devices:
                last_seen = current_time - self.last_ping.get(device['userID'], 0)
                status = "Active" if last_seen <= 20 else "Inactive"
                last_seen_str = f"{last_seen:.1f}s ago" if last_seen <= 60 else ">1m ago"
                
                self.device_tree.insert("", "end", values=(
                    device['userID'],
                    device['ipAddress'],
                    device['portNumber'],
                    status,
                    last_seen_str
                ))

    '''def _show_detection(self):
        if not self.latest_detection:
            return
            
        # Change frame style to alert
        self.detection_frame.configure(style='Alert.TLabelframe')
        
        # Remove existing dismiss button if it exists
        if hasattr(self, 'dismiss_btn'):
            self.dismiss_btn.pack_forget()  
        
        # Add dismiss button if not already there
        if not hasattr(self, 'dismiss_btn'):
            self.dismiss_btn = ttk.Button(
                self.detection_frame,
                text="Dismiss Alert",
                command=self._dismiss_alert
            )
            self.dismiss_btn.pack(pady=10)
        
        # Play notification sound
        try:
            if not self.notification_sound:
                # Generate a simple beep sound
                pygame.mixer.init()
                self.notification_sound = pygame.mixer.Sound(
                    buffer=self._generate_beep())
            self.notification_sound.play()
        except Exception as e:
            self._log_message(f"Error playing sound: {str(e)}")
        
        # Update the GUI
        try:
            # Load and display the image
            image = Image.open(io.BytesIO(self.latest_image))
            image.thumbnail((300, 300))
            photo = ImageTk.PhotoImage(image)
            
            self.current_image_label.config(image=photo)
            self.current_image_label.image = photo  # Keep reference
                
            # Show detection info
            now = datetime.now()
            date_time_str = now.strftime("%Y-%m-%d %H:%M:%S")
            date_str = now.strftime("%B %d, %Y")
            time_str = now.strftime("%I:%M %p")
            
            detection_time = date_time_str
            detection_text = f"Detection Event\nDevice: {self.latest_detection['userID']}\nTime: {detection_time}"
            
            self.detection_info_label.config(text=detection_text)
                
        except Exception as e:
            self._log_message(f"Error displaying image: {str(e)}")'''
    def _show_detection(self, camera_working, filename):
        if not self.latest_detection and camera_working:
            return
    
        try:
            # 1. First display the image and info
            if (camera_working):
                image = Image.open(io.BytesIO(self.latest_image))
                image.thumbnail((180, 180))
                photo = ImageTk.PhotoImage(image)
        
                self.current_image_label.config(image=photo)
                self.current_image_label.image = photo
        
                detection_time = datetime.fromtimestamp(
                    self.latest_detection["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
                detection_text = (f"Detection Event\n"
                                  f"Device: {self.latest_detection['userID']}\n"
                                f"Time: {detection_time}")
        
                self.detection_info_label.config(text=detection_text)
            else:
                if (not self.latest_detection):
                    image = Image.open(io.BytesIO(self.latest_image))
                    image.thumbnail((1, 1))
                    photo = ImageTk.PhotoImage(image)
                
                    self.current_image_label.config(None)
                    self.current_image_label.image = None
            
                detection_time = filename
                detection_text = filename
            
                self.detection_info_label.config(text=detection_text)                
        except Exception as e:
            self._log_message(f"Error displaying image: {str(e)}")
    
        # 2. Change frame style to alert
        self.detection_frame.configure(style='Alert.TLabelframe')
    
        # 3. Handle the dismiss button more safely
        if hasattr(self, 'dismiss_btn') and self.dismiss_btn is not None:
            try:
                self.dismiss_btn.destroy()
            except:
                pass
    
        self.dismiss_btn = ttk.Button(
            self.detection_frame,
            text="DISMISS ALERT",
            command=self._dismiss_alert,
            style='Emergency.TButton'
        )
        self.dismiss_btn.pack(pady=15, ipadx=30, ipady=8, fill=tk.X, padx=20)
    
        # 4. Play sound notification
        try:
            if not self.notification_sound:
                pygame.mixer.init()
                self.notification_sound = pygame.mixer.Sound(
                    buffer=self._generate_beep())
            self.notification_sound.play()
        except Exception as e:
            self._log_message(f"Error playing sound: {str(e)}")

    def _dismiss_alert(self):
        """Reset the detection frame to normal appearance"""
        # Change frame back to normal style
        self.detection_frame.configure(style='Normal.TLabelframe')
        
        # Safely remove the dismiss button
        if hasattr(self, 'dismiss_btn') and self.dismiss_btn is not None:
            try:
                self.dismiss_btn.destroy()
            except:
                pass
            self.dismiss_btn = None      

    def _generate_beep(self):
        # Generate a simple beep sound (440Hz for 0.5s)
        import numpy as np
        sample_rate = 44100
        duration = 0.5
        frequency = 500
        
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        wave = np.sin(2 * np.pi * frequency * t)
        audio = np.int16(wave * 32767)
        
        return audio.tobytes()

    def create_gui(self):
        self.root = tk.Tk()
        self.root.title("ESP Monitoring System")
        self.root.geometry("1000x700")
        
        # Configure grid layout
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)
        
        # Set a theme that supports styling
        #style = ttk.Style()
        #style.theme_use('clam')
        
        
        style = ttk.Style()
        style.theme_use('clam')
        
        # Alert frame style (more visible)
        style.configure('Alert.TLabelframe',
                       background='#ffebeb',  # Very light red
                       bordercolor='red',
                       borderwidth=4,
                       relief='ridge',
                       labelmargins=(10,10,10,10))  # Add padding inside frame
        
        # Emergency button style
        style.configure('Emergency.TButton',
                       foreground='white',
                       background='#ff4444',
                       font=('Helvetica', 30, 'bold'),
                       padding=10,
                       borderwidth=3,
                       relief='raised')
        style.map('Emergency.TButton',
                 background=[('active', '#ff0000'), ('!active', '#ff4444')])        
        
        
        # Device List Frame
        device_frame = ttk.LabelFrame(self.root, text="Registered Devices", padding=10)
        device_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        
        # Device Treeview
        columns = ("ID", "IP", "Port", "Status", "Last Seen")
        self.device_tree = ttk.Treeview(device_frame, columns=columns, show="headings")
        
        for col in columns:
            self.device_tree.heading(col, text=col)
            self.device_tree.column(col, width=100, anchor='center')
            
        scrollbar = ttk.Scrollbar(device_frame, orient="vertical", command=self.device_tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.device_tree.configure(yscrollcommand=scrollbar.set)
        self.device_tree.pack(fill="both", expand=True)
        
        # Detection Display Frame
        self.detection_frame = ttk.LabelFrame(
            self.root, 
            text="Latest Detection", 
            padding=10,
            style='Normal.TLabelframe'
        )
        self.detection_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        
        # Detection Image
        self.current_image_label = ttk.Label(self.detection_frame)
        self.current_image_label.pack(pady=10)
        
        # Detection Info
        self.detection_info_label = ttk.Label(
            self.detection_frame, 
            text="No detections yet", 
            font=('Helvetica', 12),
            justify='center'
        )
        self.detection_info_label.pack(pady=10)
        
        # Log Frame
        log_frame = ttk.LabelFrame(self.root, text="System Log", padding=10)
        log_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)
        
        # Log Text
        self.log_text = scrolledtext.ScrolledText(
            log_frame, 
            wrap=tk.WORD, 
            width=80, 
            height=15,
            font=('Consolas', 10)
        )
        self.log_text.pack(fill="both", expand=True)
        
        # Control Buttons Frame
        button_frame = ttk.Frame(self.root)
        button_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
        
        # Refresh Button
        refresh_btn = ttk.Button(
            button_frame, 
            text="Refresh Devices", 
            command=self._update_gui_devices
        )
        refresh_btn.pack(side="left", padx=5)
        
        # Clear Log Button
        clear_log_btn = ttk.Button(
            button_frame, 
            text="Clear Log", 
            command=lambda: self.log_text.delete(1.0, tk.END)
        )
        clear_log_btn.pack(side="left", padx=5)
        
        # Exit Button
        exit_btn = ttk.Button(
            button_frame, 
            text="Exit", 
            command=self.shutdown
        )
        exit_btn.pack(side="right", padx=5)
        
        # Start periodic GUI updates
        self.process_gui_queue()

    # Main Control Functions
    def start_servers(self):
        # Start UDP server in a separate thread
        Thread(target=self._run_udp_server, daemon=True).start()
        
        # Start TCP server in a separate thread
        Thread(target=self.start_tcp_server, daemon=True).start()

    def _run_udp_server(self):
        self.udp_sock.bind(('0.0.0.0', 1234))
        self.gui_queue.put(('log', "UDP Server listening on 0.0.0.0:1234"))
        self.handle_udp_request()

    def shutdown(self):
        self.gui_queue.put(('log', "Shutting down servers..."))
        self.udp_running = False
        self.tcp_running = False
        
        try:
            self.udp_sock.close()
        except:
            pass
            
        try:
            self.tcp_sock.close()
        except:
            pass
            
        if self.root:
            self.root.quit()
            self.root.destroy()

    def run(self):
        self.start_servers()
        self.create_gui()
        self.root.mainloop()

if __name__ == "__main__":
    server = UnifiedESPServer()
    try:
        server.run()
    except KeyboardInterrupt:
        server.shutdown()