import socket
import json
import time
from threading import Thread
import random

class ESPEmulator:
    def __init__(self, server_ip, server_port, esp_id="ESP32-CAM-001"):
        self.server_ip = server_ip
        self.server_port = server_port
        self.esp_id = esp_id
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(2.0)
        self.ip_address = f"192.168.1.{100 + int(esp_id.split('-')[-1])}"
        self.port_number = 1234
        self.peers = []  # To store peer information
        self.running = True
        tcp_port = 1235

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
            #print(f"{self.esp_id}: Sent {message_type}")
            print(f"{self.esp_id}: Sent {message}")
            
            # Wait for response
            data, _ = self.sock.recvfrom(1024)
            response = json.loads(data.decode())
            
            if message_type == "registration":
                print(f"{self.esp_id}: Registration {response['responseType']}")
            elif message_type == "ping":
                if "peers" in response:
                    self.peers = response["peers"]
                    print(f"{self.esp_id}: Updated peers list - {len(self.peers)} active peers")
                    for i in range(len(self.peers)):
                        print("Peer " + str(i) + ": " + self.peers[i]["userID"] + " at " + self.peers[i]["ipAddress"])
                    #Peer 0: ESP32-CAM-002 at 192.168.1.102:1234
            return True
            
        except socket.timeout:
            print(f"{self.esp_id}: No response from server (timeout)")
            return False
        except Exception as e:
            print(f"{self.esp_id}: Error - {str(e)}")
            return False
        
    def send_detection_alert(self):
        """Send detection alert to server (with camera failure flag)"""
        tcp_port = 1235
        #server = "196.47.245.58"
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_sock:
                tcp_sock.connect((self.server_ip, tcp_port))
                
                # Create detection message
                message = {
                    "userID": self.esp_id,
                    "timestamp": int(time.time()),
                    "cameraStatus": "broken",
                    "detectionType": "motion"  # Example detection type
                }
                
                # Send JSON message
                tcp_sock.sendall((json.dumps(message) + "\n").encode())
                print(f"{self.esp_id}: Sent detection alert (camera broken)")
                
        except Exception as e:
            print(f"{self.esp_id}: Failed to send detection alert - {str(e)}")

    def run(self):
        """Main execution loop"""
        # Initial registration
        while not self.send_message("registration"):
            time.sleep(5)
        
        # Regular pinging
        while self.running:
            success = self.send_message("ping")
            if not success and not self.send_message("registration"):
                print(f"{self.esp_id}: Failed to reconnect")
            time.sleep(5)
            
            #time.sleep(10)
            self.send_detection_alert()

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