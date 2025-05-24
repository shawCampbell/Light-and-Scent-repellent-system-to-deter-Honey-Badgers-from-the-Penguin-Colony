import os
import socket
import json
import time
from threading import Thread
import random
from datetime import datetime

class ESPEmulator:
    def __init__(self, server_ip, server_port, esp_id="ESP32-CAM-001"):
        self.server_ip = server_ip
        self.server_port = server_port
        self.esp_id = esp_id
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(2.0)
        #self.ip_address = f"192.168.1.{100 + int(esp_id.split('-')[-1])}"
        #self.port_number = 1234
        
        port = random.randint(1500, 5000)
        self.ip_address = "196.47.241.166"#"197.239.167.94" # MAKE SURE THIS IS CORRECT!!!!
        self.port_number = port
        
        self.peers = []  # To store peer information
        self.running = True
        self.tcp_port = 1235
        self.last_detection_time = 0
        self.detection_interval = 30  # seconds
        self.ping_interval = 5  # seconds
        self.last_ping_time = 0
        
        # Create a test image if it doesn't exist
        self.test_image_path = "brokenTCP.jpg"#f"test_image_{esp_id}.jpg"
        '''if not os.path.exists(self.test_image_path):
            with open(self.test_image_path, 'wb') as f:
                f.write(b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xff\xd9')
'''
    def send_message(self, message_type):
        """Send message to server and handle response"""
        message = {
            "userID": self.esp_id,
            "ipAddress": self.ip_address,
            "portNumber": self.port_number,
            "messageType": message_type
        }
        
        try:
            self.sock.sendto(json.dumps(message).encode(), (self.server_ip, self.server_port))
            print(f"{self.esp_id}: Sent {message_type}")
            
            # Wait for response
            data, _ = self.sock.recvfrom(1024)
            response = json.loads(data.decode())
            
            if message_type == "registration":
                print(f"{self.esp_id}: Registration {response['responseType']}")
            elif message_type == "ping":
                if "peers" in response:
                    self.peers = response["peers"]
                    print(f"{self.esp_id}: Updated peers list - {len(self.peers)} active peers")
                    for i, peer in enumerate(self.peers):
                        print(f"Peer {i}: {peer['userID']} at {peer['ipAddress']}:{peer['portNumber']}")
            return True
            
        except socket.timeout:
            print(f"{self.esp_id}: No response from server (timeout)")
            return False
        except Exception as e:
            print(f"{self.esp_id}: Error - {str(e)}")
            return False

    def send_detection_to_peer(self, peer, header, image_data):
        """Attempt to send detection to a peer"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_sock:
                tcp_sock.settimeout(5.0)
                tcp_sock.connect((self.ip_address, 1237))#(("197.239.167.94", 1237))#((peer['ipAddress'], peer['portNumber']))
                #tcp_sock.connect((self.ip_address, self.port_number))
                
                # Modify header to indicate forwarding
                header['forwarded'] = True
                header['originalSender'] = self.esp_id
                header['forwardReason'] = "tcp_failure"
                
                # Send header and image
                tcp_sock.sendall((json.dumps(header) + "\n").encode())
                tcp_sock.sendall(image_data)
                print(f"{self.esp_id}: Forwarded detection to peer {peer['userID']}")
                return True
        except Exception as e:
            try:
                tcp_sock.settimeout(5.0)
                tcp_sock.connect((peer['ipAddress'], 1237))#(("197.239.167.94", 1237))#((peer['ipAddress'], peer['portNumber']))
                #tcp_sock.connect((self.ip_address, self.port_number))
                
                # Modify header to indicate forwarding
                header['forwarded'] = True
                header['originalSender'] = self.esp_id
                header['forwardReason'] = "tcp_failure"
                
                # Send header and image
                tcp_sock.sendall((json.dumps(header) + "\n").encode())
                tcp_sock.sendall(image_data)
                print(f"{self.esp_id}: Forwarded detection to peer {peer['userID']}")
                return True
            except Exception as e:
                return False
            return False

    def send_detection_alert(self):
        """Handle detection event with potential TCP failure and peer forwarding"""
        current_time = time.time()
        if current_time - self.last_detection_time < self.detection_interval:
            return
            
        self.last_detection_time = current_time
        
        # Read test image
        try:
            with open(self.test_image_path, 'rb') as f:
                image_data = f.read()
        except Exception as e:
            print(f"{self.esp_id}: Failed to read test image - {str(e)}")
            return
            
        # Create header
        header = {
            "userID": self.esp_id,
            "timestamp": int(current_time),
            "imageSize": len(image_data),
            "cameraStatus": "working",
            "detectionType": "motion"
        }
        
        # First try direct connection to server
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_sock:
                tcp_sock.settimeout(5.0)
                
                # Randomly decide to fail (for simulation)
                if True:#random.random() > 0.7:  # 30% chance of failure
                    raise ConnectionError("Simulated TCP connection failure")
                
                tcp_sock.connect((self.server_ip, self.tcp_port))
                tcp_sock.sendall((json.dumps(header) + "\n").encode())
                tcp_sock.sendall(image_data)
                print(f"{self.esp_id}: Sent detection directly to server")
                return
        except Exception as e:
            print(f"{self.esp_id}: Failed to connect to server - {str(e)}")
        
        # If direct connection fails, try peers
        if not self.peers:
            print(f"{self.esp_id}: No peers available for forwarding")
            return
            
        # Try each peer in order until one succeeds
        for peer in self.peers:
            if self.send_detection_to_peer(peer, header, image_data):
                return
                
        print(f"{self.esp_id}: All peer forwarding attempts failed")

    def handle_forwarded_detection(self, conn, addr):
        """Handle detection forwarded from another ESP"""
        try:
            print(f"{self.esp_id}: Received forwarded detection from {addr}")
            
            # Read header
            header_data = b''
            while True:
                chunk = conn.recv(1)
                if chunk == b'\n' or not chunk:
                    break
                header_data += chunk
                
            if not header_data:
                return
                
            try:
                header = json.loads(header_data.decode())
            except json.JSONDecodeError:
                print(f"{self.esp_id}: Invalid JSON header from {addr}")
                return
                
            # Verify this is a forwarded message
            if not header.get('forwarded'):
                print(f"{self.esp_id}: Received non-forwarded message directly")
                return
                
            # Get image size
            image_size = header.get('imageSize', 0)
            if image_size <= 0:
                print(f"{self.esp_id}: Invalid image size in forwarded message")
                return
                
            # Read image data
            image_data = conn.recv(image_size)
            
            # First try forwarding to server
            server_success = False
            '''try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_sock:
                    tcp_sock.settimeout(5.0)
                    tcp_sock.connect((self.server_ip, self.tcp_port))
                    
                    # Add forwarding info to header
                    header['forwardedBy'] = self.esp_id
                    
                    tcp_sock.sendall((json.dumps(header) + "\n").encode())
                    tcp_sock.sendall(image_data)
                    print(f"{self.esp_id}: Successfully forwarded detection from {header['originalSender']} to server")
                    server_success = True
            except Exception as e:
                print(f"{self.esp_id}: Failed to forward to server - {str(e)}")'''
            
            '''# Only try other peers if server forwarding failed
            if not server_success and self.peers:
                # Identify the original sender to avoid forwarding back to them
                original_sender = header.get('originalSender', '')
                last_forwarder = header.get('forwardedBy', '')
                
                # Try each peer that isn't the original sender or last forwarder
                for peer in self.peers:
                    if peer['userID'] != original_sender and peer['userID'] != last_forwarder:
                        if self.send_detection_to_peer(peer, header, image_data):
                            print(f"{self.esp_id}: Forwarded to alternate peer {peer['userID']}")
                            return
                
                print(f"{self.esp_id}: No eligible peers available for forwarding (avoiding {original_sender} and {last_forwarder})")'''
                    
        except Exception as e:
            print(f"{self.esp_id}: Error handling forwarded detection - {str(e)}")
        finally:
            conn.close()  

    def listen_for_peers(self):
        """Listen for forwarded detections from peers"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('0.0.0.0', self.port_number))
            s.listen(5)
            s.settimeout(1.0)
            
            while self.running:
                try:
                    conn, addr = s.accept()
                    Thread(target=self.handle_forwarded_detection, args=(conn, addr), daemon=True).start()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        print(f"{self.esp_id}: Peer listener error - {str(e)}")

    def run(self):
        """Main execution loop"""
        # Start peer listener thread
        Thread(target=self.listen_for_peers, daemon=True).start()
        
        # Initial registration
        while not self.send_message("registration"):
            time.sleep(5)
        
        # Main loop
        while self.running:
            current_time = time.time()
            
            # Regular pinging
            if current_time - self.last_ping_time >= self.ping_interval:
                success = self.send_message("ping")
                if not success and not self.send_message("registration"):
                    print(f"{self.esp_id}: Failed to reconnect")
                self.last_ping_time = current_time
            
            # Simulate detection event
            self.send_detection_alert()
            
            time.sleep(1)  # Short sleep to prevent busy loop

    def stop(self):
        self.running = False
        self.sock.close()

if __name__ == "__main__":
    SERVER_IP = "127.0.0.1"  # Change to your server's IP
    SERVER_PORT = 1234
    
    id = random.randint(3, 100)
    
    emulator = ESPEmulator(SERVER_IP, SERVER_PORT, "ESP32-CAM-00" + str(id))
    try:
        emulator.run()
    except KeyboardInterrupt:
        emulator.stop()