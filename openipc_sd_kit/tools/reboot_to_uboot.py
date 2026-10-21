import time, os, sys

in_path = os.path.expanduser("~/Downloads/tc100-fix/uart-in.txt")
log_path = os.path.expanduser("~/Downloads/tc100-fix/uart.log")

print("Envoi de la commande reboot a Linux...")
with open(in_path, "a") as f:
    f.write("reboot\r\n")

print("Attente du redemarrage et interception U-Boot...")
caught = False
for i in range(150):
    time.sleep(0.08)
    with open(in_path, "a") as f:
        f.write("\r")
    with open(log_path, "r", encoding="latin1", errors="replace") as f:
        lines = f.readlines()[-15:]
        tail = "".join(lines)
        if "anyka$" in tail:
            print(">>> SUCCES : PROMPT U-BOOT anyka$ INTERCEPTE ! <<<")
            caught = True
            break

if not caught:
    print("Non intercepte")
