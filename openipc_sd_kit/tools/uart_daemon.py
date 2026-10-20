import os, sys, time, termios, tty, select, glob

log_path = "~/Downloads/tc100-fix/uart.log"
in_path = "~/Downloads/tc100-fix/uart-in.txt"

def run_bridge():
    while True:
        devices = glob.glob("/dev/cu.usbmodem*")
        if not devices:
            time.sleep(0.5)
            continue
        dev = devices[0]
        try:
            fd = os.open(dev, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            attrs = termios.tcgetattr(fd)
            tty.setraw(fd)
            attrs[4] = termios.B115200
            attrs[5] = termios.B115200
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
            
            with open(log_path, "a") as log_f:
                log_f.write(f"\n=== UART DAEMON CONNECTED {dev} {time.ctime()} ===\n")
                log_f.flush()
                
                in_pos = os.path.getsize(in_path) if os.path.exists(in_path) else 0
                
                while True:
                    r, _, _ = select.select([fd], [], [], 0.05)
                    if r:
                        chunk = os.read(fd, 4096)
                        if not chunk:
                            break
                        log_f.write(chunk.decode("latin1", errors="replace"))
                        log_f.flush()
                    
                    if os.path.exists(in_path):
                        sz = os.path.getsize(in_path)
                        if sz > in_pos:
                            with open(in_path, "r", encoding="latin1") as inf:
                                inf.seek(in_pos)
                                data = inf.read()
                                in_pos = sz
                                if data:
                                    os.write(fd, data.encode("latin1"))
        except Exception as e:
            time.sleep(0.5)

run_bridge()
